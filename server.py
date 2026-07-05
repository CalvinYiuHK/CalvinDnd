"""server.py — Fateweaver web backend.

Wraps the existing terminal engine (gm.py / db.py / dice.py) in a small
FastAPI app so the React frontend in web/ can play the same game:

  REST   /api/...        heroes, creation, state, gear, skills, allocation
  WS     /ws/{hero_id}   live turns — events stream from the SQLite event
                         log while the GM thread runs; reroll offers bridge
                         over the socket as confirm round-trips.

The GM still runs through the `claude` CLI with the persistent cached
session — nothing about the game rules lives here.
"""

from __future__ import annotations

import asyncio
import os
import threading

# The engine renders through ANSI; force color so enemy art keeps its
# palette in the browser (rendered with ansi_up), and skip animations.
os.environ.setdefault("TAVERN_FORCE_COLOR", "1")
os.environ.setdefault("TAVERN_NO_ANIM", "1")

import art
import db
import dice
import scenarios
import gm as gm_mod
from gm import GameMaster, MissingCLI, ability_mod, proficiency_bonus

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
CLASS_HIT_DIE = {
    "Fighter": 10, "Barbarian": 12, "Ranger": 10, "Cleric": 8,
    "Rogue": 8, "Bard": 8, "Wizard": 6,
}

db.init_db()
app = FastAPI(title="Fateweaver")

# ------------------------------------------------------------ confirm bridge
# gm.CONFIRM is a module-level hook; turns run in worker threads, so route
# each thread's confirms to its own session via a thread-local.
_tl = threading.local()


def _confirm_dispatch(prompt: str) -> bool:
    handler = getattr(_tl, "confirm", None)
    return handler(prompt) if handler else False


gm_mod.CONFIRM = _confirm_dispatch

# Demo mode (TAVERN_FAKE_GM=1): a canned GM for screenshots, UI work, and
# offline demos — no `claude` CLI calls, but the real dice/DB still run.
if os.environ.get("TAVERN_FAKE_GM"):
    _FAKE_REPLIES = [
        (
            "The trapdoor groans open and lamplight spills down worn steps. "
            "Below, between racks of dusty casks, **Gnash** the goblin crouches "
            "over a broken lockbox, ears twitching. He has not seen you yet — "
            "but the stair under your boot just creaked.\n"
            "[[enemy: Gnash | level 1 | str 12 dex 14 con 10 int 8 wis 8 cha 6 | "
            "gear: Rusty Cleaver (normal weapon); Patchy Hood (normal armor) | "
            "skills: Frenzy (1d6+STR): a wild flurry of chops]]\n"
            "[[equip: Lucky Pin | rare | trinket | dex+2 | Glint: once a day, "
            "the pin flashes and a missed step goes unnoticed]]\n"
            "[[choice: Rush Gnash before he turns around | STR | DC 12]]\n"
            "[[choice: Slip from cask to cask, closing quietly | DEX* | DC 13]]\n"
            "[[choice: Call out a greeting and offer to talk | none]]"
        ),
        (
            "Wood cracks and dust rains from the beams as the fight erupts!\n"
            "[[damage: enemy | 1d6 | str | Charging blow]]\n"
            "[[sheet: xp=+50 | First blood in the cellar]]\n"
            "[[reward: power x1 | A daring opening move]]\n"
            "[[choice: Press the attack while he reels | STR | DC 12]]\n"
            "[[choice: Kick a cask loose to pin him | DEX | DC 11]]\n"
            "[[choice: Demand his surrender | CHA | DC 10]]"
        ),
        (
            "Gnash spits, snarls, and weighs his chances against you.\n"
            "[[choice: Finish this | STR | DC 12]]\n"
            "[[choice: Circle for an opening | DEX | DC 11]]\n"
            "[[choice: Let him crawl away | none]]"
        ),
    ]
    _fake_n = {"n": 0}

    def _fake_invoke(self, prompt):
        i = min(_fake_n["n"], len(_FAKE_REPLIES) - 1)
        _fake_n["n"] += 1
        return _FAKE_REPLIES[i]

    GameMaster._invoke = _fake_invoke


