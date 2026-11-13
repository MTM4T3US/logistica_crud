"""0.7: anotações, lista de compras, cotações, time, resumo da semana, Pomodoro, ler a seleção, modo jogo."""
import asyncio
import json
from datetime import datetime, timedelta

import httpx
import pytest

from app.ai.base import ToolCall
from app.assistant import Assistant
from app.devices.registry import DeviceRegistry
from app.memory.store import MemoryStore
from app.router import LocalRouter
from app.security.permissions import Permissions
from app.services.finance import Finance, brl, say_quotes
from app.services.lists import Lists, split_items
from app.services.pomodoro import Pomodoro, say_left
from app.services.weather import WeatherService
from app.system.desk_extras import is_game, read_selection

from .conftest import FakeController


def make_core(settings, tmp_path, **kw):
    settings.permissions_path = tmp_path / "permissions.json"
    settings.permissions_path.write_text(json.dumps(kw.pop("perms", {})), encoding="utf-8")
    return Assistant(settings, gemini=None, memory=MemoryStore(":memory:"), controller=FakeController(), devices=DeviceRegistry(),
                     weather=WeatherService(settings.location, enabled=False), wake=None, **kw)


async def yes(_):
    return True


async def no(_):
    return False


async def quiet(_):
    return None


# ---------------------------------------------------------------- serviços
def test_shopping_list_splits_dedupes_and_removes_by_partial_name():
    assert split_items("leite, o pão e 2 kg de arroz; Leite") == ["leite", "pão", "2 kg de arroz"]
    lists = Lists(":memory:")
    assert lists.add_items(["Leite integral", "pão"]) == (["Leite integral", "pão"], [])
    assert lists.add_items(["leite integral", "café"]) == (["café"], ["leite integral"])
    assert lists.remove_items(["leite", "banana"]) == (["Leite integral"], ["banana"])
    assert lists.remove_items(["pao"]) == (["pão"], [])                                      # sem acento também acha
    lists.add_items(["pão"])
    assert lists.items() == ["café", "pão"]
    assert lists.clear_items() == 2 and lists.items() == []


def test_notes_keep_the_text_and_filter_by_day():
    now = [datetime(2026, 11, 13, 9, 0)]
    lists = Lists(":memory:", clock=lambda: now[0])
    lists.add_note("ligar para o banco")
    now[0] += timedelta(days=3)
    lists.add_note("Comprar presente da Mãe")
    assert [n["text"] for n in lists.notes_today()] == ["Comprar presente da Mãe"]
    assert len(lists.notes_week()) == 2 and lists.find_notes("banco")[0]["text"] == "Ligar para o banco"
    with pytest.raises(ValueError):
        lists.add_note("   ")


async def test_quotes_come_from_the_source_or_say_they_failed():
    def ok(req):
        return httpx.Response(200, json={"USDBRL": {"bid": "5.4321", "pctChange": "0.42"}, "BTCBRL": {"bid": "512340.5", "pctChange": "-1.2"}})

    fin = Finance(client=httpx.AsyncClient(transport=httpx.MockTransport(ok)))
    q = await fin.get()
    assert say_quotes(q) == "Dólar a R$ 5,43 (+0,4% hoje) e Bitcoin a R$ 512 mil (-1,2%)."
    assert say_quotes(q, ("usd",)).startswith("Dólar a R$ 5,43") and brl(1234.5) == "R$ 1.234,50"

    def down(req):
        return httpx.Response(503)

    bad = await Finance(client=httpx.AsyncClient(transport=httpx.MockTransport(down))).get()
    assert bad["ok"] is False and "Não consegui as cotações" in say_quotes(bad)          # nunca inventa número
    assert (await Finance(enabled=False).get())["ok"] is False


