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

from datetime import datetime

from .services.agenda import parse_event
from .system.desktop import SETTINGS_PAGES
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
    # pontos entre letras ficam (sites como youtube.com); os de fim de frase saem
    return re.sub(r"\s+", " ", re.sub(r"[!?;]+|\.(?!\w)|(?<!\w)\.", " ", text)).strip()


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


def _call(_tool: str, **args: Any) -> ToolCall:
    return ToolCall(id="local-" + uuid.uuid4().hex[:8], name=_tool, args=args)


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
        # feito só em parte (ex.: rotina com 1 de 2 etapas): nunca dizer "executada"
        partial = [o for o in outs if o.executed and not o.ok]
        if not failed and partial:
            o = partial[0]
            step = next((s.get("message", "") for s in (o.data or {}).get("steps", []) if not s.get("executed")), "")
            return f"Só em parte, {title}: {o.summary}" + (f" Falhou: {step}" if step else "") + sim
        if not failed:
            return ok_text.format(title=title) + sim
        if len(failed) == len(outs):
            return f"Não consegui, {title}: {failed[0].summary}"
        return f"{ok_text.format(title=title)}{sim} Mas uma parte falhou: {failed[0].summary}"
    return render


def _launched(spoken: str) -> Callable[[list[ToolOutcome], str], str]:
    """Resposta de "abre o <programa>" (0.5): usa o nome REAL encontrado no Menu Iniciar ("Word"), não o
    que foi falado ("word"). Visto no Windows: "senhor, word aberto." em vez de "Word aberto, senhor."
    As chaves do nome falado são escapadas (um "{" no texto quebrava o format)."""
    safe = spoken.replace("{", "{{").replace("}", "}}")
    fallback = _report(f"{safe} aberto, {{title}}.")

    def render(outs: list[ToolOutcome], title: str) -> str:
        o = outs[0] if outs else None
        verified = not (o is not None and isinstance(o.data, dict) and o.data.get("verified") is False)
        if o is not None and o.ok and o.executed and verified and " aberto" in o.summary:
            return f"{o.summary.split(' aberto')[0]} aberto, {title}."
        return fallback(outs, title)

    return render


