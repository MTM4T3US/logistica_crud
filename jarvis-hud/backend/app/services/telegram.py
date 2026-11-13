"""Bot do Telegram (0.7): falar com o JARVIS de qualquer lugar e receber os avisos.

- Só conversa com UM chat: o seu, pareado com um código de 6 dígitos mostrado no HUD (Configurações → Sistema →
  Telegram). Mensagens de qualquer outra pessoa ou grupo são ignoradas, sem resposta.
- O PC só faz pedidos para fora (api.telegram.org): nenhuma porta é aberta no roteador.
- Os pedidos passam pelo mesmo caminho do HUD; ações que pedem confirmação chegam com botões Sim/Não.
  Mexer na tela/teclado, ver a tela, apagar arquivos e encerrar processos ficam bloqueados (REMOTE_DENY).
  Destrancar a porta não existe.
- Avisos que chegam aqui: lembretes da agenda, fechadura (aberturas, códigos errados), cenas agendadas,
  fim do Pomodoro e o resumo da semana.
- O token do bot fica só em backend/.env (TELEGRAM_BOT_TOKEN) e nunca aparece no HUD nem nos registros.
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("jarvis.telegram")
API = "https://api.telegram.org"
HELP = ("Sou o JARVIS do seu PC. Escreva como falaria com ele: “modo cinema”, “a porta está trancada?”, "
        "“põe leite na lista”, “o que eu tenho amanhã?”, “quanto está o dólar?”.\n"
        "Atalhos: /cenas · /lista · /porta · /semana · /desparear\n"
        "Por segurança, daqui não dá para mexer na tela, digitar, ver a tela nem destrancar a porta.")


class TelegramBot:
    def __init__(self, token: str, core: Any, state_path: Path | None, client: httpx.AsyncClient | None = None,
                 clock: Any = time.time, poll_timeout: int = 25):
        self.token, self.core, self.path, self.clock, self.poll_timeout = token.strip(), core, state_path, clock, poll_timeout
        self.client = client or httpx.AsyncClient(timeout=poll_timeout + 10)
        self.chat_id: int | None = None
        self.offset = 0
        self.code: dict[str, Any] | None = None
        self.pending: dict[str, asyncio.Future] = {}
        self.task: asyncio.Task | None = None
        self.username = ""
        self.error = ""
        if state_path and state_path.exists():
            with contextlib.suppress(Exception):
                self.chat_id = int(json.loads(state_path.read_text(encoding="utf-8"))["chat_id"])

    # ------------------------------------------------------------------ API
    async def call(self, method: str, **params: Any) -> Any:
        resp = await self.client.post(f"{API}/bot{self.token}/{method}", json=params)
        data = resp.json() if resp.content else {}
        if resp.status_code == 401:
            raise PermissionError("token do bot recusado pelo Telegram")
        if not data.get("ok"):
            raise RuntimeError(str(data.get("description") or f"HTTP {resp.status_code}"))
        return data["result"]

    async def send(self, text: str, buttons: list[list[dict[str, str]]] | None = None) -> Any:
        if self.chat_id is None:
            return None
        params: dict[str, Any] = {"chat_id": self.chat_id, "text": text[:4000], "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        return await self.call("sendMessage", **params)

    async def notify(self, text: str) -> None:
        """Usado pelo núcleo para os avisos (core.remote)."""
        with contextlib.suppress(Exception):
            await self.send(text)

    # ------------------------------------------------------------------ pareamento
    def new_code(self) -> dict[str, Any]:
        self.code = {"code": f"{secrets.randbelow(1_000_000):06d}", "until": self.clock() + 600, "tries": 0}
        return {"code": self.code["code"], "expires_in": 600, "bot": self.username}

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"chat_id": self.chat_id}), encoding="utf-8")

    def unpair(self) -> None:
        self.chat_id = None
        if self.path and self.path.exists():
            self.path.unlink()

    def status(self) -> dict[str, Any]:
        return {"configured": True, "running": self.task is not None and not self.task.done(), "bot": self.username,
                "paired": self.chat_id is not None, "error": self.error}

    # ------------------------------------------------------------------ laço
    async def start(self) -> None:
        try:
            me = await self.call("getMe")
            self.username, self.error = me.get("username", ""), ""
        except Exception as err:
            self.error = f"Não consegui falar com o Telegram: {err}"
            log.warning("telegram: %s", self.error)
        self.task = asyncio.create_task(self.loop())

    async def stop(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
        await self.client.aclose()

    async def poll_once(self) -> int:
        updates = await self.call("getUpdates", offset=self.offset, timeout=self.poll_timeout, allowed_updates=["message", "callback_query"])
        for u in updates:
            self.offset = max(self.offset, int(u["update_id"]) + 1)
            if "callback_query" in u:
                await self.on_button(u["callback_query"])
            elif "message" in u:
                asyncio.create_task(self.on_message(u["message"]))     # uma confirmação pendente não trava as próximas
        return len(updates)

    async def loop(self) -> None:
        wait = 5.0
        while True:
            try:
                await self.poll_once()
                wait, self.error = 5.0, ""
            except asyncio.CancelledError:
                raise
            except PermissionError as err:
                self.error = f"O Telegram recusou o token ({err}). Confira TELEGRAM_BOT_TOKEN no backend\\.env."
                log.error("telegram: %s", self.error)
                return
            except Exception as err:   # sem internet, Telegram fora do ar: tenta de novo, cada vez mais devagar
                self.error = f"Sem conexão com o Telegram ({type(err).__name__}); tentando de novo."
                await asyncio.sleep(wait)
                wait = min(wait * 2, 120.0)

    # ------------------------------------------------------------------ mensagens
    async def on_message(self, msg: dict[str, Any]) -> None:
        chat = msg.get("chat") or {}
        if chat.get("type") != "private":
            return
        cid, text = int(chat.get("id", 0)), (msg.get("text") or "").strip()
        if self.chat_id is None:
            await self._try_pair(cid, text)
            return
        if cid != self.chat_id:
            return                                             # outra pessoa: silêncio
        if not text:
            await self.send("Por enquanto só entendo texto (mensagens de voz ainda não).")
            return
        cmd = text.split()[0].lower().split("@")[0]
        if cmd in ("/start", "/ajuda", "/help"):
            await self.send(HELP)
        elif cmd == "/cenas":
            scenes = self.core.scenes_state()
            rows = [[{"text": s["name"], "callback_data": f"cena:{s['id']}"} for s in scenes[i:i + 2]] for i in range(0, len(scenes), 2)]
            await self.send("Qual cena?", rows or None)
        elif cmd == "/lista":
            await self._run("o que tem na lista")
        elif cmd == "/porta":
            await self._run("a porta está trancada?")
        elif cmd == "/semana":
            await self.send(await self.core.week_summary())
        elif cmd == "/desparear":
            await self.send("Pareamento desfeito. Para voltar, gere um código novo no HUD.")
            self.unpair()
        else:
            await self._run(text[:500])

    async def _try_pair(self, cid: int, text: str) -> None:
        m = re.match(r"^/(?:parear|start)\s+(\d{6})$", text)
        c = self.code
        if not m:
            await self.call("sendMessage", chat_id=cid, text="Este JARVIS ainda não está pareado. No PC: Configurações → Sistema → Telegram → "
                                                              "“Gerar código”, e mande aqui: /parear CÓDIGO")
            return
        if not c or self.clock() > c["until"]:
            await self.call("sendMessage", chat_id=cid, text="Código vencido. Gere outro no HUD.")
            return
        c["tries"] += 1
        if not hmac.compare_digest(m.group(1), c["code"]):
            if c["tries"] >= 5:
                self.code = None
            await self.call("sendMessage", chat_id=cid, text="Código errado.")
            return
        self.code, self.chat_id = None, cid
        self._save()
        await self.send("Pareado. A partir de agora só este chat fala com o JARVIS.\n\n" + HELP)
        await self.core.broadcast({"type": "notice", "message": "Telegram pareado."})

    async def _run(self, text: str, plan: Any = None) -> None:
        out = await self.core.run_remote(text, "telegram", self.confirm, plan=plan)
        done = [f"{'✓' if t['executed'] else '✕'} {t['label']}" for t in out["tools"]]
        reply = out["reply"] or "Sem resposta."
        await self.send(reply + ("\n\n" + " · ".join(done) if done and len(done) > 1 else ""))

    # ------------------------------------------------------------------ botões
    async def confirm(self, question: str) -> bool:
        bid = uuid.uuid4().hex[:8]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending[bid] = fut
        await self.send(question, [[{"text": "Sim", "callback_data": f"ok:{bid}"}, {"text": "Não", "callback_data": f"no:{bid}"}]])
        try:
            return bool(await asyncio.wait_for(fut, 120))
        except asyncio.TimeoutError:
            await self.send("Sem resposta em 2 minutos: não fiz.")
            return False
        finally:
            self.pending.pop(bid, None)

    async def on_button(self, cq: dict[str, Any]) -> None:
        cid = int(((cq.get("message") or {}).get("chat") or {}).get("id", 0))
        with contextlib.suppress(Exception):
            await self.call("answerCallbackQuery", callback_query_id=cq.get("id"))
        if self.chat_id is None or cid != self.chat_id:
            return
        kind, _, arg = str(cq.get("data", "")).partition(":")
        if kind in ("ok", "no"):
            fut = self.pending.get(arg)
            if fut and not fut.done():
                fut.set_result(kind == "ok")
        elif kind == "cena":
            found = self.core.quick_plan(f"cena:{arg}")
            if found:
                asyncio.create_task(self._run(found[0], found[1]))
