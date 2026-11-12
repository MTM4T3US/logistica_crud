"""JARVIS Core — servidor local (FastAPI). Escuta só em 127.0.0.1.

REST para estado/ajustes e um WebSocket para os eventos em tempo real do HUD.
Uso:  python -m app.main      (a partir de jarvis-hud/backend)
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .assistant import MAX_AUDIO_BYTES, VERSION, Assistant, Connection
from .config import PROJECT_DIR, Settings, load_settings
from .security.permissions import LocalAuth
from .voice.tts import TTSError

OPEN_PATHS = {"/api/health", "/api/session"}
SYSTEM_PERIOD_S = 2.5
WEATHER_PERIOD_S = 600.0


def create_app(settings: Settings | None = None, assistant: Assistant | None = None) -> FastAPI:
    settings = settings or load_settings()
    core = assistant or Assistant(settings)
    auth = LocalAuth(settings.local_token, settings.origins(), settings.port)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await core.startup()
        yield

    app = FastAPI(title="JARVIS Core", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.core, app.state.auth, app.state.settings = core, auth, settings

    def cors(origin: str | None) -> dict[str, str]:
        if origin and origin in auth.origins:
            return {"Access-Control-Allow-Origin": origin, "Vary": "Origin", "Access-Control-Allow-Headers": "Content-Type, X-Jarvis-Token", "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS"}
        return {}

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        origin = request.headers.get("origin")
        if not auth.host_ok(request.headers.get("host")):
            return JSONResponse({"error": "host não permitido"}, status_code=403)
        if not auth.origin_ok(origin, required=path == "/api/session"):
            return JSONResponse({"error": "origem não permitida"}, status_code=403)
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=cors(origin))
        if path not in OPEN_PATHS and not auth.token_ok(request.headers.get("x-jarvis-token")):
            return JSONResponse({"error": "token ausente ou inválido"}, status_code=401, headers=cors(origin))
        response = await call_next(request)
        for key, value in cors(origin).items():
            response.headers[key] = value
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "name": "JARVIS Core", "version": VERSION}

    @app.post("/api/session")
    async def session() -> dict[str, Any]:
        """Entrega o token de sessão — só para origens permitidas (o Origin é exigido aqui)."""
        return {"token": auth.token, "version": VERSION}

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        return await core.state()

    @app.post("/api/settings")
    async def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
        await asyncio.to_thread(core.update_runtime, patch)
        return await core.state()

    @app.get("/api/weather")
    async def weather(force: bool = False) -> dict[str, Any]:
        return await core.weather.get(force=force)

    @app.get("/api/system")
    async def system() -> dict[str, Any]:
        return await asyncio.to_thread(core.monitor.details)

    @app.get("/api/history")
    async def history(limit: int = 40) -> dict[str, Any]:
        return {"messages": await asyncio.to_thread(core.memory.recent_messages, max(1, min(limit, 200)))}

    @app.delete("/api/history")
    async def clear_history() -> dict[str, Any]:
        await asyncio.to_thread(core.memory.clear_messages)
        return {"ok": True}

    @app.get("/api/actions")
    async def actions(limit: int = 30) -> dict[str, Any]:
        return {"actions": await asyncio.to_thread(core.memory.recent_actions, max(1, min(limit, 200)))}

    @app.get("/api/memory")
    async def memory() -> dict[str, Any]:
        return {"enabled": core.runtime()["memory_enabled"], "facts": await asyncio.to_thread(core.memory.facts)}

    @app.delete("/api/memory")
    async def clear_memory() -> dict[str, Any]:
        await asyncio.to_thread(core.memory.clear_facts)
        return {"ok": True}

    @app.post("/api/voice/sample")
    async def voice_sample(body: dict[str, Any]) -> dict[str, Any]:
        try:
            return await core.voice_sample(str(body.get("engine", "")), body.get("voice"), body.get("text"), body.get("style"))
        except TTSError as err:
            raise HTTPException(status_code=503, detail={"code": err.code, "message": err.message}) from None

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        ok = auth.host_ok(ws.headers.get("host")) and auth.origin_ok(ws.headers.get("origin"), required=True) and auth.token_ok(ws.query_params.get("token"))
        if not ok:
            await ws.close(code=4403)
            return
        await ws.accept()
        conn = Connection(ws)
        await conn.send({"type": "hello", "version": VERSION, "state": await core.state()})
        feeder = asyncio.create_task(_feed(conn, core))
        try:
            while True:
                msg = await ws.receive_json()
                kind = msg.get("type") if isinstance(msg, dict) else None
                if kind == "user_text":
                    text = str(msg.get("text", "")).strip()
                    if text:
                        await conn.cancel_turn()
                        conn.turn = asyncio.create_task(core.run_turn(conn, text, "text"))
                elif kind == "user_audio":
                    raw = msg.get("wav", "")
                    if not isinstance(raw, str) or len(raw) > MAX_AUDIO_BYTES * 4 // 3 + 8:
                        await conn.send({"type": "error", "scope": "stt", "code": "bad_audio", "message": "Gravação ausente ou grande demais."})
                        continue
                    try:
                        wav = base64.b64decode(raw, validate=True)
                    except (binascii.Error, ValueError):
                        await conn.send({"type": "error", "scope": "stt", "code": "bad_audio", "message": "Áudio corrompido."})
                        continue
                    await conn.cancel_turn()
                    conn.turn = asyncio.create_task(core.handle_audio(conn, wav, "wake" if msg.get("mode") == "wake" else "ptt"))
                elif kind == "interrupt":
                    if await conn.cancel_turn():
                        await conn.send({"type": "phase", "phase": "idle"})
                elif kind == "confirm":
                    conn.resolve_confirm(str(msg.get("id", "")), bool(msg.get("approve")))
                elif kind == "refresh":
                    await conn.send({"type": "state", "state": await core.state()})
                    await conn.send({"type": "weather", "weather": await core.weather.get(force=bool(msg.get("force")))})
        except WebSocketDisconnect:
            pass
        except Exception:
            with contextlib.suppress(Exception):
                await ws.close(code=1011)
        finally:
            conn.closed = True
            feeder.cancel()
            await conn.cancel_turn()

    dist = PROJECT_DIR / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="hud")
    return app


async def _feed(conn: Connection, core: Assistant) -> None:
    """Empurra leituras reais para o HUD: sistema a cada 2,5 s; clima a cada 10 min.

    O clima roda em tarefa própria: um provedor lento nunca atrasa as leituras do sistema."""

    async def weather_loop() -> None:
        while not conn.closed:
            await conn.send({"type": "weather", "weather": await core.weather.get()})
            if core.news.enabled:
                await conn.send({"type": "news", "news": await core.news.get()})
            await asyncio.sleep(WEATHER_PERIOD_S)

    weather = asyncio.create_task(weather_loop())
    try:
        while not conn.closed:
            await conn.send({"type": "system", "system": await asyncio.to_thread(core.monitor.snapshot)})
            await asyncio.sleep(SYSTEM_PERIOD_S)
    finally:
        weather.cancel()


def run() -> None:
    import uvicorn

    settings = load_settings()
    print(f"JARVIS Core {VERSION} em http://{settings.host}:{settings.port}  |  IA: {'Gemini (' + settings.gemini_model + ')' if settings.ai_configured else 'não configurada (modo local)'}")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    run()
