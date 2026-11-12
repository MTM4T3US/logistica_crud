"""Ferramentas que a IA pode pedir. A IA só planeja; quem valida e executa é este módulo.

Cada ferramenta tem um esquema fechado (sem texto livre que vire comando), uma classe de
permissão e devolve um ToolOutcome com `executed`/`simulated` verdadeiros — é isso que o
painel "comandos executados" mostra.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..config import Settings
from ..devices.registry import DeviceRegistry
from ..memory.store import MemoryStore
from ..security.permissions import ActionClass, Permissions
from ..services.local_info import local_now
from ..services.news import NewsService
from ..services.weather import WeatherService
from ..system.monitor import SystemMonitor
from ..system.windows import ActionResult, SystemController
from .base import ToolCall, ToolOutcome

Confirm = Callable[[str], Awaitable[bool]]
Notify = Callable[[dict[str, Any]], Awaitable[None]]
Handler = Callable[[dict[str, Any], "ToolRun"], Awaitable[ToolOutcome]]


@dataclass
class ToolSpec:
    name: str
    label: str
    description: str
    parameters: dict[str, Any]
    action_class: ActionClass
    handler: Handler


@dataclass
class ToolRun:
    """Contexto de UMA execução: a chamada, como pedir confirmação e como avisar o HUD."""
    call: ToolCall
    confirm: Confirm
    notify: Notify


def _obj(props: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


def validate_args(schema: dict[str, Any], args: Any) -> str | None:
    """Validação estrita dos argumentos vindos da IA. Devolve o erro ou None."""
    if not isinstance(args, dict):
        return "os argumentos não são um objeto"
    props = schema.get("properties", {})
    for key in args:
        if key not in props:
            return f"argumento desconhecido '{key}'"
    for key in schema.get("required", []):
        if key not in args:
            return f"faltou o argumento '{key}'"
    for key, value in args.items():
        spec = props[key]
        kind = spec.get("type")
        if kind == "string" and not isinstance(value, str):
            return f"'{key}' deve ser texto"
        if kind == "integer":
            if isinstance(value, float) and value.is_integer():
                value = args[key] = int(value)
            if not isinstance(value, int) or isinstance(value, bool):
                return f"'{key}' deve ser um número inteiro"
        if kind == "boolean" and not isinstance(value, bool):
            return f"'{key}' deve ser verdadeiro ou falso"
        if "enum" in spec and value not in spec["enum"]:
            return f"'{key}' = '{value}' não está na lista autorizada"
        if kind == "integer" and ("minimum" in spec and value < spec["minimum"] or "maximum" in spec and value > spec["maximum"]):
            return f"'{key}' fora do intervalo permitido"
        if kind == "string" and len(value) > spec.get("maxLength", 400):
            return f"'{key}' é longo demais"
    return None


class ToolRegistry:
    def __init__(
        self, *, settings: Settings, perms: Permissions, monitor: SystemMonitor, controller: SystemController,
        devices: DeviceRegistry, weather: WeatherService, news: NewsService, memory: MemoryStore,
        memory_enabled: Callable[[], bool],
    ):
        self.settings, self.perms, self.monitor, self.controller = settings, perms, monitor, controller
        self.devices, self.weather, self.news, self.memory = devices, weather, news, memory
        self.memory_enabled = memory_enabled

    # ------------------------------------------------------------------ catálogo
    def specs(self) -> dict[str, ToolSpec]:
        p = self.perms
        specs: list[ToolSpec] = [
            ToolSpec("get_local_time", "Hora local", "Data e hora atuais na cidade do usuário.", _obj(), ActionClass.READ, self._time),
            ToolSpec("get_weather", "Clima", "Clima atual e previsão de 4 dias para a cidade do usuário, de fonte meteorológica real.", _obj(), ActionClass.READ, self._weather),
            ToolSpec("get_system_status", "Estado do computador", "Leitura real de CPU, memória RAM, discos, bateria, GPU e tempo ligado deste computador.", _obj(), ActionClass.READ, self._system),
            ToolSpec("get_news", "Notícias", "Manchetes da fonte de notícias configurada pelo usuário. Devolve erro se não houver fonte.", _obj(), ActionClass.READ, self._news),
            ToolSpec("list_capabilities", "Capacidades", "Lista o que está autorizado: aplicativos, pastas, rotinas, dispositivos e recursos disponíveis neste sistema.", _obj(), ActionClass.READ, self._capabilities),
            ToolSpec("show_map", "Mapa no HUD", "Mostra a cena de mapa 3D no HUD. Atenção: é uma cidade fictícia de demonstração, não um mapa real.", _obj(), ActionClass.SAFE, self._show_map),
        ]
        if p.process_list:
            specs.append(ToolSpec(
                "list_processes", "Processos", "Processos que mais usam CPU ou memória agora.",
                _obj({"top": {"type": "integer", "minimum": 1, "maximum": 25}, "sort_by": {"type": "string", "enum": ["cpu", "ram"]}}),
                ActionClass.READ, self._processes))
        if p.apps:
            names = "; ".join(f"{a.id} = {a.name}" for a in p.apps.values())
            specs.append(ToolSpec(
                "open_app", "Abrir aplicativo", f"Abre um aplicativo pré-autorizado. Identificadores: {names}.",
                _obj({"app_id": {"type": "string", "enum": list(p.apps)}}, ["app_id"]), ActionClass.SAFE, self._open_app))
        if p.folders:
            names = "; ".join(f"{f.id} = {f.name}" for f in p.folders.values())
            specs.append(ToolSpec(
                "open_folder", "Abrir pasta", f"Abre no explorador uma pasta pré-aprovada. Identificadores: {names}.",
                _obj({"folder_id": {"type": "string", "enum": list(p.folders)}}, ["folder_id"]), ActionClass.SAFE, self._open_folder))
        if p.routines:
            names = "; ".join(f"{r.id} = {r.name}" for r in p.routines.values())
            specs.append(ToolSpec(
                "run_routine", "Executar rotina", f"Executa uma rotina cadastrada (sequência fixa de ações autorizadas). Identificadores: {names}.",
                _obj({"routine_id": {"type": "string", "enum": list(p.routines)}}, ["routine_id"]), ActionClass.SAFE, self._routine))
        if p.volume_control:
            specs.append(ToolSpec("get_volume", "Ler volume", "Lê o volume principal do computador.", _obj(), ActionClass.READ, self._get_volume))
            specs.append(ToolSpec(
                "set_volume", "Ajustar volume", "Define o volume principal (0 a 100) e/ou ativa/desativa o mudo.",
                _obj({"percent": {"type": "integer", "minimum": 0, "maximum": 100}, "mute": {"type": "boolean"}}), ActionClass.SAFE, self._set_volume))
        if self.devices.ids():
            specs.append(ToolSpec("list_devices", "Dispositivos", "Estado dos dispositivos cadastrados (nesta versão, todos são simuladores).", _obj(), ActionClass.READ, self._list_devices))
            specs.append(ToolSpec(
                "control_device", "Comandar dispositivo",
                "Envia um comando a um dispositivo. Ações — leds: on, off, color (color=#RRGGBB), brightness (value 0-100); "
                "persiana: open, close, stop, position (value 0-100); fechadura: status, lock (unlock é sempre recusado); "
                "robo: status, move (direction, value=velocidade), stop, emergency_stop, reset_emergency.",
                _obj({
                    "device_id": {"type": "string", "enum": self.devices.ids()},
                    "action": {"type": "string", "enum": ["on", "off", "color", "brightness", "open", "close", "stop", "position", "status", "lock", "unlock", "move", "emergency_stop", "reset_emergency"]},
                    "value": {"type": "integer", "minimum": 0, "maximum": 100},
                    "color": {"type": "string", "maxLength": 7},
                    "direction": {"type": "string", "enum": ["forward", "backward", "left", "right"]},
                }, ["device_id", "action"]),
                ActionClass.SAFE, self._control_device))
        if self.memory_enabled():
            specs.append(ToolSpec(
                "remember", "Guardar lembrança", "Guarda um fato que o usuário pediu explicitamente para lembrar.",
                _obj({"fact": {"type": "string", "maxLength": 300}}, ["fact"]), ActionClass.SAFE, self._remember))
            specs.append(ToolSpec("recall_memory", "Consultar lembranças", "Lista os fatos guardados a pedido do usuário.", _obj(), ActionClass.READ, self._recall))
        return {s.name: s for s in specs}

    def declarations(self) -> list[dict[str, Any]]:
        return [{"name": s.name, "description": s.description, "parameters": s.parameters} for s in self.specs().values()]

    def label(self, name: str) -> str:
        spec = self.specs().get(name)
        return spec.label if spec else name

    # ------------------------------------------------------------------ execução
    async def execute(self, call: ToolCall, confirm: Confirm, notify: Notify) -> ToolOutcome:
        spec = self.specs().get(call.name)
        if spec is None:
            return ToolOutcome(call, False, False, f"A ferramenta '{call.name}' não existe ou não está autorizada.")
        if spec.action_class is ActionClass.FORBIDDEN:
            return ToolOutcome(call, False, False, "Esta ação é proibida para o assistente.")
        problem = validate_args(spec.parameters, call.args)
        if problem:
            return ToolOutcome(call, False, False, f"Pedido recusado: {problem}.")
        try:
            return await spec.handler(call.args, ToolRun(call, confirm, notify))
        except Exception as exc:  # uma ferramenta com defeito não derruba a conversa
            return ToolOutcome(call, False, False, f"Falha interna ao executar {spec.label} ({type(exc).__name__}).")

    @staticmethod
    def _from_action(call: ToolCall, res: ActionResult) -> ToolOutcome:
        return ToolOutcome(call, res.ok, res.executed, res.message, data=res.data)

    # ------------------------------------------------------------------ leitura
    async def _time(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        now = local_now(self.settings.location)
        return ToolOutcome(run.call, True, True, f"{now['time']} em {now['city']} — {now['date']}.", data=now)

    async def _weather(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        data = await self.weather.get()
        if not data.get("ok"):
            return ToolOutcome(run.call, False, False, data.get("error", "Clima indisponível."), data={"source": data.get("source")})
        summary = f"{data['city']}: {round(data['temperature_c'])}°C, {data['condition'].lower()} (Open-Meteo, {data['fetched_at_text']})."
        return ToolOutcome(run.call, True, True, summary, data=data)

    async def _system(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        d = await asyncio.to_thread(self.monitor.details)
        summary = f"CPU {d['cpu_percent']}% · RAM {d['ram_percent']}% · disco {d['disk_percent']}% usado ({d['disk_free_gb']} GB livres)."
        return ToolOutcome(run.call, True, True, summary, data=d)

    async def _processes(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        rows = await asyncio.to_thread(self.monitor.processes, args.get("top", 8), args.get("sort_by", "cpu"))
        top = rows[0] if rows else None
        summary = f"{len(rows)} processos lidos" + (f"; maior consumo: {top['name']}." if top else ".")
        return ToolOutcome(run.call, True, True, summary, data={"processes": rows})

    async def _news(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        data = await self.news.get()
        if not data.get("ok"):
            return ToolOutcome(run.call, False, False, data["error"], data={"items": []})
        return ToolOutcome(run.call, True, True, f"{len(data['items'])} manchetes de {data['source']}.", data=data)

    async def _capabilities(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        data = {"permissions": self.perms.summary(), "system_actions": self.controller.capabilities(), "platform": self.controller.platform, "devices": self.devices.describe()}
        return ToolOutcome(run.call, True, True, "Capacidades autorizadas listadas.", data=data)

    async def _show_map(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        await run.notify({"type": "ui", "action": "show_map"})
        return ToolOutcome(run.call, True, True, "Cena de mapa aberta no HUD (cidade fictícia de demonstração, não é um mapa real).", data={"demo_scene": True, "real_map": False})

    async def _get_volume(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        return self._from_action(run.call, await asyncio.to_thread(self.controller.get_volume))

    async def _list_devices(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        devs = self.devices.describe()
        out = ToolOutcome(run.call, True, True, f"{len(devs)} dispositivos cadastrados (todos simuladores).", data={"devices": devs})
        out.simulated = any(d["simulated"] for d in devs)
        return out

    async def _recall(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        facts = await asyncio.to_thread(self.memory.facts)
        return ToolOutcome(run.call, True, True, f"{len(facts)} lembranças guardadas.", data={"facts": [f["text"] for f in facts]})

    # ------------------------------------------------------------------ ações
    async def _open_app(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        app = self.perms.apps[args["app_id"]]
        if app.confirm and not await run.confirm(f"Abrir o aplicativo {app.name}?"):
            return ToolOutcome(run.call, False, False, f"O usuário não autorizou abrir {app.name}.")
        return self._from_action(run.call, await asyncio.to_thread(self.controller.open_app, app))

    async def _open_folder(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        folder = self.perms.folders[args["folder_id"]]
        return self._from_action(run.call, await asyncio.to_thread(self.controller.open_folder, folder))

    async def _set_volume(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        if "percent" not in args and "mute" not in args:
            return ToolOutcome(run.call, False, False, "Pedido recusado: informe 'percent' e/ou 'mute'.")
        return self._from_action(run.call, await asyncio.to_thread(self.controller.set_volume, args.get("percent"), args.get("mute")))

    async def _routine(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        routine = self.perms.routines[args["routine_id"]]
        if routine.confirm and not await run.confirm(f"Executar a rotina “{routine.name}” ({len(routine.steps)} etapas)?"):
            return ToolOutcome(run.call, False, False, f"O usuário não autorizou a rotina {routine.name}.")
        steps = []
        for i, step in enumerate(routine.steps):
            sub = ToolCall(id=f"{run.call.id}.{i + 1}", name=step["tool"], args=dict(step.get("args", {})))
            # etapas de rotina já foram aprovadas em bloco: não pedem confirmação individual
            res = await self.execute(sub, _approved, run.notify)
            steps.append({"tool": sub.name, "args": sub.args, "ok": res.ok, "executed": res.executed, "message": res.summary})
        done = sum(1 for s in steps if s["executed"])
        ok = done == len(steps)
        summary = f"Rotina {routine.name}: {done} de {len(steps)} etapas executadas."
        return ToolOutcome(run.call, ok, done > 0, summary, data={"steps": steps})

    async def _control_device(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        params = {k: args[k] for k in ("value", "color", "direction") if k in args}
        if args["action"] == "move" and "value" in params:
            params["speed"] = params["value"]
        res = self.devices.command(args["device_id"], args["action"], params)
        await run.notify({"type": "devices", "devices": self.devices.describe()})
        return ToolOutcome(run.call, res.ok, res.executed, res.message, simulated=res.simulated, data={"state": res.state})

    async def _remember(self, args: dict[str, Any], run: ToolRun) -> ToolOutcome:
        fact = args["fact"].strip()
        if not fact:
            return ToolOutcome(run.call, False, False, "Nada para guardar.")
        await asyncio.to_thread(self.memory.add_fact, fact)
        return ToolOutcome(run.call, True, True, "Lembrança guardada no banco local.")


async def _approved(_: str) -> bool:
    return True