async def test_pomodoro_cycles_focus_and_breaks_and_can_stop():
    t = [0.0]
    events = []

    async def fake_sleep(s):
        t[0] += s
        await asyncio.sleep(0)

    async def changed(phase, info):
        events.append(phase)

    p = Pomodoro(changed, clock=lambda: t[0], sleep=fake_sleep)
    st = p.start(25, 5, 2)
    assert st["phase"] == "foco" and st["left_s"] == 1500 and "faltam 25 minutos" in say_left(st)
    await asyncio.wait_for(p.task, 1)
    assert events == ["foco", "pausa", "foco", "fim"] and p.done_today == 2 and p.public() is None
    p.start(1, 1, 4)
    assert await p.stop() is True and p.public() is None and say_left(None) == "Nenhum Pomodoro em andamento."


def test_games_are_recognised_by_folder_or_user_list():
    assert is_game(r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\bin\win64\cs2.exe")
    assert is_game(r"C:\Riot Games\VALORANT\live\VALORANT.exe") and is_game(r"D:\Epic Games\Fortnite\FortniteClient-Win64-Shipping.exe")
    assert not is_game(r"C:\Program Files (x86)\Steam\steam.exe")                    # o launcher não é jogo
    assert not is_game(r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE") and not is_game("")
    assert is_game(r"C:\Jogos\Meu\jogo_indie.exe", ("jogo_indie",))


class FakeScreen:
    def __init__(self, title="Documento - Word", exe="WINWORD.EXE", selected="Texto selecionado  na tela."):
        self.title, self.exe, self.selected, self.combos, self.clip = title, exe, selected, [], None

    def foreground(self):
        return self.title, self.exe

    def foreground_path(self):
        return self.exe

    def combo(self, c):
        self.combos.append(c)
        if self.selected is not None:
            self.clip.value = self.selected


class FakeClip:
    def __init__(self, value="o que eu tinha copiado"):
        self.value = value

    def get(self):
        return self.value

    def set(self, text):
        self.value = text


def test_read_selection_copies_reads_and_restores_the_clipboard():
    si, clip = FakeScreen(), FakeClip()
    si.clip = clip
    assert read_selection(si, clip, wait=lambda s: None) == (True, "Texto selecionado na tela.")
    assert clip.value == "o que eu tinha copiado" and si.combos == ["ctrl+c"]                 # a área de transferência volta
    term = FakeScreen(title="Prompt de Comando", exe="cmd.exe")
    term.clip = clip
    ok, why = read_selection(term, clip, wait=lambda s: None)
    assert not ok and "terminais" in why and term.combos == []                               # Ctrl+C num terminal interrompe programas
    empty = FakeScreen(selected=None)
    empty.clip = clip
    assert read_selection(empty, clip, wait=lambda s: None) == (False, "Nada selecionado: selecione o texto e peça de novo.")
    assert clip.value == "o que eu tinha copiado"


# ---------------------------------------------------------------- roteador (sem Gemini)
TOOLS = {"shop_add", "shop_remove", "shop_list", "shop_clear", "note_add", "notes_list", "note_remove", "read_selection", "pomodoro_start",
         "pomodoro_stop", "pomodoro_status", "game_mode", "get_quotes", "team_news", "week_summary", "agenda_add", "agenda_list", "media_control", "get_local_time"}


@pytest.mark.parametrize("text,tool,args", [
    ("põe leite, pão e café na lista", "shop_add", {"items": "leite, pão e café"}),
    ("Jarvis, coloca Sabão em Pó na lista de compras", "shop_add", {"items": "Sabão em Pó"}),
    ("tira o pão da lista", "shop_remove", {"items": "o pão"}),
    ("o que tem na lista?", "shop_list", {}),
    ("limpa a lista de compras", "shop_clear", {}),
    ("anota: ligar para o Banco do Brasil", "note_add", {"text": "ligar para o Banco do Brasil"}),
    ("anota aí que a senha do wifi mudou", "note_add", {"text": "a senha do wifi mudou"}),
    ("minhas anotações da semana", "notes_list", {"period": "semana"}),
    ("lê pra mim", "read_selection", {}),
    ("lê o texto selecionado", "read_selection", {}),
    ("começa um pomodoro", "pomodoro_start", {}),
    ("começa um pomodoro de 50 minutos com pausa de 10", "pomodoro_start", {"focus_min": 50, "break_min": 10}),
    ("quanto falta do pomodoro?", "pomodoro_status", {}),
    ("pausa o pomodoro", "pomodoro_stop", {}),
    ("modo jogo", "game_mode", {"on": True}),
    ("sai do modo jogo", "game_mode", {"on": False}),
    ("quanto está o dólar?", "get_quotes", {"which": "dolar"}),
    ("cotação do bitcoin", "get_quotes", {"which": "bitcoin"}),
    ("como foi o jogo do meu time?", "team_news", {}),
    ("e o Goiás, ganhou?", "team_news", {}),
    ("como vai ser a minha semana?", "week_summary", {}),
])
def test_new_phrases_route_locally(text, tool, args):
    plan = LocalRouter(Permissions(), lambda: TOOLS, team=lambda: "Goiás").match(text)
    assert plan is not None and plan.calls[0].name == tool and plan.calls[0].args == args


def test_notes_with_a_date_stay_in_the_agenda_and_media_pause_still_works():
    r = LocalRouter(Permissions(), lambda: TOOLS)
    assert r.match("anota dentista amanhã às 15h").calls[0].name == "agenda_add"
    assert r.match("pausa a música").calls[0].name == "media_control"


# ---------------------------------------------------------------- núcleo
async def test_tools_through_the_core(settings, tmp_path):
    core = make_core(settings, tmp_path)
    run = lambda name, **a: core.tools.execute(ToolCall("1", name, a), yes, quiet)   # noqa: E731
    assert (await run("shop_add", items="leite e pão")).summary == "Pronto: leite e pão na lista."
    assert (await run("shop_add", items="Leite")).summary == "Pronto: Leite já estava."
    assert (await run("shop_list")).summary == "Na lista (2): leite e pão."
    assert (await core.tools.execute(ToolCall("2", "shop_clear", {}), no, quiet)).executed is False     # pede confirmação
    assert (await run("note_add", text="ligar para o banco")).summary == "Anotado: Ligar para o banco"
    assert (await run("notes_list")).summary == "Uma anotação hoje: Ligar para o banco."
    st = await core.state()
    assert st["lists"]["shopping"] == ["leite", "pão"] and st["pomodoro"] is None and st["game"] == {"on": False, "source": ""}
    assert "read_selection" not in core.tools.specs() and "team_news" not in core.tools.specs()          # sem Windows / sem time
    core.update_runtime({"team": " Goiás "})
    assert core.runtime()["team"] == "Goiás" and "team_news" in core.tools.specs()
    assert core.update_runtime({"team": "<script>"})["team"] == "Goiás"


async def test_lists_stay_private_while_locked(settings, tmp_path, monkeypatch):
    core = make_core(settings, tmp_path)
    monkeypatch.setattr(type(core.gate), "open", property(lambda self: False))
    assert (await core.state())["lists"] is None


async def test_game_mode_switches_on_with_a_game_and_off_after_two_misses(settings, tmp_path):
    screen = FakeScreen(exe=r"C:\Riot Games\VALORANT\live\VALORANT.exe")
    core = make_core(settings, tmp_path, screen=screen, clipboard=FakeClip(), perms={"jogos": ["meujogo"]})
    events = []

    async def cap(ev):
        events.append(ev)
        return 1

    core.broadcast = cap
    assert await core.check_game() is True and core.game["on"] and events[-1] == {"type": "ui", "action": "game", "on": True, "source": "auto"}
    screen.exe = r"C:\Program Files\JARVIS\navegador.exe"
    assert await core.check_game() is None and core.game["on"]           # 1 leitura fora: ainda não (alt+tab rápido)
    assert await core.check_game() is False and not core.game["on"]
    screen.exe = r"D:\x\meujogo.exe"
    assert await core.check_game() is True                              # lista do usuário (permissions.json → "jogos")
    core.update_runtime({"game_auto": False})
    await core.set_game_mode(False, "voz")
    assert await core.check_game() is None and not core.game["on"]     # automático desligado


async def test_week_summary_lists_the_week_birthdays_and_pending_items(settings, tmp_path):
    core = make_core(settings, tmp_path)
    now = core.agenda.now()
    core.agenda.add("Dentista", (now + timedelta(days=2)).replace(hour=15, minute=0))
    core.agenda.add("Aniversário da Mãe", (now + timedelta(days=3)).replace(hour=0, minute=0), all_day=True)
    core.lists.add_items(["leite"])
    text = await core.week_summary()
    assert text.startswith("Resumo da semana, senhor. 1 compromisso nos próximos 7 dias:") and "Dentista" in text
    assert "Aniversários: Aniversário da Mãe" in text and "1 item na lista de compras" in text


async def test_week_summary_runs_once_on_sunday_night_and_goes_to_telegram(settings, tmp_path):
    core = make_core(settings, tmp_path)
    sent, events = [], []

    async def remote(text):
        sent.append(text)

    async def cap(ev):
        events.append(ev)
        return 0

    core.remote.append(remote)
    core.broadcast = cap
    sunday = datetime(2026, 11, 15, 20, 1)
    assert sunday.weekday() == 6
    assert (await core.run_week_summary(sunday)).startswith("Resumo da semana")
    assert await core.run_week_summary(sunday + timedelta(minutes=1)) is None                  # uma vez
    assert await core.run_week_summary(datetime(2026, 11, 16, 20, 1)) is None                   # segunda: não
    assert len(sent) == 1 and sent[0].startswith("Resumo da semana")
    core.update_runtime({"week_summary": {"on": False, "day": 6, "at": "20:00"}})
    assert await core.run_week_summary(datetime(2026, 11, 22, 20, 1)) is None


async def test_briefing_adds_quotes_and_birthdays(settings, tmp_path):
    def ok(req):
        return httpx.Response(200, json={"USDBRL": {"bid": "5.10", "pctChange": "0"}})

    core = make_core(settings, tmp_path, finance=Finance(client=httpx.AsyncClient(transport=httpx.MockTransport(ok))))
    now = core.agenda.now()
    core.agenda.add("Aniversário do Pedro", now.replace(hour=0, minute=0), all_day=True)
    b = await core.briefing()
    assert "Hoje tem Aniversário do Pedro." in b["briefing"] and "Dólar a R$ 5,10" in b["briefing"]
    assert b["briefing"].endswith("Em que posso ajudar, senhor?")


# ---------------------------------------------------------------- celular
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.mobile import DeviceStore, MobileGateway, create_mobile_app, lan_addresses, qr_svg  # noqa: E402


def test_pairing_codes_expire_limit_tries_and_store_only_a_hash(tmp_path):
    t = [1000.0]
    store = DeviceStore(tmp_path / "aparelhos.json", clock=lambda: t[0])
    assert store.pair("123456", "x") == (None, "Código vencido: gere outro no HUD (Configurações → Sistema → Celular).")
    code = store.new_code()["code"]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(4):
        assert store.pair(wrong, "x")[0] is None
    assert store.pair(wrong, "x")[1] == "Código errado demais: gere outro no HUD."
    assert store.pair(code, "x")[0] is None                                    # o código morreu depois de 5 erros
    code = store.new_code()["code"]
    t[0] += 301
    assert store.pair(code, "x")[0] is None                                    # 5 minutos
    code = store.new_code()["code"]
    token, msg = store.pair(code, "Celular do Mateus <script>")
    assert token and msg == "Celular do Mateus script pareado."
    saved = (tmp_path / "aparelhos.json").read_text(encoding="utf-8")
    assert token not in saved and store.devices[0]["hash"] in saved              # só o hash vai para o disco
    assert DeviceStore(tmp_path / "aparelhos.json").check(token)["name"] == "Celular do Mateus script"
    assert store.check("outro") is None and store.check(None) is None
    assert store.remove(store.devices[0]["id"]) and store.check(token) is None


@pytest.fixture
def phone(settings, tmp_path):
    core = make_core(settings, tmp_path)
    store = DeviceStore(None)
    c = TestClient(create_mobile_app(core, store))
    code = store.new_code()["code"]
    token = c.post("/m/pair", json={"code": code, "name": "Teste"}).json()["token"]
    c.headers["Authorization"] = "Bearer " + token
    c.core, c.store = core, store
    return c


def test_phone_page_and_state_need_the_device_key(phone):
    page = TestClient(phone.app).get("/")
    assert page.status_code == 200 and "PAREAR ESTE CELULAR" in page.text and page.headers["x-frame-options"] == "DENY"
    assert TestClient(phone.app).get("/m/state").status_code == 401
    assert TestClient(phone.app).get("/m/state", headers={"Authorization": "Bearer chute"}).status_code == 401
    assert TestClient(phone.app).get("/../app/main.py").status_code == 404
    st = phone.get("/m/state").json()
    assert st["device"] == "Teste" and st["city"] == "Itumbiara" and [s["id"] for s in st["scenes"]][:2] == ["bom_dia", "cinema"]
    assert st["quick"]["door"] is True and st["door"]["id"] == "fechadura" and st["lists"] == {"shopping": [], "notes": []}


def test_phone_runs_scenes_with_the_same_confirmation(phone):
    r = phone.post("/m/quick", json={"action": "cena:foco"}).json()
    assert r["reply"].startswith("Modo foco") and r["tools"][0]["name"] == "run_routine"
    ask = phone.post("/m/quick", json={"action": "cena:saindo"}).json()
    assert ask["needs_confirm"].startswith("Executar a rotina “Saindo de casa”") and ask["tools"] == []
    assert phone.post("/m/say", json={"confirm_id": ask["confirm_id"], "approve": False}).json()["reply"] == "Cancelado."
    ask = phone.post("/m/quick", json={"action": "cena:saindo"}).json()
    done = phone.post("/m/say", json={"confirm_id": ask["confirm_id"], "approve": True}).json()
    assert done["tools"][0]["executed"] is True
    assert phone.post("/m/say", json={"confirm_id": ask["confirm_id"], "approve": True}).status_code == 410   # uma vez só
    assert phone.post("/m/quick", json={"action": "porta:unlock"}).status_code == 400


def test_phone_cannot_touch_the_screen_or_keyboard(phone):
    r = phone.post("/m/say", json={"text": "digita: oi"}).json()
    assert r["tools"] == [] or all(not t["executed"] for t in r["tools"])
    core = phone.core
    from app.assistant import REMOTE_DENY

    assert {"computer_task", "type_text", "press_keys", "take_screenshot", "recycle_file", "kill_process"} <= REMOTE_DENY
    r = phone.post("/m/say", json={"text": "põe leite e pão na lista"}).json()
    assert r["reply"] == "Pronto: leite e pão na lista." and core.lists.items() == ["leite", "pão"]


def test_phone_lists_and_notes(phone):
    assert phone.post("/m/list", json={"op": "add", "items": "café, açúcar"}).json()["shopping"] == ["café", "açúcar"]
    assert phone.post("/m/list", json={"op": "remove", "items": "acucar"}).json()["shopping"] == ["café"]
    assert phone.post("/m/list", json={"op": "note", "items": "ligar pro mecânico"}).json()["notes"][0]["text"] == "Ligar pro mecânico"
    assert phone.post("/m/list", json={"op": "drop"}).status_code == 400


async def test_remote_turns_refuse_denied_tools_even_if_planned(settings, tmp_path):
    from app.router import Plan, _call

    core = make_core(settings, tmp_path)
    plan = Plan("pc", [_call("type_text", text="oi")], lambda o, title: o[0].summary)
    out = await core.run_remote("digita oi", "celular", plan=plan)
    assert out["tools"][0]["executed"] is False and "só no próprio computador" in out["reply"]


def test_hud_controls_the_phone_server(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MOBILE_HOST", "127.0.0.1")
    monkeypatch.setenv("JARVIS_MOBILE_PORT", "18766")
    settings.local_token = "token-de-teste"
    core = make_core(settings, tmp_path)
    h = {"host": "127.0.0.1:8765", "x-jarvis-token": "token-de-teste"}
    with TestClient(create_app(settings, core), base_url="http://127.0.0.1:8765") as c:
        st = c.get("/api/mobile", headers=h).json()
        assert st["enabled"] is False and st["running"] is False
        assert c.post("/api/mobile/pair", headers=h).status_code == 400                     # desligado: sem código
        assert c.post("/api/settings", headers=h, json={"mobile_enabled": True}).status_code == 200
        st = c.get("/api/mobile", headers=h).json()
        assert st["running"] is True and all(u.endswith(":18766/") for u in st["urls"])
        pair = c.post("/api/mobile/pair", headers=h).json()
        assert len(pair["code"]) == 6 and pair["qr"].startswith("<svg")
        # o servidor do celular responde de verdade na porta própria; a API do HUD não existe lá
        r = httpx.get("http://127.0.0.1:18766/", timeout=5)
        assert r.status_code == 200 and "JARVIS" in r.text
        assert httpx.get("http://127.0.0.1:18766/api/state", timeout=5).status_code == 404
        c.post("/api/settings", headers=h, json={"mobile_enabled": False})
        assert c.get("/api/mobile", headers=h).json()["running"] is False
        with pytest.raises(httpx.HTTPError):
            httpx.get("http://127.0.0.1:18766/", timeout=2)


def test_qr_and_addresses():
    assert qr_svg("http://192.168.0.10:8766/#pair=123456").startswith("<svg")
    assert all(a.count(".") == 3 for a in lan_addresses())


# ---------------------------------------------------------------- Telegram (servidor falso)
from app.services.telegram import TelegramBot  # noqa: E402


class FakeTelegram:
    def __init__(self):
        self.updates, self.sent, self.uid = [], [], 0

    def push(self, chat, text=None, data=None, kind="private"):
        self.uid += 1
        if data is not None:
            self.updates.append({"update_id": self.uid, "callback_query": {"id": str(self.uid), "data": data, "message": {"chat": {"id": chat, "type": kind}}}})
        else:
            self.updates.append({"update_id": self.uid, "message": {"chat": {"id": chat, "type": kind}, "text": text}})

    def handler(self, req):
        method = req.url.path.rsplit("/", 1)[-1]
        body = json.loads(req.content or b"{}")
        if "/botRUIM/" in req.url.path:
            return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"username": "meu_jarvis_bot"}})
        if method == "getUpdates":
            ups = [u for u in self.updates if u["update_id"] >= body.get("offset", 0)]
            return httpx.Response(200, json={"ok": True, "result": ups})
        if method == "sendMessage":
            self.sent.append(body)
        return httpx.Response(200, json={"ok": True, "result": {}})

    def texts(self, chat=None):
        return [m["text"] for m in self.sent if chat is None or m["chat_id"] == chat]


