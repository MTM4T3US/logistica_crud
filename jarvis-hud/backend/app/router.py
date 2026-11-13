"""Roteador local: entende os comandos do dia a dia sem gastar a cota do Gemini.

Só reconhece frases que ele entende com segurança; o resto (conversa, perguntas, pedidos
complexos) segue para o Gemini. Sem internet ou sem cota, é ele que mantém o JARVIS útil.

Nada aqui executa texto livre: cada intenção vira uma chamada de ferramenta com argumentos
do cadastro (permissions.json), que passa pela mesma validação de qualquer pedido da IA.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .ai.base import ToolCall, ToolOutcome
from .security.permissions import Permissions

COLORS = {
    "azul claro": "#00c8ff", "azul escuro": "#0010a0", "azul jarvis": "#2b9bff", "azul": "#0050ff", "ciano": "#00e0ff", "turquesa": "#00ffc8",
    "verde": "#00ff30", "vermelho": "#ff0000", "amarelo": "#ffc800", "laranja": "#ff6400", "roxo": "#8000ff", "violeta": "#8000ff",
    "lilas": "#b070ff", "rosa": "#ff3c96", "magenta": "#ff00ff", "dourado": "#ffaa20", "branco quente": "#ffb070", "branco": "#ffffff",
}
APP_WORDS = {
    "vscode": ["vs code", "vscode", "visual studio code", "codigo", "editor"], "navegador": ["navegador", "browser", "edge", "chrome", "internet"],
    "terminal": ["terminal", "powershell", "prompt"], "explorador": ["explorador", "explorer", "arquivos"], "bloco_de_notas": ["bloco de notas", "notepad"],
    "calculadora": ["calculadora"], "spotify": ["spotify"], "discord": ["discord"],
}
NUM_WORDS = {"zero": 0, "dez": 10, "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "metade": 50, "sessenta": 60, "setenta": 70,
             "oitenta": 80, "noventa": 90, "cem": 100, "maximo": 100, "minimo": 5}


def fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[!?.;]+", " ", text)).strip()


def _n(v: Any) -> str:
    return str(round(float(v))) if v is not None else "?"


@dataclass
class Plan:
    """O que fazer localmente: chamadas de ferramenta e como responder com os resultados."""
    kind: str
    calls: list[ToolCall] = field(default_factory=list)
    render: Callable[[list[ToolOutcome], str], str] = lambda outs, title: ""
    #: intenções de conversa (saudação) só são tratadas localmente quando a IA não está disponível
    chat: bool = False


def _call(name: str, **args: Any) -> ToolCall:
    return ToolCall(id="local-" + uuid.uuid4().hex[:8], name=name, args=args)


def _report(ok_text: str) -> Callable[[list[ToolOutcome], str], str]:
    """Resposta padrão de ação: diz o que de fato aconteceu, inclusive falhas."""
    def render(outs: list[ToolOutcome], title: str) -> str:
        failed = [o for o in outs if not o.executed]
        # nunca deixar parecer real o que aconteceu só no simulador
        sim = " Isso foi só no simulador; nenhum aparelho real foi acionado." if any(o.simulated and o.executed for o in outs) else ""
        # ação feita, mas sem prova (ex.: app iniciado sem janela visível): repete o aviso honesto
        unverified = [o for o in outs if o.executed and isinstance(o.data, dict) and o.data.get("verified") is False]
        if not failed and unverified:
            return " ".join(o.summary for o in unverified) + sim
        if not failed:
            return ok_text.format(title=title) + sim
        if len(failed) == len(outs):
            return f"Não consegui, {title}: {failed[0].summary}"
        return f"{ok_text.format(title=title)}{sim} Mas uma parte falhou: {failed[0].summary}"
    return render


class LocalRouter:
    def __init__(self, perms: Permissions, tool_names: Callable[[], set[str]], wake_word: str = "jarvis"):
        self.perms = perms
        self.tool_names = tool_names
        self.wake = fold(wake_word)

    # ------------------------------------------------------------------ entrada
    def match(self, text: str, allow_chat: bool = False) -> Plan | None:
        t = fold(text)
        t = re.sub(rf"^(ei |ok |oi )?{self.wake}\b[ ,]*", "", t).strip(" ,")
        if not t:
            return None
        # vários comandos na mesma frase: só local se TODAS as partes forem entendidas
        verbs = r"abr|lig|deslig|apag|acend|coloq|deix|toc|paus|despaus|aument|diminu|abaix|sob|minimiz|maximiz|organiz|ativ|prepar|fech|mud|volum|luz|leds?|prox|pul|volt|silenci|brilho"
        parts = [p.strip(" ,") for p in re.split(rf",| e depois | depois | e (?=(?:o |a |as |os )?(?:{verbs})\w*\b)", t) if p.strip(" ,")]
        plans = [self._one(p, False) for p in parts] if len(parts) >= 2 else []
        if not plans or any(p is None or p.kind in ("stop", "chat") for p in plans):
            return self._one(t, allow_chat)
        calls = [c for p in plans for c in p.calls]
        bounds, i = [], 0
        for p in plans:
            bounds.append((p, i, i + len(p.calls)))
            i += len(p.calls)

        def render(outs: list[ToolOutcome], title: str) -> str:
            return " ".join(p.render(outs[a:b], title) for p, a, b in bounds)

        return Plan("multi", calls, render)

    # ------------------------------------------------------------------ intenções
    def _one(self, t: str, allow_chat: bool) -> Plan | None:
        tools = self.tool_names()
        # perguntas abertas vão para a IA
        if re.search(r"\b(por que|porque|explique|explica|o que (e|significa)|quem (e|foi)|como funciona|me conte|escreva|resuma|traduza)\b", t):
            return None
        if re.fullmatch(r"(pare|para|parar|silencio|cala a boca|chega|cancela|cancelar|esquece|deixa pra la)( por favor)?", t):
            return Plan("stop")

        # ---- rotinas e cenas ("modo cinema", "prepara tudo para programar")
        if "run_routine" in tools:
            for rid, r in self.perms.routines.items():
                names = {fold(r.name), fold(rid), f"modo {fold(rid)}"}
                if any(re.search(rf"\b{re.escape(n)}\b", t) for n in names) or (rid == "programar" and re.search(r"\bprepar\w* .*program", t)):
                    return Plan("routine", [_call("run_routine", routine_id=rid)], _report(f"Rotina “{r.name}” executada, {{title}}."))
        # ---- luzes
        if "set_lights" in tools and re.search(r"\b(luz|luzes|led|leds|fita|lampada|iluminacao)\b|\bmodo cinema\b", t):
            plan = self._lights(t)
            if plan:
                return plan
        # ---- mídia
        if "media_control" in tools:
            if re.search(r"\b(proxima|pula|avanca)\b.*\b(musica|faixa|cancao)?\b", t) and re.search(r"\b(proxima|pula|avanca)\b", t):
                return Plan("media", [_call("media_control", action="next")], _report("Próxima faixa: tecla enviada, {title}."))
            if re.search(r"\b(anterior|volta a musica|musica anterior|faixa anterior)\b", t):
                return Plan("media", [_call("media_control", action="previous")], _report("Faixa anterior: tecla enviada."))
            if re.search(r"\b(pausa|pause|pausar|despausa|continua|retoma|toca|tocar|play)\b.*\b(musica|som|video|spotify|midia|isso)\b|^(pausa|pause|play|despausa)$", t):
                return Plan("media", [_call("media_control", action="play_pause")], _report("Tecla de tocar/pausar enviada."))
        # ---- volume
        if "set_volume" in tools and re.search(r"\b(volume|som|mudo|silencia)\b", t):
            plan = self._volume(t)
            if plan:
                return plan
        # ---- janelas
        if "window_control" in tools and re.search(r"\b(janela|janelas|lado a lado|area de trabalho|minimiz|maximiz|alterna|fecha)\w*", t):
            plan = self._windows(t)
            if plan:
                return plan
        # ---- abrir projeto / pasta / aplicativo
        if re.search(r"\b(abr[aei]\w*|inici[ae]\w*|execut[ae]\w*|lanc[ae]\w*|abre)\b", t):
            plan = self._open(t, tools)
            if plan:
                return plan
        # ---- consultas
        if "lock_hud" in tools and re.search(r"\b(bloque\w*|trav\w*|tranc\w*)\b.*\b(jarvis|sistema|hud|painel|tela|interface)\b", t):
            return Plan("lock", [_call("lock_hud")], _report("Bloqueado, {title}. Até logo."))
        if "city_briefing" in tools and re.search(r"\b(novidades|noticias|manchetes|resumo do dia|briefing)\b|\bcomo (esta|ta) a cidade\b|\bo que (esta acontecendo|aconteceu)\b", t):
            return Plan("briefing", [_call("city_briefing")], self._say_briefing)
        if re.search(r"\b(mostr|abr|exib|v[ae]\w* para)\w*\b.*\b(mapa|cidade)\b|\bmapa\b", t):
            return Plan("map", [_call("show_map")], self._say_map)
        if re.search(r"\b(clima|temperatura|chover|chuva|previsao)\b|\bcomo (esta|ta) o tempo\b|\bfaz (calor|frio)\b", t):
            return Plan("weather", [_call("get_weather")], self._say_weather)
        if re.search(r"\b(que horas|que hora|horas sao|que dia|data de hoje)\b", t):
            return Plan("time", [_call("get_local_time")], lambda o, title: f"São {o[0].data['time']}, {title}. Hoje é {o[0].data['date']}." if o[0].ok else f"Não consegui ler a hora: {o[0].summary}")
        if "list_processes" in tools and re.search(r"\b(processo|processos|consumindo|pesando)\b", t):
            return Plan("processes", [_call("list_processes", top=5, sort_by="ram" if re.search(r"\b(memoria|ram)\b", t) else "cpu")], self._say_processes)
        if re.search(r"\b(computador|sistema|cpu|processador|memoria|ram|disco|armazenamento|desempenho|pc)\b", t) and re.search(r"\b(como|status|estado|uso|usando|quanto|esta|ta)\b", t):
            return Plan("system", [_call("get_system_status")], self._say_system)
        if "list_devices" in tools and re.search(r"\b(dispositivos|aparelhos)\b", t):
            return Plan("devices", [_call("list_devices")], lambda o, title: o[0].summary)
        # ---- conversa (só sem IA)
        if allow_chat and re.fullmatch(r"(bom dia|boa tarde|boa noite|ola|oi|e ai|tudo bem|como vai)( \w+)?", t):
            return Plan("chat", [_call("get_local_time")], lambda o, title: f"{o[0].data['greeting'] if o[0].ok else 'Olá'}, {title}. Estou sem acesso à inteligência artificial agora, mas os comandos locais seguem funcionando.", chat=True)
        return None

    def _lights(self, t: str) -> Plan | None:
        if re.search(r"\bmodo cinema\b", t) and "cinema" in self.perms.scenes and "cinema" not in self.perms.routines:
            return Plan("lights", [_call("set_lights", scene_id="cinema")], _report("Modo cinema enviado às luzes."))
        for sid, scene in self.perms.scenes.items():
            if re.search(rf"\b(modo|cena) {re.escape(fold(sid))}\b|\b{re.escape(fold(scene.name))}\b", t):
                return Plan("lights", [_call("set_lights", scene_id=sid)], _report(f"Cena “{scene.name}” enviada às luzes."))
        if re.search(r"\b(desliga|desligue|desligar|apaga|apague|apagar)\b", t):
            return Plan("lights", [_call("set_lights", power="off")], _report("Comando para desligar as luzes enviado."))
        m = re.search(r"\bbrilho\b.*?(\d{1,3})|(\d{1,3}) ?(%|por cento)", t)
        word = next((v for k, v in NUM_WORDS.items() if re.search(rf"\bbrilho\b.*\b{k}\b", t)), None)
        if m or word is not None:
            value = max(0, min(100, int(next(g for g in m.groups() if g and g.isdigit())) if m else word))
            return Plan("lights", [_call("set_lights", brightness=value)], _report(f"Brilho de {value} por cento enviado às luzes."))
        for name, hexv in sorted(COLORS.items(), key=lambda kv: -len(kv[0])):
            if re.search(rf"\b{name}\b", t):
                return Plan("lights", [_call("set_lights", color=hexv)], _report(f"Luzes em {name}: comando enviado."))
        if re.search(r"\b(liga|ligue|ligar|acende|acenda|acender)\b", t):
            return Plan("lights", [_call("set_lights", power="on")], _report("Comando para ligar as luzes enviado."))
        return None

    def _volume(self, t: str) -> Plan | None:
        if re.search(r"\b(tira o mudo|desmuta|volta o som|ativa o som|liga o som)\b", t):
            return Plan("volume", [_call("set_volume", mute=False)], _report("Som de volta."))
        if re.search(r"\b(mudo|silencia|tira o som|corta o som)\b", t):
            return Plan("volume", [_call("set_volume", mute=True)], _report("Mudo ativado."))
        m = re.search(r"\b(\d{1,3})\b", t)
        word = next((v for k, v in NUM_WORDS.items() if re.search(rf"\b{k}\b", t)), None)
        if re.search(r"\bvolume\b", t) and (m or word is not None) and not re.search(r"\b(aument|diminu|abaix|sobe|desce)\w*", t):
            value = max(0, min(100, int(m.group(1)) if m else word))
            return Plan("volume", [_call("set_volume", percent=value)], _report(f"Volume em {value} por cento."))
        step = int(m.group(1)) if m else 10
        if re.search(r"\b(aument\w*|sobe|subir|mais alto)\b", t):
            return Plan("volume", [_call("change_volume", delta=min(step, 50))], _report("Volume aumentado."))
        if re.search(r"\b(diminu\w*|abaix\w*|desce|descer|mais baixo)\b", t):
            return Plan("volume", [_call("change_volume", delta=-min(step, 50))], _report("Volume diminuído."))
        if re.search(r"\b(qual|como esta|quanto)\b.*\bvolume\b|\bvolume atual\b", t):
            return Plan("volume", [_call("get_volume")], lambda o, title: o[0].summary)
        return None

    def _windows(self, t: str) -> Plan | None:
        def target(after: str) -> str:
            m = re.search(rf"{after}\s+(?:a |o |as |os )?(?:janela (?:do |da |de )?)?(.+)$", t)
            return m.group(1).strip() if m else ""

        if re.search(r"\b(organiza\w*|arruma\w*)\b.*\bjanelas\b|\blado a lado\b", t):
            m = re.search(r"\b(?:o|a)?\s*(\w[\w ]*?) e (?:o|a)?\s*(\w[\w ]*?) lado a lado\b", t)
            args = {"action": "arrange", "query": m.group(1), "other": m.group(2)} if m else {"action": "arrange"}
            return Plan("windows", [_call("window_control", **args)], _report("Janelas organizadas lado a lado."))
        if re.search(r"\b(minimiz\w* tudo|minimiz\w* todas|mostra\w* a area de trabalho|area de trabalho)\b", t):
            return Plan("windows", [_call("window_control", action="minimize_all")], _report("Área de trabalho à vista."))
        for verb, action, done in (("minimiz\\w*", "minimize", "Janela minimizada."), ("maximiz\\w*", "maximize", "Janela maximizada."),
                                   ("(?:alterna\\w* para|vai para|traz\\w*|mostra\\w*|foca\\w* (?:no|na))", "focus", "Pronto."),
                                   ("fecha\\w*", "close", "Pedido de fechamento enviado.")):
            if re.search(rf"\b{verb}\b", t):
                q = target(verb)
                q = re.sub(r"^(o|a|os|as) ", "", q)
                if q:
                    return Plan("windows", [_call("window_control", action=action, query=q[:80])], _report(done))
        return None

    def _open(self, t: str, tools: set[str]) -> Plan | None:
        if "open_project" in tools:
            for pid, proj in self.perms.projects.items():
                if re.search(rf"\b(projeto )?({re.escape(fold(pid))}|{re.escape(fold(proj.name))})\b", t) and ("projeto" in t or fold(proj.name) in t):
                    return Plan("project", [_call("open_project", project_id=pid)], _report(f"Projeto {proj.name} aberto, {{title}}."))
        if "open_folder" in tools and re.search(r"\bpasta\b", t):
            for fid, folder in self.perms.folders.items():
                if re.search(rf"\b({re.escape(fold(fid))}|{re.escape(fold(folder.name))})\b", t):
                    return Plan("folder", [_call("open_folder", folder_id=fid)], _report(f"Pasta {folder.name} aberta."))
        if "open_app" in tools:
            for aid, app in self.perms.apps.items():
                words = APP_WORDS.get(aid, []) + [fold(app.name), aid.replace("_", " ")]
                if any(re.search(rf"\b{re.escape(w)}\b", t) for w in words):
                    return Plan("app", [_call("open_app", app_id=aid)], _report(f"{app.name} aberto, {{title}}."))
        return None

    # ------------------------------------------------------------------ respostas faladas
    @staticmethod
    def _say_briefing(outs: list[ToolOutcome], title: str) -> str:
        return outs[0].summary if outs and outs[0].executed else f"Não consegui o resumo agora, {title}."

    @staticmethod
    def _say_map(outs: list[ToolOutcome], title: str) -> str:
        o = outs[0] if outs else None
        if not o or not o.executed:
            return f"Não consegui abrir o mapa, {title}."
        return "Aqui está a cidade." if o.data.get("real_map") else "Abrindo o mapa. O mapa real ainda está sendo baixado; por enquanto é a cidade de demonstração."

    @staticmethod
    def _say_weather(outs: list[ToolOutcome], title: str) -> str:
        o = outs[0]
        if not o.ok:
            return f"Não tenho o clima agora, {title}: {o.summary}"
        d, today = o.data, o.data.get("today") or {}
        text = f"Em {d['city']} faz {_n(d['temperature_c'])} graus, {d['condition'].lower()}, com sensação de {_n(d['feels_like_c'])}."
        if today:
            text += f" Hoje a máxima é de {_n(today['max_c'])} e a mínima de {_n(today['min_c'])}, com {_n(today['rain_probability'])} por cento de chance de chuva."
        return text

    @staticmethod
    def _say_system(outs: list[ToolOutcome], title: str) -> str:
        d = outs[0].data
        if not outs[0].ok:
            return f"Não consegui ler o sistema: {outs[0].summary}"
        text = f"Processador em {_n(d['cpu_percent'])} por cento, memória em {_n(d['ram_percent'])} por cento, e {_n(d['disk_free_gb'])} gigabytes livres no disco principal."
        if d.get("gpu"):
            text += f" A placa de vídeo está em {_n(d['gpu']['percent'])} por cento."
        return text

    @staticmethod
    def _say_processes(outs: list[ToolOutcome], title: str) -> str:
        rows = outs[0].data.get("processes", [])[:3]
        if not rows:
            return "Não consegui ler os processos."
        return "Os que mais consomem agora: " + ", ".join(f"{r['name']} com {_n(r['cpu_percent'])} por cento de CPU e {_n(r['ram_mb'])} megabytes" for r in rows) + "."