class LocalRouter:
    def __init__(self, perms: Permissions, tool_names: Callable[[], set[str]], wake_word: str = "jarvis",
                 lights: Callable[[], list[tuple[str, str]]] | None = None):
        self.perms = perms
        self.tool_names = tool_names
        #: luzes de casa (id, nome) — para "luz da sala"
        self.lights = lights or (lambda: [])
        self.wake = fold(wake_word)

    # ------------------------------------------------------------------ entrada
    def match(self, text: str, allow_chat: bool = False) -> Plan | None:
        self._raw = text or ""   # original (maiúsculas e acentos) para o "digita:" — match é síncrono
        t = fold(text)
        t = re.sub(rf"^(ei |ok |oi )?{self.wake}\b[ ,]*", "", t).strip(" ,")
        if not t:
            return None
        self._whole = t          # cenas "exatas" ("bom dia") só valem como frase inteira, nunca como pedaço
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

        # ---- rotinas e cenas ("modo cinema", "prepara tudo para programar", "bom dia", "estou saindo")
        if "run_routine" in tools:
            for rid, r in self.perms.routines.items():
                names = {fold(r.name), fold(rid).replace("_", " "), f"modo {fold(rid).replace('_', ' ')}", *(fold(w) for w in r.words)}
                if r.exact:
                    # "bom dia"/"boa noite": só a frase inteira (não "bom dia, que horas são?")
                    hit = t == getattr(self, "_whole", t) and any(re.fullmatch(rf"{re.escape(n)}(,? (jarvis|senhor|chefe))?", t) for n in names)
                else:
                    hit = any(re.search(rf"\b{re.escape(n)}\b", t) for n in names)
                if hit or (rid == "programar" and re.search(r"\bprepar\w* .*program", t)):
                    return Plan("routine", [_call("run_routine", routine_id=rid)], self._say_routine(r.name))
        # ---- fechadura: trancar e ver (destrancar por voz não existe)
        if "control_device" in tools and re.search(r"\bmodo trancado\b|\bninguem (entra|abre)\b|\bbloque\w* (a )?fechadura\b", t):
            return Plan("lock", [_call("control_device", device_id="fechadura", action="lockdown")], lambda o, title: o[0].summary)
        if "control_device" in tools and re.search(r"\b(porta|fechadura)\b", t):
            if re.search(r"\b(destranc\w*|abr\w*|libera\w*)\b", t):
                return Plan("lock", [], lambda o, title: f"Destrancar por voz não é permitido, {title}. Use o teclado, a digital ou a chave da fechadura.")
            if re.search(r"\b(tranc\w*|fech\w*)\b", t) and not re.search(r"\b(esta|ta|ficou)\b.*\btrancad", t):
                return Plan("lock", [_call("control_device", device_id="fechadura", action="lock")], lambda o, title: o[0].summary)
            if re.search(r"\b(trancad\w*|aberta|estado|status|como esta)\b", t):
                return Plan("lock", [_call("control_device", device_id="fechadura", action="status")], lambda o, title: o[0].summary)
        # ---- luzes de casa (Tuya) — "leds"/"fita" continuam indo só para a fita
        if "house_lights" in tools and not re.search(r"\b(led|leds|fita)\b", t) and (
                re.search(r"\b(luz|luzes|lampada|lampadas|iluminacao|abajur|luminaria)\b", t) or self._light_hits(t)[1] > 0):
            plan = self._house(t)
            if plan:
                return plan
        # ---- luzes
        # "brilho em 30%" sozinho também é das luzes (visto no teste do Windows: ia para o Gemini, que
        # respondeu "comando enviado" sem chamar ferramenta nenhuma). Brilho da TELA fica de fora.
        if "set_lights" in tools and (re.search(r"\b(luz|luzes|led|leds|fita|lampada|iluminacao)\b|\bmodo cinema\b", t)
                                      or (re.search(r"\bbrilho\b", t) and not re.search(r"\b(tela|monitor|ecra|display|notebook)\b", t))):
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
        # ---- agenda (0.5)
        plan = self._agenda(t, tools)
        if plan:
            return plan
        # ---- computador (0.5): energia, brilho, captura, arquivos, sites, programas, teclado
        plan = self._pc(t, tools)
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

    def _light_hits(self, t: str) -> tuple[list[str], int]:
        """Luzes cujo nome aparece na frase (pelo maior número de palavras em comum)."""
        generic = {"luz", "luzes", "lampada", "lampadas", "de", "da", "do", "das", "dos", "e", "a", "o"}
        scored: list[tuple[int, str]] = []
        for dev_id, name in self.lights():
            words = [w for w in re.split(r"[\s_]+", fold(name)) if w and w not in generic]
            hits = sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", t))
            if hits:
                scored.append((hits, dev_id))
        if not scored:
            return [], 0
        top = max(h for h, _ in scored)
        return [d for h, d in scored if h == top], top

    def _house(self, t: str) -> Plan | None:
        hits, _ = self._light_hits(t)
        if len(hits) > 1:
            return None                      # dois aparelhos com o mesmo nome: melhor perguntar do que chutar
        args: dict[str, Any] = {"target": hits[0] if hits else "todas"}
        if re.search(r"\b(desliga|desligue|desligar|apaga|apague|apagar)\b", t):
            args["power"] = "off"
        else:
            m = re.search(r"\b(\d{1,3}) ?(%|por cento)|\bbrilho\b\D*(\d{1,3})", t)
            if m:
                args["brightness"] = max(1, min(100, int(m.group(1) or m.group(3))))
            if re.search(r"\b(branca|branco|luz branca)\b", t):
                args["white"] = True
            else:
                for name, hexv in sorted(COLORS.items(), key=lambda kv: -len(kv[0])):
                    if re.search(rf"\b{name}\b", t):
                        args["color"] = hexv
                        break
            if re.search(r"\b(liga|ligue|ligar|acende|acenda|acender)\b", t) or len(args) == 1:
                args["power"] = "on"
        if len(args) == 1:
            return None
        return Plan("lights", [_call("house_lights", **args)], lambda o, title: o[0].summary)

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
        if "launch_app" in tools:
            # 0.5: qualquer programa instalado (o nome é procurado no Menu Iniciar, não executado)
            m = re.search(r"\b(?:abr[aei]\w*|inici[ae]\w*|execut[ae]\w*|lanc[ae]\w*)\s+(?:o |a |os |as )?(?:programa |aplicativo |app )?(.+)$", t)
            name = m.group(1).strip() if m else ""
            if name and not re.search(r"\b(mapa|cidade|projeto|pasta|site|arquivo|janela|configurac\w*)\b|\.\w{2,3}\b|^(o|a|os|as)?\s*\d+$", name):
                return Plan("app", [_call("launch_app", name=name[:60])], _launched(name[:60]))
        return None

    #: frases que começam assim são perguntas ou outros comandos, nunca um compromisso sem verbo
    NOT_EVENT = re.compile(r"^(e |o que|que|qual|quais|quando|quanto|como|onde|tenho|liga|desliga|abr\w*|fech\w*|apag\w*|acend\w*|toc\w*|"
                           r"coloc\w*|poe|aument\w*|diminu\w*|baix\w*|sob\w*|bloque\w*|tranc\w*|mostr\w*|pesquis\w*|procur\w*|mand\w*|digit\w*|"
                           r"tir\w*|cancel\w*|desmarc\w*|paus\w*|volt\w*|vai|ativ\w*|desativ\w*|minimiz\w*|maximiz\w*|organiz\w*|pul\w*)\b")

    def _raw_tail(self, pattern: str) -> str | None:
        """O mesmo trecho na frase ORIGINAL (maiúsculas e acentos), para o título do compromisso.
        Visto no Windows: "Teste de lembrete do JARVIS" virava "Teste de lembrete do jarvis"."""
        raw = re.sub(rf"(?i)^\s*(?:(?:ei|ok|oi)\s+)?{self.wake}\b[\s,]*", "", getattr(self, "_raw", "") or "").strip()
        m = re.match(pattern, raw, re.IGNORECASE)
        return m.group(1).strip(" .!?") if m else None

    def _agenda(self, t: str, tools: set[str]) -> Plan | None:
        if "agenda_list" in tools:
            if re.search(r"\b(minha agenda|meus compromissos|meus horarios|o que (eu )?tenho|tenho (algum|alguma|compromisso)\w*|agenda (de|da|do|pra|para))\b|^agenda$|\bcompromissos (de|da|pra|para)\b", t):
                if re.search(r"\bsemana\b", t):
                    return Plan("agenda", [_call("agenda_list", days=7)], lambda o, title: o[0].summary)
                day = "amanha" if re.search(r"\bamanha\b", t) else "hoje"
                return Plan("agenda", [_call("agenda_list", day=day)], lambda o, title: o[0].summary)
        if "agenda_add" in tools:
            m = re.match(r"^(?:marc\w*|agend\w*|anot\w*|lembr\w*|me lembr\w*|cri\w*|adicion\w*)\b(?: na (?:minha )?agenda| um compromisso| compromisso| um lembrete| lembrete| um evento| evento)?(?: de| que| pra| para)?\s+(.+)$", t)
            if m and parse_event(m.group(1), datetime.now()) is not None:      # sem data/hora: não é agenda (ex.: "lembra que…")
                raw = self._raw_tail(r"^(?:me\s+)?(?:marc\w*|agend\w*|anot\w*|lembr\w*|cri\w*|adicion\w*)(?:-me)?\b(?:\s+na\s+(?:minha\s+)?agenda|"
                                     r"\s+(?:um\s+)?compromisso|\s+(?:um\s+)?lembrete|\s+(?:um\s+)?evento)?(?:\s+(?:de|que|pra|para))?\s+(.+)$")
                phrase = raw if raw and parse_event(raw, datetime.now()) is not None else m.group(1)
                return Plan("agenda", [_call("agenda_add", phrase=phrase[:200])], lambda o, title: o[0].summary)
        if "agenda_remove" in tools and re.search(r"\b(agenda|compromisso|lembrete|evento|desmarc\w*)\b", t):
            m = re.match(r"^(?:cancel\w*|desmarc\w*|apag\w*|remov\w*|exclu\w*|tir\w*)\b(?: o| a)?(?: compromisso| lembrete| evento)?(?: d[oae])?\s+(.+?)(?: da (?:minha )?agenda)?$", t)
            if m:
                return Plan("agenda", [_call("agenda_remove", query=m.group(1)[:80])], lambda o, title: o[0].summary)
        if "agenda_add" in tools and not self.NOT_EVENT.match(t):
            # sem verbo: "academia toda segunda às 8h", "dentista amanhã às 15h" (visto no Windows: ia ao Gemini,
            # que perguntava a data em vez de marcar). Só com hora ou repetição, e um nome de verdade.
            ev = parse_event(t, datetime.now())
            if ev and (ev["repeat"] or not ev["all_day"]) and len(re.sub(r"[^a-z]", "", fold(ev["title"]))) >= 3:
                raw = self._raw_tail(r"^(.+)$")
                phrase = raw if raw and parse_event(raw, datetime.now()) is not None else t
                return Plan("agenda", [_call("agenda_add", phrase=phrase[:200])], lambda o, title: o[0].summary)
        return None

    ORDINALS = {"primeiro": 1, "segundo": 2, "terceiro": 3, "quarto": 4, "quinto": 5, "sexto": 6, "setimo": 7, "oitavo": 8, "nono": 9, "decimo": 10}
    KEY_WORDS = {"copia": "ctrl+c", "copie": "ctrl+c", "cola": "ctrl+v", "cole": "ctrl+v", "recorta": "ctrl+x", "desfaz": "ctrl+z", "desfaca": "ctrl+z",
                 "refaz": "ctrl+y", "salva": "ctrl+s", "salve": "ctrl+s", "seleciona tudo": "ctrl+a", "nova aba": "ctrl+t", "atualiza a pagina": "f5",
                 "tela cheia": "f11", "troca de janela": "alt+tab", "proxima aba": "ctrl+tab"}

    def _pc(self, t: str, tools: set[str]) -> Plan | None:
        pc = r"\b(computador|pc|maquina|notebook|windows)\b"
        if "computer_task" in tools:
            m = re.search(r"^(?:usa|use|usar) (?:o )?(?:computador|pc) (?:para|pra|e) (.+)$|^(?:no computador|faz no computador|faca no computador)[, ]+(.+)$|^assum\w* o controle (?:e|para|pra) (.+)$", t)
            if m:
                task = next(g for g in m.groups() if g)
                return Plan("pc", [_call("computer_task", task=task[:500])], lambda o, title: o[0].summary)
        if "cancel_shutdown" in tools and re.search(r"\bcancel\w* (o )?(desligamento|reinicio)\b|\bnao (desliga|reinicia)\b", t):
            return Plan("pc", [_call("cancel_shutdown")], _report("Desligamento cancelado, {title}."))
        if "shutdown_pc" in tools and re.search(pc, t):
            restart = bool(re.search(r"\breinici\w*\b", t))
            if restart or re.search(r"\b(deslig\w*)\b", t):
                # "em 10 minutos", "daqui a 5 min", "em 90 segundos": o tempo dito vale (30 s a 10 min)
                m = re.search(r"\b(?:em|daqui a|daqui|depois de)\s+(\d{1,4}|um|uma|meia)\s*(h|horas?|min\w*|s|seg\w*)\b", t)
                delay = 60
                if m:
                    n = {"um": 1, "uma": 1, "meia": 0.5}.get(m.group(1)) or int(m.group(1))
                    unit = m.group(2)
                    delay = int(n * (3600 if unit.startswith("h") else 60 if unit.startswith("min") else 1))
                    if delay > 600:
                        return Plan("pc", [], lambda _o, title: f"Consigo agendar no máximo 10 minutos, {title}. Peça de novo mais perto da hora.")
                    delay = max(30, delay)
                when = "um minuto" if delay == 60 else f"{delay // 60} minutos" if delay % 60 == 0 else f"{delay} segundos"
                verb = "Reiniciando" if restart else "Desligando"
                args = {"restart": restart, **({"delay_s": delay} if delay != 60 else {})}
                return Plan("pc", [_call("shutdown_pc", **args)], _report(f"{verb} em {when}, {{title}}."))
        if "sleep_pc" in tools and re.search(r"\b(suspend\w*|hibern\w*|suspensao)\b", t):
            return Plan("pc", [_call("sleep_pc")], _report("Suspendendo, {title}."))
        if "lock_windows" in tools and re.search(r"\b(bloque\w*|trav\w*)\b", t) and re.search(pc, t):
            return Plan("pc", [_call("lock_windows")], _report("Windows bloqueado."))
        if "set_brightness" in tools and re.search(r"\bbrilho\b", t) and re.search(r"\b(tela|monitor|notebook|display)\b", t):
            m = re.search(r"(\d{1,3})", t)
            word = next((v for k, v in NUM_WORDS.items() if re.search(rf"\b{k}\b", t)), None)
            if m or word is not None:
                value = max(0, min(100, int(m.group(1)) if m else word))
                return Plan("pc", [_call("set_brightness", percent=value)], _report(f"Brilho da tela em {value} por cento."))
        if "take_screenshot" in tools and re.search(r"\b(print|printscreen|captura (de |da )?tela|foto da tela)\b", t):
            return Plan("pc", [_call("take_screenshot")], lambda o, title: o[0].summary if o[0].executed else f"Não consegui: {o[0].summary}")
        if "find_files" in tools:
            m = re.search(r"\b(?:procur\w*|busc\w*|ach\w*|encontr\w*)\b (?:o |a |os |as |pelo |pela )?(?:arquivo|arquivos|documento|planilha|foto|pdf)s? (?:chamad[oa] |de nome |com o nome )?(.+)$", t)
            if m:
                return Plan("pc", [_call("find_files", query=m.group(1).strip()[:80])], lambda o, title: o[0].summary)
        if "recycle_file" in tools:
            m = re.search(r"\b(\d{1,2}|" + "|".join(self.ORDINALS) + r")\b.*\blixeira\b", t)
            if m:
                idx = int(m.group(1)) if m.group(1).isdigit() else self.ORDINALS[m.group(1)]
                return Plan("pc", [_call("recycle_file", index=idx)], _report("Arquivo enviado para a Lixeira."))
        if "open_file" in tools:
            m = re.search(r"\b(abr\w*|mostr\w*|apag\w*|exclu\w*|lixeira)\b (?:o |a )?(?:arquivo )?(?:numero )?(\d{1,2}|" + "|".join(self.ORDINALS) + r")\b", t)
            if m:
                idx = int(m.group(2)) if m.group(2).isdigit() else self.ORDINALS[m.group(2)]
                verb = m.group(1)
                if verb.startswith(("apag", "exclu", "lixeira")):
                    return Plan("pc", [_call("recycle_file", index=idx)], _report("Arquivo enviado para a Lixeira."))
                if verb.startswith("mostr"):
                    return Plan("pc", [_call("show_file", index=idx)], _report("Mostrando na pasta."))
                return Plan("pc", [_call("open_file", index=idx)], _report("Abrindo o arquivo."))
        if "open_website" in tools:
            m = re.search(r"\b([a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com\.br|gov\.br|org\.br|com|org|net|br|io|dev|tv|app|me|gg))(/\S*)?\b", t)
            if m and re.search(r"\b(abr\w*|entr\w*|acess\w*|vai|ir|site)\b", t):
                return Plan("pc", [_call("open_website", url=m.group(0))], _report(f"Abrindo {m.group(1)}."))
        if "web_search" in tools:
            m = re.search(r"\b(?:pesquis\w*|procur\w*|busc\w*|googl\w*|toc\w*|coloc\w*)\b (?:por |sobre )?(.+?) (?:no|na) (google|youtube|maps|mapa|wikipedia)\b", t)
            if m:
                site = {"mapa": "maps"}.get(m.group(2), m.group(2))
                return Plan("pc", [_call("web_search", query=m.group(1)[:300], site=site)], _report("Pesquisando, {title}."))
            m = re.search(r"^(?:pesquis\w*|googl\w*)\s+(?:por |sobre )?(.+)$", t)
            if m:
                return Plan("pc", [_call("web_search", query=m.group(1)[:300], site="google")], _report("Pesquisando no Google, {title}."))
        if "open_settings" in tools:
            m = re.search(r"\b(?:configurac\w*|ajustes|opcoes)\b (?:de |do |da |dos |das )?([a-z ]+?)$", t)
            if m and fold(m.group(1)) in SETTINGS_PAGES:
                return Plan("pc", [_call("open_settings", page=fold(m.group(1)))], _report(f"Configurações de {m.group(1)} abertas."))
        if "kill_process" in tools:
            m = re.search(r"\b(?:forc\w* (?:o )?fechamento d[oa]|mata\w* (?:o )?(?:processo )?|encerr\w* a forca (?:o |a )?)(.+)$", t)
            if m:
                return Plan("pc", [_call("kill_process", name=m.group(1).strip()[:60])], _report("Encerrado."))
        if "close_app" in tools and not re.search(r"\bjanela\b", t):
            m = re.search(r"\b(?:fech\w*|encerr\w*|sai\w* do|sai\w* da)\s+(?:o |a |os |as )?(?:programa |aplicativo |app )?(.+)$", t)
            if m and not re.search(r"\b(tudo|todas|luz|luzes|leds?|fita|porta|persiana)\b", m.group(1)):
                return Plan("pc", [_call("close_app", name=m.group(1).strip()[:60])], _report("Pedido de fechamento enviado."))
        if "type_text" in tools:
            m = re.search(r"^digit\w*:?\s+(.+)$", t)
            if m:
                # digita o texto como foi dito/escrito: visto no Windows, "teste do JARVIS" saía "teste do jarvis"
                raw = re.search(r"(?i)\bdigit\w*:?\s+(.+)$", getattr(self, "_raw", "") or "")
                typed = raw.group(1).strip() if raw else m.group(1)
                return Plan("pc", [_call("type_text", text=typed[:500])], _report("Digitado."))
        if "press_keys" in tools:
            for words, combo in sorted(self.KEY_WORDS.items(), key=lambda kv: -len(kv[0])):
                if re.fullmatch(rf"{words}( isso| tudo| o arquivo| a pagina)?", t):
                    return Plan("pc", [_call("press_keys", keys=combo)], _report("Feito."))
            m = re.search(r"\b(?:aperta|aperte|pressiona|pressione|tecla)\s+(.+)$", t)
            if m:
                return Plan("pc", [_call("press_keys", keys=m.group(1).replace(" mais ", "+").replace(" e ", "+")[:30])], _report("Atalho enviado."))
        return None

    # ------------------------------------------------------------------ respostas faladas
    @staticmethod
    def _say_routine(name: str) -> Callable[[list[ToolOutcome], str], str]:
        """Cena: diz o que foi feito; se ela tem resumo da cidade ou agenda, fala o resumo."""
        def render(outs: list[ToolOutcome], title: str) -> str:
            o = outs[0] if outs else None
            if o is None or not o.executed:
                return f"Não consegui, {title}: {o.summary if o else 'sem resposta'}"
            speech = " ".join(o.data.get("speech", []))
            failed = [st["message"] for st in o.data.get("steps", []) if not st.get("executed") and not st.get("skipped")]
            head = f"{name}, {title}." if speech else f"{name} pronto, {title}."
            tail = f" Mas uma parte falhou: {failed[0]}" if failed else ""
            return f"{head} {speech}{tail}".strip()
        return render

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