async def settle(max_s: float = 1.0):
    """Espera as tarefas do bot terminarem (as que esperam um botão ficam pendentes até max_s)."""
    for _ in range(int(max_s / 0.01)):
        busy = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done() and "confirm" not in repr(t.get_coro())]
        if not busy:
            await asyncio.sleep(0.02)
            return
        await asyncio.sleep(0.01)


async def test_telegram_pairs_one_chat_ignores_others_and_runs_commands(settings, tmp_path):
    core = make_core(settings, tmp_path)
    tg = FakeTelegram()
    bot = TelegramBot("TOKEN", core, tmp_path / "telegram.json", client=httpx.AsyncClient(transport=httpx.MockTransport(tg.handler)), poll_timeout=0)
    core.remote.append(bot.notify)
    await bot.start()
    bot.task.cancel()
    assert bot.username == "meu_jarvis_bot" and bot.status()["paired"] is False
    tg.push(111, "oi")                                      # sem pareamento: explica como parear
    code = bot.new_code()["code"]
    tg.push(111, "/parear 000000" if code != "000000" else "/parear 111111")
    tg.push(111, f"/parear {code}")
    await bot.poll_once(); await settle()
    assert "ainda não está pareado" in tg.texts(111)[0] and tg.texts(111)[1] == "Código errado."
    assert tg.texts(111)[2].startswith("Pareado.") and bot.chat_id == 111
    assert json.loads((tmp_path / "telegram.json").read_text())["chat_id"] == 111
    tg.push(222, "põe vodka na lista")                      # outra pessoa: silêncio e nada muda
    tg.push(111, "põe leite e pão na lista", kind="group")  # grupo: ignorado
    tg.push(111, "põe leite e pão na lista")
    await bot.poll_once(); await settle()
    assert tg.texts(222) == [] and core.lists.items() == ["leite", "pão"] and tg.texts(111)[-1] == "Pronto: leite e pão na lista."
    tg.push(111, "/cenas")
    await bot.poll_once(); await settle()
    buttons = tg.sent[-1]["reply_markup"]["inline_keyboard"]
    assert buttons[0][0] == {"text": "Bom dia", "callback_data": "cena:bom_dia"}
    tg.push(111, data="cena:foco")
    await bot.poll_once(); await settle()
    assert tg.texts(111)[-1].startswith("Modo foco")
    # confirmação por botão: "limpa a lista" pergunta; Não → nada; Sim → limpa
    tg.push(111, "limpa a lista")
    await bot.poll_once(); await settle()
    ask = tg.sent[-1]
    assert ask["text"].startswith("Apagar a lista de compras inteira") and ask["reply_markup"]["inline_keyboard"][0][1]["text"] == "Não"
    bid = ask["reply_markup"]["inline_keyboard"][0][0]["callback_data"].split(":")[1]
    tg.push(222, data=f"ok:{bid}")                          # botão apertado por outro chat: ignorado
    await bot.poll_once(); await settle()
    assert core.lists.items() == ["leite", "pão"]
    tg.push(111, data=f"ok:{bid}")
    await bot.poll_once(); await settle()
    assert core.lists.items() == [] and tg.texts(111)[-1] == "Lista de compras limpa."
    # avisos do núcleo chegam no chat pareado
    await core.notify_remote("⏰ Dentista, em 15 minutos.")
    assert tg.texts(111)[-1] == "⏰ Dentista, em 15 minutos."
    tg.push(111, "/desparear")
    await bot.poll_once(); await settle()
    assert bot.chat_id is None and not (tmp_path / "telegram.json").exists()
    await bot.stop()


