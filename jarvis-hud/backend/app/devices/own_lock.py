"""Fechadura do próprio usuário (feita por ele) — lado do JARVIS. Escolha do usuário: SÓ TRANCAR E VER.

O firmware da fechadura (módulo firmware/fechadura_jarvis/JarvisLock.h, ESP32 + solenoide 12 V) expõe:
    GET  /status   → {"locked", "energized", "door_open" (null sem sensor), "lockdown", "wrong_codes", "events": [...]}
    POST /lock     → corta o solenoide se estiver abrindo ("garante travada")
    POST /lockdown → MODO TRANCADO: app/rosto/painel não abrem mais; o teclado continua abrindo.
                     Desligar o modo trancado só no teclado (código mestre), nunca pela rede.
Não existe /unlock na rede: destrancar continua no próprio aparelho (teclado, app do TCC, rosto).

Cada pedido e cada resposta é assinado (HMAC-SHA256) com um segredo gerado no pareamento:
    assinatura do pedido   = HMAC(segredo, "MÉTODO\\ncaminho\\ntimestamp\\nnonce\\ncorpo")
    assinatura da resposta = HMAC(segredo, "RESP\\nnonce\\ncorpo")
Assim ninguém na rede consegue mandar trancar no lugar do JARVIS nem fingir um "trancada".
Protocolo completo e regras do firmware: docs/FECHADURA.md.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from .registry import Device, DeviceResult


def sign(secret: bytes, text: str) -> str:
    return hmac.new(secret, text.encode("utf-8"), hashlib.sha256).hexdigest()


def load_config(path: Path) -> dict[str, Any] | None:
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        if str(cfg.get("url", "")).startswith(("http://", "https://")) and len(bytes.fromhex(cfg.get("secret", ""))) >= 16:
            return cfg
    except (OSError, ValueError):
        pass
    return None


def new_config(url: str) -> dict[str, Any]:
    return {"url": url.rstrip("/"), "secret": secrets.token_hex(32), "created": time.time()}


class OwnLock(Device):
    id, name, kind, transport = "fechadura", "Fechadura", "lock", "Wi-Fi local (assinado)"
    simulated = False
    actions = ("status", "lock", "lockdown")   # "unlock" não existe aqui — de propósito

    def __init__(self, url: str, secret: bytes, client: httpx.AsyncClient | None = None, clock: Callable[[], float] = time.time):
        self.url, self.secret = url.rstrip("/"), secret
        self._client, self._clock = client, clock
        self._s: dict[str, Any] = {"locked": None, "door_open": None, "battery": None, "reachable": None, "lockdown": None, "wrong_codes": 0}
        self.events: list[dict[str, Any]] = []

    def status(self) -> dict[str, Any]:
        return dict(self._s)

    def describe(self) -> dict[str, Any]:
        d = super().describe()
        d["connected"] = bool(self._s.get("reachable"))
        return d

    async def _request(self, method: str, path: str) -> dict[str, Any]:
        ts, nonce, body = str(int(self._clock())), secrets.token_hex(12), ""
        headers = {"X-Jarvis-Time": ts, "X-Jarvis-Nonce": nonce, "X-Jarvis-Sig": sign(self.secret, f"{method}\n{path}\n{ts}\n{nonce}\n{body}")}
        client = self._client or httpx.AsyncClient(timeout=5.0)
        try:
            resp = await client.request(method, self.url + path, headers=headers, content=body)
        finally:
            if self._client is None:
                await client.aclose()
        text = resp.text
        if not hmac.compare_digest(resp.headers.get("X-Lock-Sig", ""), sign(self.secret, f"RESP\n{nonce}\n{text}")):
            raise PermissionError("resposta sem assinatura válida")
        if resp.status_code >= 400:
            raise RuntimeError(json.loads(text).get("error", f"HTTP {resp.status_code}") if text.startswith("{") else f"HTTP {resp.status_code}")
        return json.loads(text)

    async def command(self, action: str, params: dict[str, Any]) -> DeviceResult:  # type: ignore[override]
        if action == "unlock":
            return DeviceResult(False, False, "Destrancar pelo JARVIS não existe: use o teclado, a digital ou a chave da própria fechadura.",
                                simulated=False, state=self.status())
        path = {"status": "/status", "lock": "/lock", "lockdown": "/lockdown"}.get(action)
        if path is None:
            return DeviceResult(False, False, f"Ação '{action}' não existe para a fechadura.", simulated=False, state=self.status())
        try:
            data = await self._request("GET" if action == "status" else "POST", path)
        except PermissionError:
            self._s["reachable"] = False
            return DeviceResult(False, False, "A resposta da fechadura não veio assinada: ignorei (pode ser outro aparelho fingindo ser ela).",
                                simulated=False, state=self.status())
        except Exception as exc:
            self._s["reachable"] = False
            return DeviceResult(False, False, f"A fechadura não respondeu ({type(exc).__name__}). Está ligada e no Wi-Fi?", simulated=False, state=self.status())
        self._s.update(locked=bool(data.get("locked")), door_open=data.get("door_open"), battery=data.get("battery"), reachable=True,
                       lockdown=bool(data.get("lockdown")), wrong_codes=int(data.get("wrong_codes") or 0), energized=bool(data.get("energized")))
        self.events = list(data.get("events") or [])
        bolt = "travada" if data.get("locked") else "ABRINDO (solenoide energizado)"
        door = ("A porta está ABERTA." if data.get("door_open") else "Porta fechada.") if data.get("door_open") is not None else \
            "Sem sensor de porta: não sei se ela está fechada."
        mode = " Modo trancado ligado: app e rosto não abrem; só o teclado." if data.get("lockdown") else ""
        if action == "lock":
            if data.get("locked"):
                return DeviceResult(True, True, f"Fechadura travada (o próprio circuito confirmou o solenoide desligado). {door}{mode}",
                                    simulated=False, state={**self.status(), "confirmed": True})
            return DeviceResult(False, False, f"A fechadura não travou ({data.get('event') or 'motivo não informado'}).", simulated=False, state=self.status())
        if action == "lockdown":
            if data.get("lockdown"):
                return DeviceResult(True, True, "Modo trancado ligado: o app, o reconhecimento facial e o painel não abrem mais a porta; o teclado "
                                    "continua abrindo. Para desligar o modo, use o código mestre no teclado.", simulated=False,
                                    state={**self.status(), "confirmed": True})
            return DeviceResult(False, False, "A fechadura não confirmou o modo trancado.", simulated=False, state=self.status())
        bad = f" {data['wrong_codes']} código(s) errado(s) no teclado." if data.get("wrong_codes") else ""
        return DeviceResult(True, True, f"Fechadura {bolt}. {door}{mode}{bad}", simulated=False, state=self.status())
