"""Offline end-to-end test for server.py — mocked GM, real engine + DB."""
import os
import tempfile

os.environ["TAVERN_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["TAVERN_NO_ANIM"] = "1"

from fastapi.testclient import TestClient

import server
from gm import GameMaster

# Scripted GM: first call narrates + stats an enemy + choices; the choice
# turn returns a follow-up with damage; then a plain wrap-up.
REPLIES = [
    (
        "The cellar door bursts open. **Gnash** the goblin snarls at Rui.\n"
        "[[enemy: Gnash | level 1 | str 12 dex 14 con 10 int 8 wis 8 cha 6 | icon: goblin | "
        "gear: Rusty Cleaver (normal weapon) | skills: Frenzy (1d6+STR): flurry]]\n"
        "[[equip: Lucky Pin | rare | trinket | dex+2 | Glint: reroll one die a day]]\n"
        "[[choice: Charge Gnash head-on | STR | DC 12]]\n"
        "[[choice: Slip behind the barrels | DEX* | DC 13]]\n"
        "[[choice: Talk it out | none]]"
    ),
    (
        "Steel meets green flesh!\n"
        "[[damage: enemy | 1d6 | str | Charge]]\n"
        "[[sheet: xp=+50 | First blood]]\n"
        "[[choice: Press the attack | STR | DC 12]]\n"
        "[[choice: Kick sand at it | DEX | DC 11]]\n"
        "[[choice: Back off warily | none]]"
    ),
    "The dust settles. Gnash whimpers into a corner.",
]
calls = {"n": 0}


def fake_invoke(self, prompt):
    i = min(calls["n"], len(REPLIES) - 1)
    calls["n"] += 1
    return REPLIES[i]


GameMaster._invoke = fake_invoke

client = TestClient(server.app)

# ---- REST: bootstrap, stat roll, creation
boot = client.get("/api/bootstrap").json()
assert any(s["key"] == "tavern" for s in boot["scenarios"]), "scenarios missing"

stats = client.post("/api/roll-stats").json()
assert all(3 <= stats["scores"][a] <= 18 for a in stats["scores"]), "bad stat roll"

hero = client.post("/api/heroes", json={
    "name": "Rui", "scenario": "tavern", "race": "Elf", "char_class": "Rogue",
    "lang": "en", "premise": "", "scores": stats["scores"],
}).json()
cid = hero["id"]

state = client.get(f"/api/heroes/{cid}/state").json()
assert state["name"] == "Rui" and state["level"] == 1
assert len(state["inventory"]) >= 3, "starting kit missing"

# ---- WS: opener turn
with client.websocket_connect(f"/ws/{cid}") as ws:
    types = []
    msg = ws.receive_json()
    assert msg["type"] == "state"
    msg = ws.receive_json()
    assert msg["type"] == "hello" and msg["resuming"] is False

    ws.send_json({"type": "start"})
    choices = enemies = None
    while True:
        m = ws.receive_json()
        types.append(m["type"])
        if m["type"] == "choices":
            choices = m["choices"]
        if m["type"] == "state":
            enemies = m["state"]["enemies"]
        if m["type"] == "idle":
            break
    assert "event" in types, "no events streamed"
    assert len(choices) == 3, f"expected 3 choices, got {choices}"
    assert choices[0]["trait"] == "str" and choices[0]["dc"] == 12
    assert choices[1]["prof"] is True and choices[1]["need"] >= 2
    assert choices[2]["trait"] is None
    assert len(enemies) == 1 and enemies[0]["tier"] == "full", enemies
    # "Gnash" matches no hand-drawn preset → art is None (icon fallback),
    # while preset names still ship ANSI art.
    assert enemies[0]["art"] is None, "expected icon fallback for Gnash"
    assert enemies[0]["icon"] == "goblin", f"GM-picked icon lost: {enemies[0]}"
    import art as art_mod
    assert art_mod.has_preset("Goblin Chief") and art_mod.art_for("Goblin Chief")

    # gear granted by [[equip]] shows in state
    st = client.get(f"/api/heroes/{cid}/state").json()
    assert any(e["rarity"] == "rare" for e in st["equipment"]), "rare gear missing"

    # ---- WS: pick choice 1 (STR DC 12) — may trigger a reroll confirm
    ws.send_json({"type": "choice", "index": 0, "power": False})
    got_confirm = False
    while True:
        m = ws.receive_json()
        if m["type"] == "confirm":
            got_confirm = True
            ws.send_json({"type": "confirm", "answer": False})
        if m["type"] == "idle":
            break
    print(f"  (reroll confirm offered: {got_confirm})")

    st = client.get(f"/api/heroes/{cid}/state").json()
    assert st["xp"] >= 50, f"xp not awarded: {st['xp']}"
    gnash = st["enemies"][0]
    assert gnash["hp"] < gnash["max_hp"], "damage not applied"

# ---- REST: equip toggling, log, language, delete
st = client.get(f"/api/heroes/{cid}/state").json()
pin = next(e for e in st["equipment"] if e["name"] == "Lucky Pin")
st2 = client.post(f"/api/heroes/{cid}/equip", json={"equipment_id": pin["id"]}).json()
assert next(e for e in st2["equipment"] if e["id"] == pin["id"])["equipped"]
assert st2["stats"]["dex"]["gear"] == 2, "gear bonus not reflected"

log = client.get(f"/api/heroes/{cid}/log").json()["events"]
assert any(e["kind"] == "roll" for e in log), "rolls missing from log"
assert any(e["kind"] == "gm" for e in log), "narration missing from log"

# ---- WS: instant resume — a returning hero gets the saved choice menu
# immediately, with no GM call burned just to look at the game.
gm_calls_before = calls["n"]
with client.websocket_connect(f"/ws/{cid}") as ws:
    msg = ws.receive_json()
    assert msg["type"] == "state"
    msg = ws.receive_json()
    assert msg["type"] == "hello" and msg["resuming"] is True
    assert msg["instant"] is True, f"expected instant resume: {msg}"
    msg = ws.receive_json()
    assert msg["type"] == "choices" and len(msg["choices"]) == 3, msg
    assert msg["choices"][0]["text"] == "Press the attack", msg["choices"]
    msg = ws.receive_json()
    assert msg["type"] == "idle"
assert calls["n"] == gm_calls_before, "resume must not spend a GM turn"

# ---- corruption guard: a truncated conversation row must not brick the hero
import db as db_mod
with db_mod._conn() as c:
    c.execute("UPDATE conversation SET messages=? WHERE character_id=?",
              ('{"session_id": "x", "hist', cid))
assert db_mod.load_conversation(cid) == [], "corrupt save should fall back"
with client.websocket_connect(f"/ws/{cid}") as ws:
    assert ws.receive_json()["type"] == "state"
    hello = ws.receive_json()
    assert hello["type"] == "hello" and hello["instant"] is False

# ---- armor: only positive bonuses count as damage reduction
aid = db_mod.add_equipment(cid, "Cursed Mail", "armor", "rare",
                           {"con": 2, "dex": -3}, ["Rustbound: it whispers"])["id"]
db_mod.equip_item(cid, aid)
assert db_mod.hero_armor(cid) == 2, f"cursed penalty counted as armor: {db_mod.hero_armor(cid)}"

st3 = client.post(f"/api/heroes/{cid}/lang", json={"lang": "canto"}).json()
assert st3["lang"] == "canto"

# ---- GM settings: read, change model/effort/backend, reject junk
sett = client.get("/api/settings").json()
assert sett["backend"] in ("claude", "gemini")
assert any(b["name"] == "claude" and b["models"] for b in sett["backends"])
assert sett["effort"] in sett["effort_levels"]

sett = client.post("/api/settings",
                   json={"model": "haiku", "effort": "low",
                         "default_lang": "canto"}).json()
claude_cfg = next(b for b in sett["backends"] if b["name"] == "claude")
assert claude_cfg["model"] == "haiku" and sett["effort"] == "low", sett
assert sett["default_lang"] == "canto", sett
boot2 = client.get("/api/bootstrap").json()
assert boot2["model"] == "haiku" and boot2["effort"] == "low", "bootstrap stale"
assert boot2["default_lang"] == "canto", "default lang not in bootstrap"
assert client.post("/api/settings", json={"default_lang": "elvish"}).status_code == 400

assert client.post("/api/settings", json={"backend": "cthulhu"}).status_code == 400
assert client.post("/api/settings", json={"effort": "ultra"}).status_code == 400
assert client.post("/api/settings", json={"model": "x; rm -rf /"}).status_code == 400
# restore defaults so later assertions see the stock config
client.post("/api/settings", json={"model": "sonnet", "effort": "medium",
                                   "default_lang": "en"})

assert client.delete(f"/api/heroes/{cid}").json()["ok"]
assert client.get(f"/api/heroes/{cid}/state").status_code == 404

# ---- icon vocabulary: every scenario menu word must exist in the web map,
# every menu has exactly 50 entries, and the GM's system prompt carries it.
import re

import scenarios

js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "web", "src", "foeIcons.js")).read()
body = js.split("export const FOE_ICON_MAP = {", 1)[1]
body = re.sub(r"//.*", "", body)
js_words = {a or b for a, b in
            re.findall(r'(?:"([\w-]+)"|(?<![\w-])([a-zA-Z][\w-]*))\s*:', body)}
for scen, words in scenarios.FOE_ICONS.items():
    assert len(words) == 50, f"{scen}: {len(words)} icon words, want 50"
    assert len(set(words)) == 50, f"{scen}: duplicate icon words"
    missing = [w for w in words if w not in js_words]
    assert not missing, f"{scen}: not in foeIcons.js: {missing}"

gm2 = GameMaster(client.post("/api/heroes", json={
    "name": "Mo", "scenario": "work", "race": "—", "char_class": "New Hire",
    "lang": "en", "premise": "", "scores": {a: 10 for a in stats["scores"]},
}).json()["id"])
sysprompt = gm2._system()
assert "Enemy icon menu" in sysprompt and "coffee-fiend" in sysprompt

# ---- fd-leak guard: DB connections must close deterministically. Left to
# the GC they pile up and connect() eventually fails with "unable to open
# database file" (macOS caps a process at 256 open files by default).
import gc

gc.collect()
_fds_before = len(os.listdir("/dev/fd"))
for _ in range(100):
    client.get("/api/bootstrap")
_leaked = len(os.listdir("/dev/fd")) - _fds_before
assert _leaked < 20, f"fd leak: {_leaked} new fds after 100 requests"

print("ALL SERVER TESTS PASSED")