# ------------------------------------------------------------------ helpers
def _events_after(character_id: int, after_id: int, limit: int = 200) -> list[dict]:
    with db._conn() as c:
        rows = c.execute(
            "SELECT id, kind, content, created_at FROM event_log "
            "WHERE character_id=? AND id>? ORDER BY id ASC LIMIT ?",
            (character_id, after_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _last_event_id(character_id: int) -> int:
    with db._conn() as c:
        row = c.execute(
            "SELECT COALESCE(MAX(id), 0) AS m FROM event_log WHERE character_id=?",
            (character_id,),
        ).fetchone()
    return row["m"]


def _recent_events(character_id: int, limit: int = 300) -> list[dict]:
    with db._conn() as c:
        rows = c.execute(
            "SELECT id, kind, content, created_at FROM event_log "
            "WHERE character_id=? ORDER BY id DESC LIMIT ?",
            (character_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def _has_inspect(character_id: int) -> bool:
    words = ("inspect", "insight", "appraise", "analyz", "scan", "鑑定", "洞察")
    for sk in db.list_skills(character_id):
        text = (sk["name"] + " " + sk["descr"]).lower()
        if any(w in text for w in words):
            return True
    for e in db.list_equipment(character_id):
        if e["equipped"] and any(w in " ".join(e["abilities"]).lower() for w in words):
            return True
    return False


def enemy_public(char: dict, enemy: dict, inspect: bool) -> dict:
    """The tiered enemy view (mirrors gm.enemy_view) as structured data."""
    diff = char["level"] - enemy["level"]
    tier = ("full" if diff >= 0 or inspect else
            "partial" if diff == -1 else
            "vague" if diff == -2 else "silhouette")
    out = {
        "id": enemy["id"],
        "name": enemy["name"],
        "tier": tier,
        "hp_pct": round(100 * enemy["hp"] / max(1, enemy["max_hp"])),
        "defeated": enemy["hp"] == 0,
        "art": art.art_for(enemy["name"]),
    }
    if tier in ("full", "partial"):
        out["hp"] = enemy["hp"]
        out["max_hp"] = enemy["max_hp"]
    if tier != "silhouette":
        out["level"] = enemy["level"]
    if tier == "full":
        out["attrs"] = enemy["attrs"]
        out["armor"] = enemy["armor"]
        out["gear"] = enemy["gear"]
        out["skills"] = enemy["skills"]
    elif tier == "partial":
        top = sorted(enemy["attrs"], key=lambda a: -enemy["attrs"][a])[:2]
        out["attrs"] = {a: enemy["attrs"][a] for a in top}
        out["gear"] = [g.split("(")[0].strip() for g in enemy["gear"]]
    elif tier == "vague":
        top = max(enemy["attrs"], key=lambda a: enemy["attrs"][a])
        out["hint"] = top
    return out


def state_payload(character_id: int) -> dict:
    char = db.get_character(character_id)
    if char is None:
        raise HTTPException(404, "no such hero")
    bonuses = db.equipment_bonuses(character_id)
    stats = {}
    for a in ABILITIES:
        eff = char[a] + bonuses.get(a, 0)
        stats[a] = {"base": char[a], "gear": bonuses.get(a, 0),
                    "score": eff, "mod": ability_mod(eff)}
    skills = []
    for sk in db.list_skills(character_id):
        mod = sum(ability_mod(char[a] + bonuses.get(a, 0)) for a in sk["attrs"])
        skills.append({**sk, "mod": mod})
    inspect = _has_inspect(character_id)
    return {
        "id": char["id"],
        "name": char["name"],
        "race": char["race"],
        "class": char["class"],
        "level": char["level"],
        "hp": char["hp"],
        "max_hp": char["max_hp"],
        "gold": char["gold"],
        "xp": char["xp"],
        "xp_next": db.xp_for_next(char["level"]),
        "lang": char.get("lang") or "en",
        "scenario": char.get("scenario") or "tavern",
        "stats": stats,
        "proficiency": proficiency_bonus(char["level"]),
        "armor": db.hero_armor(character_id),
        "rerolls": char.get("rerolls", 0),
        "power_rolls": char.get("power_rolls", 0),
        "attr_points": char.get("attr_points", 0),
        "stat_cap": db.STAT_CAP,
        "inventory": db.get_inventory(character_id),
        "equipment": db.list_equipment(character_id),
        "skills": skills,
        "max_skill_slots": db.max_skill_slots(char["level"]),
        "enemies": [enemy_public(char, e, inspect)
                    for e in db.list_enemies(character_id)],
    }


def choices_payload(gmi: GameMaster) -> list[dict]:
    char = db.get_character(gmi.character_id)
    out = []
    for text, trait, prof, dc, assumed in gmi.choices:
        if trait == "none":
            out.append({"text": text, "trait": None})
            continue
        mod = gmi._check_mod(char, trait, prof)
        out.append({
            "text": text, "trait": trait, "prof": prof, "dc": dc,
            "assumed": assumed, "mod": mod,
            "need": max(2, min(20, dc - mod)),
        })
    return out


# --------------------------------------------------------------------- REST
@app.get("/api/bootstrap")
def bootstrap():
    scens = []
    for key in scenarios.ORDER:
        s = scenarios.SCENARIOS[key]
        scens.append({"key": key, "title": s["title"], "tagline": s["tagline"],
                      "emoji": s["emoji"], "races": s["races"], "roles": s["roles"]})
    heroes = []
    for c in db.list_characters():
        heroes.append({
            "id": c["id"], "name": c["name"], "race": c["race"],
            "class": c["class"], "level": c["level"], "hp": c["hp"],
            "max_hp": c["max_hp"], "scenario": c.get("scenario") or "tavern",
            "lang": c.get("lang") or "en",
        })
    return {"scenarios": scens, "heroes": heroes,
            "backend": gm_mod.current_backend(),
            "model": gm_mod.current_model(),
            "effort": gm_mod.current_effort()}


@app.post("/api/roll-stats")
def roll_stats():
    rolls = {a: dice.roll_ability() for a in ABILITIES}
    return {"scores": {a: r["score"] for a, r in rolls.items()},
            "details": {a: r["detail"] for a, r in rolls.items()}}


class NewHero(BaseModel):
    name: str
    scenario: str = "tavern"
    race: str = "—"
    char_class: str = "Protagonist"
    lang: str = "en"
    premise: str = ""
    scores: dict[str, int]


@app.post("/api/heroes")
def create_hero(body: NewHero):
    if body.scenario not in scenarios.SCENARIOS:
        raise HTTPException(400, "unknown scenario")
    if not body.name.strip():
        raise HTTPException(400, "name required")
    scores = {a: int(body.scores.get(a, 10)) for a in ABILITIES}
    scen = scenarios.SCENARIOS[body.scenario]
    hit_die = CLASS_HIT_DIE.get(body.char_class, 8)
    max_hp = max(1, hit_die + ability_mod(scores["con"]))
    gold_notation, gold_mult = scen["gold_dice"]
    gold = dice.roll(gold_notation).total * gold_mult
    cid = db.create_character(body.name.strip(), body.race, body.char_class,
                              scores, max_hp, gold=gold, lang=body.lang,
                              scenario=body.scenario, premise=body.premise)
    for item, qty in scen["kit"]:
        db.add_item(cid, item, qty)
    if body.scenario == "tavern":
        gear = {"Fighter": ("Sword", 1), "Barbarian": ("Sword", 1),
                "Ranger": ("Sword", 1), "Rogue": ("Daggers", 2),
                "Wizard": ("Spellbook", 1), "Bard": ("Spellbook", 1),
                "Cleric": ("Holy symbol", 1)}.get(body.char_class)
        if gear:
            db.add_item(cid, *gear)
    return {"id": cid}


@app.delete("/api/heroes/{cid}")
def delete_hero(cid: int):
    if db.get_character(cid) is None:
        raise HTTPException(404, "no such hero")
    db.delete_character(cid)
    return {"ok": True}


@app.get("/api/heroes/{cid}/state")
def hero_state(cid: int):
    return state_payload(cid)


@app.get("/api/heroes/{cid}/log")
def hero_log(cid: int, limit: int = 300):
    if db.get_character(cid) is None:
        raise HTTPException(404, "no such hero")
    return {"events": _recent_events(cid, limit)}


class EquipBody(BaseModel):
    equipment_id: int


@app.post("/api/heroes/{cid}/equip")
def equip(cid: int, body: EquipBody):
    if db.equip_item(cid, body.equipment_id) is None:
        raise HTTPException(404, "no such item")
    return state_payload(cid)


class ForgetBody(BaseModel):
    skill_id: int


@app.post("/api/heroes/{cid}/forget")
def forget(cid: int, body: ForgetBody):
    if not db.remove_skill(cid, body.skill_id):
        raise HTTPException(404, "no such skill")
    return state_payload(cid)


class AllocateBody(BaseModel):
    allocation: dict[str, int]


@app.post("/api/heroes/{cid}/allocate")
def allocate(cid: int, body: AllocateBody):
    alloc = {a: int(v) for a, v in body.allocation.items()
             if a in ABILITIES and int(v) > 0}
    char = db.get_character(cid)
    if char is None:
        raise HTTPException(404, "no such hero")
    if sum(alloc.values()) > char.get("attr_points", 0):
        raise HTTPException(400, "not enough attribute points")
    db.spend_attr_points(cid, alloc)
    return state_payload(cid)


class LangBody(BaseModel):
    lang: str


@app.post("/api/heroes/{cid}/lang")
def set_lang(cid: int, body: LangBody):
    if body.lang not in ("en", "canto"):
        raise HTTPException(400, "lang must be en or canto")
    db.set_language(cid, body.lang)
    return state_payload(cid)


# ---------------------------------------------------------------- WebSocket
class Session:
    """One live hero connection: a GameMaster plus the confirm bridge."""

    def __init__(self, ws: WebSocket, gmi: GameMaster,
                 loop: asyncio.AbstractEventLoop):
        self.ws = ws
        self.gm = gmi
        self.loop = loop
        self.busy = False
        self.confirm_future: asyncio.Future | None = None

    # Runs in the GM worker thread (via gm.CONFIRM).
    def confirm_sync(self, prompt: str) -> bool:
        fut = asyncio.run_coroutine_threadsafe(self._ask(prompt), self.loop)
        try:
            return fut.result(timeout=180)
        except Exception:
            return False

    async def _ask(self, prompt: str) -> bool:
        self.confirm_future = self.loop.create_future()
        await self.ws.send_json({"type": "confirm", "prompt": prompt})
        try:
            return await asyncio.wait_for(self.confirm_future, timeout=170)
        except asyncio.TimeoutError:
            return False
        finally:
            self.confirm_future = None

    def answer(self, value: bool) -> None:
        if self.confirm_future and not self.confirm_future.done():
            self.confirm_future.set_result(bool(value))


async def _push_events(sess: Session, after_id: int) -> int:
    events = _events_after(sess.gm.character_id, after_id)
    for e in events:
        await sess.ws.send_json({"type": "event", **e})
        after_id = e["id"]
    return after_id


async def _run_turn(sess: Session, fn) -> None:
    cid = sess.gm.character_id
    sess.busy = True
    await sess.ws.send_json({"type": "busy"})
    last_id = _last_event_id(cid)
    stop = asyncio.Event()

    async def pump():
        nonlocal last_id
        while not stop.is_set():
            last_id = await _push_events(sess, last_id)
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.4)
            except asyncio.TimeoutError:
                pass

    def worker():
        _tl.confirm = sess.confirm_sync
        try:
            fn()
        finally:
            _tl.confirm = None

    pump_task = asyncio.create_task(pump())
    error = None
    try:
        await asyncio.to_thread(worker)
    except (RuntimeError, MissingCLI) as e:
        error = str(e)
    finally:
        stop.set()
        await pump_task
        await _push_events(sess, last_id)
    if error:
        await sess.ws.send_json({"type": "error", "message": error})
    await sess.ws.send_json({"type": "choices", "choices": choices_payload(sess.gm)})
    await sess.ws.send_json({"type": "state", "state": state_payload(cid)})
    char = db.get_character(cid)
    if char.get("attr_points", 0) > 0:
        await sess.ws.send_json({"type": "levelup",
                                 "points": char["attr_points"]})
    sess.busy = False
    await sess.ws.send_json({"type": "idle"})


def _opener(gmi: GameMaster) -> str:
    if gmi.messages:
        return ("[The player has returned. Briefly recap where things stood, "
                "then continue the scene and present the three choice options.]")
    char = db.get_character(gmi.character_id)
    scen = scenarios.SCENARIOS.get(char.get("scenario") or "tavern",
                                   scenarios.SCENARIOS["tavern"])
    who = (f"{char['name']}, a {char['race']} {char['class']},"
           if char["race"] != "—" else f"{char['name']}, {char['class']},")
    return f"[Begin the adventure. {who} {scen['opener']}]"


@app.websocket("/ws/{cid}")
async def ws_game(ws: WebSocket, cid: int):
    await ws.accept()
    if db.get_character(cid) is None:
        await ws.send_json({"type": "error", "message": "no such hero"})
        await ws.close()
        return
    try:
        gmi = GameMaster(cid)
    except MissingCLI as e:
        await ws.send_json({"type": "error", "message": str(e)})
        await ws.close()
        return

    sess = Session(ws, gmi, asyncio.get_running_loop())
    await ws.send_json({"type": "state", "state": state_payload(cid)})
    await ws.send_json({"type": "hello", "resuming": bool(gmi.messages)})

    turn_task: asyncio.Task | None = None
    try:
        while True:
            msg = await ws.receive_json()
            kind = msg.get("type")
            if kind == "confirm":
                sess.answer(msg.get("answer", False))
                continue
            if sess.busy:
                await ws.send_json({"type": "error",
                                    "message": "the GM is still narrating"})
                continue
            if kind == "start":
                opener = _opener(gmi)
                turn_task = asyncio.create_task(
                    _run_turn(sess, lambda o=opener: gmi.send(o)))
            elif kind == "say":
                text = (msg.get("text") or "").strip()
                if text:
                    turn_task = asyncio.create_task(
                        _run_turn(sess, lambda t=text: gmi.send(t)))
            elif kind == "choice":
                i = int(msg.get("index", -1))
                power = bool(msg.get("power"))
                if 0 <= i < len(gmi.choices):
                    turn_task = asyncio.create_task(_run_turn(
                        sess, lambda i=i, p=power: gmi.play_choice(i, power=p)))
            elif kind == "skill":
                i = int(msg.get("index", -1))
                if 0 <= i < len(db.list_skills(cid)):
                    turn_task = asyncio.create_task(
                        _run_turn(sess, lambda i=i: gmi.use_skill(i)))
    except WebSocketDisconnect:
        pass
    finally:
        sess.answer(False)
        if turn_task:
            turn_task.cancel()


# Serve the built frontend (web/dist) when it exists; API routes above win.
_dist = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="app")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
