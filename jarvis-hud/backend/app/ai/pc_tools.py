"""Ferramentas do controle amplo do computador (0.5).

Escolha do usuário: "amplo com confirmação". Abrir, pesquisar, buscar, digitar e capturar são livres;
fechar, encerrar, apagar (lixeira), suspender, desligar e reiniciar pedem confirmação com o nome exato
do alvo. Não existe ferramenta de terminal.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable

from ..security.permissions import ActionClass
from ..system.desktop import SETTINGS_PAGES, Desktop
from ..system.screen_input import RISKY_COMBOS, ScreenInput, guard, normalize_combo
from ..system.windows import ActionResult
from .base import ToolOutcome


def _obj(props: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


class PcTools:
    def __init__(self, desktop: Desktop | None, screen: ScreenInput | None, enabled: Callable[[str], bool] = lambda _k: True,
                 shots_dir: Path | None = None, agent: Callable[[], Any] | None = None):
        self.d, self.si, self.enabled = desktop, screen, enabled
        self.shots_dir = shots_dir
        self.agent = agent or (lambda: None)

    @staticmethod
    def _out(call: Any, res: ActionResult) -> ToolOutcome:
        return ToolOutcome(call, res.ok, res.executed, res.message, data=res.data)

    def specs(self) -> list[Any]:
        from .tools import ToolSpec

        if self.d is None or not self.d.available:
            return []
        on = self.enabled
        out: list[ToolSpec] = []
        if on("apps"):
            out.append(ToolSpec("launch_app", "Abrir programa", "Abre QUALQUER programa instalado no Windows pelo nome (Menu Iniciar, inclui os da Microsoft Store). Ex.: 'Word', 'Spotify', 'Calculadora'.",
                                _obj({"name": {"type": "string", "maxLength": 60}}, ["name"]), ActionClass.SAFE, self._launch))
            out.append(ToolSpec("close_app", "Fechar programa", "Pede para fechar as janelas de um programa (como clicar no X; pede confirmação ao usuário).",
                                _obj({"name": {"type": "string", "maxLength": 60}}, ["name"]), ActionClass.CONFIRM, self._close))
            out.append(ToolSpec("kill_process", "Encerrar à força", "Encerra à força um programa travado (perde o que não foi salvo; pede confirmação). Nunca processos do sistema.",
                                _obj({"name": {"type": "string", "maxLength": 60}}, ["name"]), ActionClass.CONFIRM, self._kill))
        if on("web"):
            out.append(ToolSpec("open_website", "Abrir site", "Abre um site (http/https) no navegador padrão.",
                                _obj({"url": {"type": "string", "maxLength": 300}}, ["url"]), ActionClass.SAFE, self._url))
            out.append(ToolSpec("web_search", "Pesquisar na web", "Pesquisa no Google, YouTube, Maps ou Wikipédia, no navegador padrão.",
                                _obj({"query": {"type": "string", "maxLength": 300}, "site": {"type": "string", "enum": ["google", "youtube", "maps", "wikipedia"]}}, ["query"]),
                                ActionClass.SAFE, self._search))
        if on("settings"):
            out.append(ToolSpec("open_settings", "Configurações do Windows", "Abre uma página das Configurações do Windows.",
                                _obj({"page": {"type": "string", "enum": list(SETTINGS_PAGES)}}, ["page"]), ActionClass.SAFE, self._settings))
        if on("files"):
            out.append(ToolSpec("find_files", "Buscar arquivos", "Procura arquivos pelo nome nas pastas pessoais (Área de Trabalho, Documentos, Downloads, Imagens, Músicas, Vídeos, OneDrive). Devolve uma lista numerada.",
                                _obj({"query": {"type": "string", "maxLength": 80}}, ["query"]), ActionClass.READ, self._find))
            out.append(ToolSpec("open_file", "Abrir arquivo", "Abre o arquivo de número N da última busca, no programa padrão (programas e scripts nunca são executados).",
                                _obj({"index": {"type": "integer", "minimum": 1, "maximum": 10}}, ["index"]), ActionClass.SAFE, self._open_file))
            out.append(ToolSpec("show_file", "Mostrar na pasta", "Abre a pasta do arquivo N da última busca, com ele selecionado.",
                                _obj({"index": {"type": "integer", "minimum": 1, "maximum": 10}}, ["index"]), ActionClass.SAFE, self._reveal))
            out.append(ToolSpec("recycle_file", "Mandar para a Lixeira", "Manda o arquivo N da última busca para a Lixeira (dá para restaurar; pede confirmação).",
                                _obj({"index": {"type": "integer", "minimum": 1, "maximum": 10}}, ["index"]), ActionClass.CONFIRM, self._recycle))
        if on("teclado") and self.si is not None:
            out.append(ToolSpec("type_text", "Digitar", "Digita um texto na janela em foco (recusado em terminais e no Executar).",
                                _obj({"text": {"type": "string", "maxLength": 500}}, ["text"]), ActionClass.SAFE, self._type))
            out.append(ToolSpec("press_keys", "Atalho de teclado", "Pressiona um atalho da lista permitida, ex.: 'ctrl+c', 'alt+tab', 'win+d', 'enter'. Atalhos que fecham ou apagam pedem confirmação.",
                                _obj({"keys": {"type": "string", "maxLength": 30}}, ["keys"]), ActionClass.SAFE, self._keys))
        if on("screenshot") and self.si is not None:
            out.append(ToolSpec("take_screenshot", "Captura de tela", "Salva uma captura da tela na pasta Imagens\\JARVIS (fica só no computador).", _obj(), ActionClass.SAFE, self._shot))
        if on("brightness"):
            out.append(ToolSpec("set_brightness", "Brilho da tela", "Brilho da tela do notebook (0 a 100).",
                                _obj({"percent": {"type": "integer", "minimum": 0, "maximum": 100}}, ["percent"]), ActionClass.SAFE, self._brightness))
        if on("computer_use") and self.si is not None:
            out.append(ToolSpec("computer_task", "Usar o computador (vendo a tela)",
                                "Modo computer use: o JARVIS olha a tela e usa mouse/teclado para cumprir uma tarefa que nenhuma outra ferramenta faz "
                                "(ex.: 'no Gmail, abra o último e-mail da faculdade'). Lento e caro: ~1 pedido de IA por passo. Pede autorização.",
                                _obj({"task": {"type": "string", "maxLength": 500}}, ["task"]), ActionClass.CONFIRM, self._computer))
        if on("power"):
            out.append(ToolSpec("lock_windows", "Bloquear o Windows", "Bloqueia a sessão do Windows (volta com a senha/PIN do Windows).", _obj(), ActionClass.SAFE, self._lock))
            out.append(ToolSpec("sleep_pc", "Suspender", "Coloca o computador em suspensão (pede confirmação).", _obj(), ActionClass.CONFIRM, self._sleep))
            out.append(ToolSpec("shutdown_pc", "Desligar/reiniciar", "Desliga ou reinicia o computador depois de uma contagem (30 a 600 s; padrão 60), cancelável. Pede confirmação.",
                                _obj({"restart": {"type": "boolean"}, "delay_s": {"type": "integer", "minimum": 30, "maximum": 600}}), ActionClass.CONFIRM, self._shutdown))
            out.append(ToolSpec("cancel_shutdown", "Cancelar desligamento", "Cancela um desligamento ou reinício agendado.", _obj(), ActionClass.SAFE, self._cancel))
        return out

    # ------------------------------------------------------------------ programas
    async def _launch(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        app, others = await asyncio.to_thread(self.d.find_app, args["name"])
        if app is None:
            return ToolOutcome(run.call, False, False, f"Não encontrei “{args['name']}” entre os programas instalados.")
        res = await asyncio.to_thread(self.d.launch, app)
        out = self._out(run.call, res)
        if others:
            out.data["alternativas"] = [a.name for a in others]
        return out

    async def _close(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        if not await run.confirm(f"Fechar “{args['name']}”? Se houver algo sem salvar, o programa vai perguntar."):
            return ToolOutcome(run.call, False, False, f"O usuário não autorizou fechar “{args['name']}”.")
        return self._out(run.call, await asyncio.to_thread(self.d.close_app, args["name"]))

    async def _kill(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        if not await run.confirm(f"ENCERRAR À FORÇA “{args['name']}”? O que não foi salvo será perdido."):
            return ToolOutcome(run.call, False, False, f"O usuário não autorizou encerrar “{args['name']}”.")
        return self._out(run.call, await asyncio.to_thread(self.d.kill_process, args["name"]))

    # ------------------------------------------------------------------ web e configurações
    async def _url(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        return self._out(run.call, await asyncio.to_thread(self.d.open_url, args["url"]))

    async def _search(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        return self._out(run.call, await asyncio.to_thread(self.d.web_search, args["query"], args.get("site", "google")))

    async def _settings(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        return self._out(run.call, await asyncio.to_thread(self.d.open_settings, args["page"]))

    # ------------------------------------------------------------------ arquivos
    async def _find(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        hits = await asyncio.to_thread(self.d.search_files, args["query"])
        if not hits:
            return ToolOutcome(run.call, True, True, f"Nenhum arquivo com “{args['query']}” nas suas pastas.", data={"files": []})
        rows = [{"n": i + 1, "name": h.name, "folder": h.folder, "modified": time.strftime("%d/%m/%Y", time.localtime(h.modified))} for i, h in enumerate(hits)]
        text = "; ".join(f"{r['n']}) {r['name']}" for r in rows[:5])
        return ToolOutcome(run.call, True, True, f"{len(hits)} arquivo(s): {text}. Diga “abre o 1”, “mostra o 2 na pasta”…", data={"files": rows})

    async def _open_file(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        return self._out(run.call, await asyncio.to_thread(self.d.open_file, args["index"]))

    async def _reveal(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        return self._out(run.call, await asyncio.to_thread(self.d.reveal_file, args["index"]))

    async def _recycle(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        hit = self.d._hit(args["index"])
        if hit is None:
            return ToolOutcome(run.call, False, False, "Esse número não está na última busca de arquivos.")
        if not await run.confirm(f"Mandar “{hit.name}” (em {hit.folder}) para a Lixeira?"):
            return ToolOutcome(run.call, False, False, f"O usuário não autorizou apagar “{hit.name}”.")
        return self._out(run.call, await asyncio.to_thread(self.d.recycle_file, args["index"]))

    # ------------------------------------------------------------------ teclado e tela
    async def _type(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        why = await asyncio.to_thread(guard, self.si, "type")
        if why:
            return ToolOutcome(run.call, False, False, why)
        await asyncio.to_thread(self.si.type_text, args["text"])
        return ToolOutcome(run.call, True, True, f"Digitei {len(args['text'])} caractere(s) na janela em foco.", data={"confirmed": False})

    async def _keys(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        combo = normalize_combo(args["keys"])
        why = await asyncio.to_thread(guard, self.si, "combo", combo)
        if why:
            return ToolOutcome(run.call, False, False, why)
        if combo in RISKY_COMBOS:
            title, _ = await asyncio.to_thread(self.si.foreground)
            if not await run.confirm(f"Pressionar {combo.upper()} em “{title}”? Isso fecha ou apaga algo."):
                return ToolOutcome(run.call, False, False, f"O usuário não autorizou {combo}.")
        await asyncio.to_thread(self.si.combo, combo)
        return ToolOutcome(run.call, True, True, f"Atalho {combo} enviado.", data={"confirmed": False})

    async def _shot(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        shot = await asyncio.to_thread(self.si.capture, 4096)
        folder = self.shots_dir or (self.d.home / "Pictures" / "JARVIS")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"captura-{time.strftime('%Y%m%d-%H%M%S')}.png"
        await asyncio.to_thread(path.write_bytes, shot.png)
        return ToolOutcome(run.call, True, True, f"Captura salva em {path}.", data={"path": str(path)})

    async def _brightness(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        return self._out(run.call, await asyncio.to_thread(self.d.set_brightness, args["percent"]))

    # ------------------------------------------------------------------ computer use
    async def _computer(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        agent = self.agent()
        if agent is None:
            return ToolOutcome(run.call, False, False, "Modo computer use indisponível: precisa do Gemini configurado e do Windows.")
        task = args["task"].strip()
        if not await run.confirm(f"Usar o computador por você para: “{task}”? A cada passo uma captura da tela vai ao Gemini (Google) — cerca de 1 pedido de IA por passo, até 25. "
                                 "O HUD sai da frente; mexa o mouse para me parar."):
            return ToolOutcome(run.call, False, False, "O usuário não autorizou o modo computer use.")
        res = await agent.run(task, run.confirm, run.notify)
        return ToolOutcome(run.call, res["ok"], res["steps"] > 0, f"{res['message']} ({res['steps']} passo(s) de IA).",
                           data={"reason": res["reason"], "steps": res["steps"], "history": res["history"][-12:], "verified": res["ok"]})

    # ------------------------------------------------------------------ energia
    async def _lock(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        return self._out(run.call, await asyncio.to_thread(self.d.lock_windows))

    async def _sleep(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        if not await run.confirm("Suspender o computador agora?"):
            return ToolOutcome(run.call, False, False, "O usuário não autorizou suspender.")
        return self._out(run.call, await asyncio.to_thread(self.d.sleep))

    async def _shutdown(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        restart = bool(args.get("restart", False))
        delay = int(args.get("delay_s", 60))
        if not await run.confirm(f"{'REINICIAR' if restart else 'DESLIGAR'} o computador em {delay} s? Salve o que estiver aberto."):
            return ToolOutcome(run.call, False, False, "O usuário não autorizou.")
        return self._out(run.call, await asyncio.to_thread(self.d.shutdown, restart, delay))

    async def _cancel(self, args: dict[str, Any], run: Any) -> ToolOutcome:
        return self._out(run.call, await asyncio.to_thread(self.d.cancel_shutdown))
