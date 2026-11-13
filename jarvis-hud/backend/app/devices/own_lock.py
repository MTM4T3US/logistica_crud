"""Fechadura do próprio usuário (feita por ele) — lado do JARVIS. Escolha do usuário: SÓ TRANCAR E VER.

O firmware da fechadura expõe na rede de casa apenas:
    GET  /status   → {"locked": bool, "door_open": bool|null, "battery": int|null, "event": str|null}
    POST /lock     → tranca (só se a porta estiver fechada) e devolve o mesmo formato
Não existe /unlock na rede: destrancar continua no próprio aparelho (teclado, digital, RFID, chave).

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
    actions = ("status", "lock")          # "unlock" não existe aqui — de propósito

    def __init__(self, url: str, secret: bytes, client: httpx.AsyncClient | None = None, clock: Callable[[], float] = time.time):
        self.url, self.secret = url.rstrip("/"), secret
        self._client, self._clock = client, clock
        self._s: dict[str, Any] = {"locked": None, "door_open": None, "battery": None, "reachable": None}

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
        try:
            data = await self._request("GET" if action == "status" else "POST", "/status" if action == "status" else "/lock")
        except PermissionError:
            self._s["reachable"] = False
            return DeviceResult(False, False, "A resposta da fechadura não veio assinada: ignorei (pode ser outro aparelho fingindo ser ela).",
                                simulated=False, state=self.status())
        except Exception as exc:
            self._s["reachable"] = False
            return DeviceResult(False, False, f"A fechadura não respondeu ({type(exc).__name__}). Está ligada e no Wi-Fi?", simulated=False, state=self.status())
        self._s.update(locked=bool(data.get("locked")), door_open=data.get("door_open"), battery=data.get("battery"), reachable=True)
        door = " A porta está ABERTA." if data.get("door_open") else ""
        if action == "lock":
            if data.get("locked"):
                return DeviceResult(True, True, "Porta trancada (confirmado pelo sensor da fechadura)." + door, simulated=False, state={**self.status(), "confirmed": True})
            why = data.get("event") or ("a porta está aberta" if data.get("door_open") else "motivo não informado")
            return DeviceResult(False, False, f"A fechadura não trancou: {why}.", simulated=False, state=self.status())
        state = "trancada" if data.get("locked") else "DESTRANCADA"
        bat = f" Bateria {data['battery']}%." if isinstance(data.get("battery"), int) else ""
        return DeviceResult(True, True, f"Fechadura {state}.{door}{bat}", simulated=False, state=self.status())