async def test_telegram_blocks_screen_actions_and_stops_on_a_bad_token(settings, tmp_path):
    from app.router import Plan, _call

    core = make_core(settings, tmp_path)
    tg = FakeTelegram()
    bot = TelegramBot("TOKEN", core, None, client=httpx.AsyncClient(transport=httpx.MockTransport(tg.handler)), poll_timeout=0)
    bot.chat_id = 111
    await bot._run("tira um print", Plan("pc", [_call("take_screenshot")], lambda o, title: o[0].summary))
    assert "só no próprio computador" in tg.texts(111)[-1]
    bad = TelegramBot("RUIM", core, None, client=httpx.AsyncClient(transport=httpx.MockTransport(tg.handler)), poll_timeout=0)
    await bad.loop()                                         # 401: para sozinho, com o motivo
    assert "recusou o token" in bad.error and "RUIM" not in bad.error


async def test_new_quick_buttons_for_gestures_pomodoro_and_game(settings, tmp_path):
    core = make_core(settings, tmp_path)
    tools = set(core.tools.specs())
    for action, tool in (("midia:play_pause", "media_control"), ("volume:up", "change_volume"), ("pomodoro:start", "pomodoro_start"), ("jogo:off", "game_mode")):
        found = core.quick_plan(action)
        if tool in tools:
            assert found is not None and found[1].calls[0].name == tool, action
    assert core.quick_plan("volume:max") is None and core.quick_plan("midia:apagar") is None
    out = await core.run_remote("Começar Pomodoro", "celular", plan=core.quick_plan("pomodoro:start")[1])
    assert out["tools"][0]["executed"] and core.pomodoro.running
    await core.pomodoro.stop()
