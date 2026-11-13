"""JARVIS Core — servidor local (FastAPI). Escuta só em 127.0.0.1.

REST para estado/ajustes e um WebSocket para os eventos em tempo real do HUD.
Uso:  python -m app.main      (a partir de jarvis-hud/backend)
"""
from __future__ import annotations

import asyncio
import base64
import os
import binascii
import contextlib
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .assistant import MAX_AUDIO_BYTES, VERSION, Assistant, Connection
from .config import PROJECT_DIR, Settings, load_settings
from .security.permissions import LocalAuth
from .voice.tts import TTSError

OPEN_PATHS = {"/api/health", "/api/session"}
#: com a entrada por rosto ativa e o JARVIS bloqueado, só isto responde
LOCKED_PATHS = {"/api/state"}
#: mensagens aceitas pelo WebSocket enquanto o JARVIS está bloqueado
LOCKED_MESSAGES = {"face_verify", "pin_verify", "refresh", "face_enroll"}
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
        await core.shutdown()

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
        if path not in OPEN_PATHS and path not in LOCKED_PATHS and not core.gate.open:
            return JSONResponse({"error": "JARVIS bloqueado: confirme seu rosto (ou o PIN) para continuar."}, status_code=423, headers=cors(origin))
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

    @app.post("/api/devices/{device_id}/{action}")
    async def device_action(device_id: str, action: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Ações de manutenção vindas do painel (procurar, conectar, desconectar, estado).
        Comandos de luz pela IA/roteador passam pelas ferramentas, não por aqui."""
        if action not in ("scan", "connect", "disconnect", "status"):
            raise HTTPException(status_code=400, detail={"message": "Ação não permitida por esta rota."})
        res = await core.devices.command(device_id, action, body or {})
        return {"ok": res.ok, "executed": res.executed, "simulated": res.simulated, "message": res.message, "state": res.state, "devices": core.devices.describe()}

    @app.post("/api/perf")
    async def perf_report(body: dict[str, Any]) -> dict[str, Any]:
        """Relatório de desempenho: métricas do HUD (FPS medidos no navegador) + leituras reais do sistema."""
        from .services.perf import write_report

        path, text = await asyncio.to_thread(write_report, settings.db_path.parent, body, core.monitor)
        return {"path": str(path), "markdown": text}

    @app.post("/api/voice/sample")
    async def voice_sample(body: dict[str, Any]) -> dict[str, Any]:
        try:
            return await core.voice_sample(str(body.get("engine", "")), body.get("voice"), body.get("text"), body.get("style"))
        except TTSError as err:
            raise HTTPException(status_code=503, detail={"code": err.code, "message": err.message}) from None

    @app.get("/api/intro/music")
    async def intro_music_get() -> FileResponse:
        path = core.intro_music()
        if path is None:
            raise HTTPException(status_code=404, detail={"message": "Nenhuma música de entrada escolhida."})
        return FileResponse(path, media_type=core.MUSIC_TYPES[path.suffix.lower()])

    @app.post("/api/intro/music")
    async def intro_music_put(request: Request) -> dict[str, Any]:
        """Recebe o arquivo de música escolhido pelo usuário (fica só em backend/data/entrada/)."""
        from urllib.parse import unquote

        size = int(request.headers.get("content-length") or 0)
        if size > core.MUSIC_MAX_BYTES:
            raise HTTPException(status_code=413, detail={"message": "Arquivo maior que 40 MB."})
        name = unquote(request.headers.get("x-file-name") or "musica.mp3")
        try:
            info = await asyncio.to_thread(core.save_intro_music, await request.body(), name)
        except ValueError as err:
            raise HTTPException(status_code=400, detail={"message": str(err)}) from None
        return {"ok": True, **info}

    @app.delete("/api/intro/music")
    async def intro_music_delete() -> dict[str, Any]:
        await asyncio.to_thread(core.delete_intro_music)
        return {"ok": True}

    @app.get("/api/map")
    async def city_map(force: bool = False) -> Response:
        """Mapa real da cidade (OpenStreetMap). A 1ª vez baixa da internet; depois vem do arquivo salvo."""
        import json as _json

        # sem mapa (ex.: sem internet) responde {"ok": false, "error": …}: é um estado esperado, não uma falha do núcleo
        data = await core.citymap.get(force=force)
        return Response(_json.dumps(data, separators=(",", ":")), media_type="application/json")

    @app.get("/api/agenda")
    async def agenda_list(days: int = 14) -> dict[str, Any]:
        from .services.agenda import Agenda as _A

        now = core.agenda.now()
        evs = await asyncio.to_thread(core.agenda.occurrences, now.date(), now.date() + timedelta(days=max(1, min(days, 90))))
        return {"events": [_A.public(e) for e in evs], "all": [_A.public(e) for e in await asyncio.to_thread(core.agenda.all)]}

    @app.post("/api/agenda")
    async def agenda_add(body: dict[str, Any]) -> dict[str, Any]:
        from .ai.agenda_tools import AgendaTools
        from .ai.base import ToolCall

        class Run:
            call = ToolCall("painel", "agenda_add", body)

            @staticmethod
            async def notify(ev: dict[str, Any]) -> None:
                for c in list(core.conns):
                    with contextlib.suppress(Exception):
                        await c.send(ev)

        allowed = {k: body[k] for k in ("title", "date", "time", "repeat", "remind_min", "duration_min", "place", "phrase") if k in body}
        out = await AgendaTools(core.agenda)._add(allowed, Run)
        if not out.ok:
            raise HTTPException(status_code=400, detail={"message": out.summary})
        return {"ok": True, "message": out.summary, **out.data}

    @app.delete("/api/agenda/{event_id}")
    async def agenda_delete(event_id: int) -> dict[str, Any]:
        """Apagar pelo painel já é a confirmação (o botão pede "tem certeza?")."""
        ok = await asyncio.to_thread(core.agenda.remove, event_id)
        for c in list(core.conns):
            with contextlib.suppress(Exception):
                await c.send({"type": "agenda", "agenda": core.agenda_state()})
        return {"ok": ok}

    @app.get("/api/briefing")
    async def briefing() -> dict[str, Any]:
        return await core.briefing()

    app.state.conns = 0

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        ok = auth.host_ok(ws.headers.get("host")) and auth.origin_ok(ws.headers.get("origin"), required=True) and auth.token_ok(ws.query_params.get("token"))
        if not ok:
            await ws.close(code=4403)
            return
        await ws.accept()
        conn = Connection(ws)
        core.gate.connection_opened(app.state.conns)
        app.state.conns += 1
        core.conns.add(conn)
        await conn.send({"type": "hello", "version": VERSION, "state": await core.state()})
        feeder = asyncio.create_task(_feed(conn, core))
        try:
            while True:
                msg = await ws.receive_json()
                kind = msg.get("type") if isinstance(msg, dict) else None
                if not core.gate.open and kind not in LOCKED_MESSAGES:
                    await conn.send({"type": "locked", "message": "Confirme seu rosto (ou o PIN) para usar o JARVIS."})
                    continue
                if kind in ("face_verify", "pin_verify", "face_enroll", "face_enable", "face_forget"):
                    gate = core.gate
                    if kind == "face_verify":
                        res = gate.verify(msg.get("descriptors"), msg.get("liveness") if isinstance(msg.get("liveness"), dict) else None)
                    elif kind == "pin_verify":
                        res = await asyncio.to_thread(gate.verify_pin, str(msg.get("pin", "")))
                    elif kind == "face_enroll":
                        res = await asyncio.to_thread(gate.enroll, msg.get("descriptors"), msg.get("pin"))
                    elif kind == "face_enable":
                        res = await asyncio.to_thread(gate.set_enabled, bool(msg.get("on")))
                    else:
                        res = await asyncio.to_thread(gate.forget)
                    await conn.send({"type": "face_result", "mode": kind, **res.to_dict()})
                    await conn.send({"type": "state", "state": await core.state()})
                elif kind == "lock":
                    await conn.cancel_turn()
                    core.gate.lock()
                    await conn.send({"type": "state", "state": await core.state()})
                elif kind == "intro":
                    await conn.cancel_turn()
                    conn.turn = asyncio.create_task(core.intro(conn))
                elif kind == "user_text":
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
                    mode = msg.get("mode") if msg.get("mode") in ("ptt", "wake", "followup", "barge") else "ptt"
                    if mode in ("wake", "barge"):
                        # só interrompe a fala atual se o detector local confirmar "Jarvis"
                        if conn.listen is not None and not conn.listen.done():
                            conn.listen.cancel()
                        conn.listen = asyncio.create_task(core.handle_audio(conn, wav, mode))
                    else:
                        await conn.cancel_turn()
                        conn.turn = asyncio.create_task(core.handle_audio(conn, wav, mode))
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
            app.state.conns = max(0, app.state.conns - 1)
            core.conns.discard(conn)
            core.gate.connection_closed(app.state.conns)

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


LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def check_exposure(settings: Settings) -> str | None:
    """O núcleo só escuta fora do próprio computador com autorização explícita e token forte."""
    if settings.host in LOOPBACK:
        return None
    if not settings.allow_lan:
        return (f"Recusado: JARVIS_HOST={settings.host} exporia o núcleo na rede. Para permitir, defina JARVIS_ALLOW_LAN=true, "
                "um JARVIS_LOCAL_TOKEN com 24+ caracteres e JARVIS_ALLOWED_ORIGINS com o endereço do HUD.")
    if len(os.getenv("JARVIS_LOCAL_TOKEN", "").strip()) < 24:
        return "Recusado: para acesso pela rede, JARVIS_LOCAL_TOKEN precisa ter pelo menos 24 caracteres."
    if not settings.allowed_origins:
        return "Recusado: para acesso pela rede, defina JARVIS_ALLOWED_ORIGINS com o endereço exato do HUD."
    return None


def run() -> None:
    import uvicorn

    settings = load_settings()
    problem = check_exposure(settings)
    if problem:
        print(problem)
        raise SystemExit(2)
    print(f"JARVIS Core {VERSION} em http://{settings.host}:{settings.port}  |  IA: {'Gemini (' + settings.gemini_model + ')' if settings.ai_configured else 'não configurada (modo local)'}")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    run()
