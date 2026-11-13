"""JARVIS no celular (0.7) — página própria para o celular na rede de casa (ou pelo Tailscale).

Segurança:
- É um servidor SEPARADO (porta 8766), que só sobe quando o usuário liga em Configurações → Sistema. O HUD e a
  API completa continuam só em 127.0.0.1.
- Cada celular é pareado uma vez com um código de 6 dígitos (5 min, 5 tentativas) mostrado no HUD, com QR.
  Recebe um token só dele; o núcleo guarda apenas o hash (data/aparelhos.json). Dá para remover no HUD.
- A API do celular é restrita: cenas, luzes, porta (trancar e ver — destrancar não existe), agenda, lista,
  anotações, Pomodoro e conversa por texto. Mexer na tela/teclado, ver a tela, apagar arquivos e encerrar
  processos são bloqueados (REMOTE_DENY). Ações que pedem confirmação no HUD pedem no celular também.
- HTTP simples na rede de casa (como roteadores e impressoras). Fora de casa, use o Tailscale (criptografado);
  nunca abra portas no roteador.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import re
import secrets
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

STATIC = Path(__file__).resolve().parent / "static" / "mobile"
CODE_TTL_S = 300
MAX_TRIES = 5
MAX_DEVICES = 8


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class DeviceStore:
    """Celulares pareados (só o hash do token fica no disco) e o código de pareamento da vez."""

    def __init__(self, path: Path | None, clock: Callable[[], float] = time.time):
        self.path, self.clock = path, clock
        self.devices: list[dict[str, Any]] = []
        self.code: dict[str, Any] | None = None
        if path and path.exists():
            with contextlib.suppress(Exception):
                self.devices = [d for d in json.loads(path.read_text(encoding="utf-8")).get("devices", []) if isinstance(d, dict) and d.get("hash")]

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"devices": self.devices}, ensure_ascii=False, indent=1), encoding="utf-8")

    def new_code(self) -> dict[str, Any]:
        self.code = {"code": f"{secrets.randbelow(1_000_000):06d}", "until": self.clock() + CODE_TTL_S, "tries": 0}
        return {"code": self.code["code"], "expires_in": CODE_TTL_S}

    def pair(self, code: str, name: str) -> tuple[str | None, str]:
        c = self.code
        if not c or self.clock() > c["until"]:
            self.code = None
            return None, "Código vencido: gere outro no HUD (Configurações → Sistema → Celular)."
        c["tries"] += 1
        if not hmac.compare_digest(str(code or "").strip(), c["code"]):
            if c["tries"] >= MAX_TRIES:
                self.code = None
                return None, "Código errado demais: gere outro no HUD."
            return None, "Código errado."
        self.code = None
        if len(self.devices) >= MAX_DEVICES:
            return None, f"Já há {MAX_DEVICES} aparelhos pareados: remova um no HUD."
        token = secrets.token_urlsafe(32)
        name = re.sub(r"[^\w .\-áéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ]", "", (name or "").strip())[:40] or "Celular"
        self.devices.append({"id": uuid.uuid4().hex[:8], "name": name, "hash": _hash(token), "created": int(self.clock()), "last_seen": int(self.clock())})
        self._save()
        return token, f"{name} pareado."

    def check(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        h = _hash(token)
        for d in self.devices:
            if hmac.compare_digest(d["hash"], h):
                if self.clock() - d.get("last_seen", 0) > 60:
                    d["last_seen"] = int(self.clock())
                    with contextlib.suppress(OSError):
                        self._save()
                return d
        return None

    def remove(self, device_id: str) -> bool:
        before = len(self.devices)
        self.devices = [d for d in self.devices if d["id"] != device_id]
        if len(self.devices) != before:
            self._save()
            return True
        return False

    def public(self) -> list[dict[str, Any]]:
        return [{k: d[k] for k in ("id", "name", "created", "last_seen")} for d in self.devices]


def lan_addresses() -> list[str]:
    """Endereços deste PC na rede de casa e no Tailscale (100.64.0.0/10). Não envia nada pela rede."""
    out: list[str] = []
    with contextlib.suppress(OSError):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))      # UDP sem envio: só descobre a interface de saída
            out.append(s.getsockname()[0])
        finally:
            s.close()
    with contextlib.suppress(OSError):
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out and not ip.startswith("127."):
                out.append(ip)
    def rank(ip: str) -> int:
        a, b = (int(x) for x in ip.split(".")[:2])
        return 0 if (a == 192 and b == 168) or a == 10 or (a == 172 and 16 <= b <= 31) else 1 if a == 100 and 64 <= b <= 127 else 2
    return sorted(out, key=rank)


def qr_svg(text: str) -> str:
    import segno

    return segno.make(text, error="m").svg_inline(scale=6, dark="#04122e", light="#ffffff", border=2)


def create_mobile_app(core: Any, store: DeviceStore) -> FastAPI:
    app = FastAPI(title="JARVIS no celular", docs_url=None, redoc_url=None, openapi_url=None)
    pending: dict[str, dict[str, Any]] = {}      # confirmações pedidas ao celular (id → pedido)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; media-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
        return resp

    def device(request: Request) -> dict[str, Any]:
        auth = request.headers.get("authorization", "")
        d = store.check(auth[7:].strip() if auth.lower().startswith("bearer ") else None)
        if d is None:
            raise HTTPException(status_code=401, detail={"message": "Celular não pareado (ou removido no HUD)."})
        return d

    @app.get("/")
    async def page() -> Response:
        return FileResponse(STATIC / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/{name}")
    async def asset(name: str) -> Response:
        files = {"app.js": "text/javascript; charset=utf-8", "manifest.webmanifest": "application/manifest+json", "icon.png": "image/png"}
        if name not in files:
            raise HTTPException(status_code=404)
        return FileResponse(STATIC / name, media_type=files[name])

    @app.post("/m/pair")
    async def pair(body: dict[str, Any]) -> JSONResponse:
        token, msg = store.pair(str(body.get("code", ""))[:12], str(body.get("name", ""))[:60])
        await asyncio.sleep(0.4)                 # freia tentativas em sequência
        if token is None:
            return JSONResponse({"ok": False, "message": msg}, status_code=403)
        await core.broadcast({"type": "notice", "message": f"Celular pareado: {msg}"})
        await core.broadcast({"type": "mobile", "devices": store.public()})
        return JSONResponse({"ok": True, "token": token, "message": msg})

    @app.get("/m/state")
    async def state(d: dict[str, Any] = Depends(device)) -> dict[str, Any]:
        full = await core.state()
        lock = next((x for x in full["devices"] if x["id"] == "fechadura"), None)
        return {
            "device": d["name"], "version": full["version"], "title": full["runtime"]["user_title"], "city": full["location"]["city"],
            "scenes": [{k: s[k] for k in ("id", "name", "icon", "confirm", "schedule")} for s in full.get("scenes", [])],
            "quick": full.get("quick"), "door": lock,
            "agenda": core.agenda_state(), "lists": core.lists.public(), "pomodoro": full.get("pomodoro"), "game": full.get("game"),
            "weather": await core.weather.get(), "hud_open": len(core.conns) > 0, "voice": full["voice"]["tts_active"],
        }

    async def run(text: str, plan: Any, approve: str | None) -> dict[str, Any]:
        async def confirm(question: str) -> bool:
            return approve is not None and question == approve

        out = await core.run_remote(text, "celular", confirm, plan=plan)
        if out["asked"] and not any(t["executed"] for t in out["tools"]) and approve is None:
            cid = uuid.uuid4().hex[:10]
            pending[cid] = {"text": text, "quick": getattr(plan, "_quick", None), "question": out["asked"][0], "until": time.time() + 120}
            for k in [k for k, v in pending.items() if v["until"] < time.time()]:
                pending.pop(k, None)
            return {"needs_confirm": out["asked"][0], "confirm_id": cid, "reply": "", "tools": []}
        return {"reply": out["reply"], "tools": out["tools"]}

    async def voice(reply: str, where: str) -> dict[str, Any]:
        if not reply or where == "none":
            return {}
        if where == "pc":
            return {"spoken_on": "pc" if await core.say_on_hud(reply, "celular") else "nenhum HUD aberto"}
        engine = core.tts.resolve(core.runtime()["tts_engine"])
        if engine is None:
            return {"spoken_on": "sem voz configurada"}
        with contextlib.suppress(Exception):
            rt = core.runtime()
            s = await core.voice_sample(engine.id, core._voice_for(engine, rt), reply[:300])
            return {"spoken_on": "celular", "wav": s["wav"]}
        return {"spoken_on": "falhou"}

    @app.post("/m/say")
    async def say(body: dict[str, Any], d: dict[str, Any] = Depends(device)) -> dict[str, Any]:
        text = str(body.get("text", "")).strip()[:500]
        cid = body.get("confirm_id")
        if cid:
            p = pending.pop(str(cid), None)
            if not p or p["until"] < time.time():
                raise HTTPException(status_code=410, detail={"message": "Confirmação vencida: peça de novo."})
            text, approve = p["text"], (p["question"] if body.get("approve") else None)
            if approve is None:
                return {"reply": "Cancelado.", "tools": []}
            plan = core.quick_plan(p["quick"])[1] if p.get("quick") and core.quick_plan(p["quick"]) else None
        else:
            if not text:
                raise HTTPException(status_code=400, detail={"message": "Diga ou digite um comando."})
            approve, plan = None, None
        out = await run(text, plan, approve)
        return {**out, **(await voice(out.get("reply", ""), str(body.get("voice", "none"))))}

    @app.post("/m/quick")
    async def quick(body: dict[str, Any], d: dict[str, Any] = Depends(device)) -> dict[str, Any]:
        action = str(body.get("action", ""))[:60]
        found = core.quick_plan(action)
        if found is None:
            raise HTTPException(status_code=400, detail={"message": "Esse botão não existe neste computador."})
        label, plan = found
        plan._quick = action  # type: ignore[attr-defined]
        out = await run(label, plan, None)
        return {**out, **(await voice(out.get("reply", ""), str(body.get("voice", "none"))))}

    @app.post("/m/list")
    async def shopping(body: dict[str, Any], d: dict[str, Any] = Depends(device)) -> dict[str, Any]:
        op, items = body.get("op"), str(body.get("items", ""))[:300]
        from .services.lists import split_items

        if op == "add":
            core.lists.add_items(split_items(items))
        elif op == "remove":
            core.lists.remove_items(split_items(items))
        elif op == "note":
            with contextlib.suppress(ValueError):
                core.lists.add_note(items)
        else:
            raise HTTPException(status_code=400, detail={"message": "Operação desconhecida."})
        await core.broadcast({"type": "lists", "lists": core.lists.public()})
        return core.lists.public()

    return app


class _QuietServer:
    """uvicorn rodando no MESMO laço do núcleo, sem mexer nos sinais (Ctrl+C) do servidor principal."""

    def __init__(self, app: FastAPI, host: str, port: int):
        import uvicorn

        class Server(uvicorn.Server):
            @contextlib.contextmanager
            def capture_signals(self):  # noqa: D401 — o servidor principal cuida dos sinais
                yield

        self.server = Server(uvicorn.Config(app, host=host, port=port, log_level="warning", log_config=None, lifespan="off"))
        self.task: asyncio.Task | None = None

    async def start(self) -> None:
        self.task = asyncio.create_task(self.server.serve())
        for _ in range(100):
            if self.server.started or self.task.done():
                break
            await asyncio.sleep(0.05)
        if self.task.done() and not self.server.started:
            exc = self.task.exception()
            raise OSError(str(exc) if exc else "não subiu")

    async def stop(self) -> None:
        self.server.should_exit = True
        if self.task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(self.task, 5)


class MobileGateway:
    """Liga/desliga o servidor do celular conforme Configurações → Sistema → Celular."""

    def __init__(self, core: Any, store: DeviceStore, host: str = "0.0.0.0", port: int = 8766):
        self.core, self.store, self.host, self.port = core, store, host, port
        self.server: _QuietServer | None = None
        self.error = ""

    @property
    def running(self) -> bool:
        return self.server is not None

    async def apply(self) -> None:
        want = bool(self.core.runtime().get("mobile_enabled"))
        if want and self.server is None:
            srv = _QuietServer(create_mobile_app(self.core, self.store), self.host, self.port)
            try:
                await srv.start()
                self.server, self.error = srv, ""
            except OSError as err:
                self.error = f"Não consegui abrir a porta {self.port}: {err}"
        elif not want and self.server is not None:
            await self.server.stop()
            self.server = None

    def status(self) -> dict[str, Any]:
        urls = [f"http://{ip}:{self.port}/" for ip in lan_addresses()] if self.running else []
        return {"enabled": bool(self.core.runtime().get("mobile_enabled")), "running": self.running, "port": self.port, "urls": urls,
                "error": self.error, "devices": self.store.public()}
