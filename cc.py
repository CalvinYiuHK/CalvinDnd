#!/usr/bin/env python3
"""cc.py — Fateweaver CC mode: a headless engine for Claude-chat play.

This flips the architecture for playing inside a Claude chat (phone app /
claude.ai) with sandboxed code execution: **the Claude you're chatting with is
the Game Master**, and this script is its dice tower and character database.
Claude narrates the story in chat; every mechanical fact — rolls, DCs, HP,
gold, tokens, inventory — comes from running this script, so the numbers stay
real even though the narrator is an LLM.

Every command prints a single JSON object. See CC_MODE.md for the GM playbook.

Usage:
    python3 cc.py new "Wren" --scenario school --role "Transfer Student"
    python3 cc.py state
    python3 cc.py check dex 13 --prof            # d20 + DEX mod + proficiency vs DC 13
    python3 cc.py check str 15 --power           # spend ⚡ +10
    python3 cc.py check str 15 --reroll          # spend ↻ and roll again
    python3 cc.py roll 2d6+1 --reason "Dagger damage"
    python3 cc.py sheet --hp -3 --xp 10 --reason "Trap shard"
    python3 cc.py item add "Silver Key"
    python3 cc.py reward power --reason "Old Greg's lucky coin"
    python3 cc.py log --limit 10
    python3 cc.py heroes
"""

from __future__ import annotations

import argparse
import json
import sys

import db
import dice
import scenarios

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")


def ability_mod(score: int) -> int:
    return (score - 10) // 2


def proficiency_bonus(level: int) -> int:
    return 2 + max(0, level - 1) // 4


def _latest_id() -> int | None:
    chars = db.list_characters()
    return chars[0]["id"] if chars else None


def _target(args) -> int:
    cid = getattr(args, "id", None) or _latest_id()
    if cid is None or db.get_character(cid) is None:
        _fail("no character found — create one with: cc.py new NAME")
    return cid


def _fail(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def _out(payload: dict) -> None:
    payload.setdefault("ok", True)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _state(cid: int) -> dict:
    c = db.get_character(cid)
    return {
        "id": c["id"], "name": c["name"], "race": c["race"], "class": c["class"],
        "level": c["level"], "hp": c["hp"], "max_hp": c["max_hp"],
        "gold": c["gold"], "xp": c["xp"],
        "abilities": {a: {"score": c[a], "mod": ability_mod(c[a])} for a in ABILITIES},
        "proficiency_bonus": proficiency_bonus(c["level"]),
        "tokens": {"rerolls": c.get("rerolls", 0), "power": c.get("power_rolls", 0)},
        "scenario": c.get("scenario", "tavern"),
        "premise": c.get("premise", ""),
        "lang": c.get("lang", "en"),
        "inventory": db.get_inventory(cid),
        "alive": c["hp"] > 0,
    }


def cmd_new(args) -> None:
    scen = scenarios.SCENARIOS.get(args.scenario)
    if scen is None:
        _fail(f"unknown scenario {args.scenario!r} — one of {list(scenarios.ORDER)}")
    scores = {a: dice.roll_ability()["score"] for a in ABILITIES}
    max_hp = max(1, 8 + ability_mod(scores["con"]))
    g_not, g_mult = scen["gold_dice"]
    gold = dice.roll(g_not).total * g_mult
    role = args.role or scen["roles"][0]
    race = args.race or (scen["races"][0] if scen["races"] else "—")
    cid = db.create_character(args.name, race, role, scores, max_hp, gold=gold,
                              lang=args.lang, scenario=args.scenario,
                              premise=args.premise or "")
    for item, qty in scen["kit"]:
        db.add_item(cid, item, qty)
    db.log_event(cid, "system", f"Character created in scenario {args.scenario}")
    _out({"created": True, "state": _state(cid),
          "scenario_premise": args.premise or scen["premise"],
          "opener": f"{args.name}, {role}, {scen['opener']}"})


def cmd_state(args) -> None:
    _out({"state": _state(_target(args))})


def cmd_heroes(args) -> None:
    _out({"heroes": [{"id": c["id"], "name": c["name"], "class": c["class"],
                      "level": c["level"], "hp": f"{c['hp']}/{c['max_hp']}",
                      "scenario": c.get("scenario", "tavern")}
                     for c in db.list_characters()]})


def cmd_check(args) -> None:
    cid = _target(args)
    c = db.get_character(cid)
    trait = args.trait.lower()
    if trait not in ABILITIES:
        _fail(f"trait must be one of {ABILITIES}")
    mod = ability_mod(c[trait])
    parts = [f"{trait.upper()} {ability_mod(c[trait]):+d}"]
    if args.prof:
        mod += proficiency_bonus(c["level"])
        parts.append(f"proficiency +{proficiency_bonus(c['level'])}")

    tokens_note = []
    if args.power:
        if c.get("power_rolls", 0) < 1:
            _fail("no power tokens left")
        c = db.adjust_resources(cid, power_rolls=-1)
        mod += 10
        parts.append("POWER +10")
        tokens_note.append("power token spent")
    if args.reroll:
        if c.get("rerolls", 0) < 1:
            _fail("no reroll tokens left")
        c = db.adjust_resources(cid, rerolls=-1)
        tokens_note.append("reroll token spent — this result replaces the previous roll")

    notation = f"d20{mod:+d}" if mod else "d20"
    result = dice.roll(notation, advantage=args.advantage,
                       disadvantage=args.disadvantage)
    g0 = result.groups[0]
    nat = g0.kept[0] if len(g0.kept) == 1 else None
    dc = args.dc
    success = (nat == 20) or (nat != 1 and result.total >= dc)
    crit = nat == 20
    fumble = nat == 1
    db.log_event(cid, "roll",
                 f"{args.reason or trait.upper() + ' check'} vs DC {dc}: "
                 f"{result.detail()} → {'SUCCESS' if success else 'FAILURE'}")
    c = db.get_character(cid)
    _out({
        "check": args.reason or f"{trait.upper()} check",
        "formula": f"{notation} ({', '.join(parts)})",
        "dc": dc, "need_on_d20": max(2, min(20, dc - mod)),
        "d20_showed": nat, "rolls": g0.rolls, "modifier": mod,
        "total": result.total, "detail": result.detail(),
        "success": success, "critical_success": crit, "critical_failure": fumble,
        "margin": result.total - dc,
        "tokens": {"rerolls": c.get("rerolls", 0), "power": c.get("power_rolls", 0)},
        "notes": tokens_note,
        "reroll_available": (not success) and c.get("rerolls", 0) > 0,
    })


def cmd_roll(args) -> None:
    cid = _target(args)
    try:
        result = dice.roll(args.notation)
    except ValueError as e:
        _fail(str(e))
    db.log_event(cid, "roll", f"{args.reason or args.notation}: {result.detail()}")
    _out({"roll": args.reason or args.notation, "notation": args.notation,
          "detail": result.detail(), "total": result.total,
          "crit": result.crit, "fumble": result.fumble})


def cmd_sheet(args) -> None:
    cid = _target(args)
    char = db.adjust_character(cid, hp=args.hp, gold=args.gold, xp=args.xp,
                               level=args.level, max_hp=args.max_hp)
    db.log_event(cid, "sheet",
                 f"{args.reason or 'sheet change'} → HP {char['hp']}/{char['max_hp']}, "
                 f"Gold {char['gold']}, XP {char['xp']}, Lvl {char['level']}")
    _out({"applied": {"hp": args.hp, "gold": args.gold, "xp": args.xp,
                      "level": args.level, "max_hp": args.max_hp},
          "state": _state(cid)})


def cmd_item(args) -> None:
    cid = _target(args)
    if args.action == "add":
        inv = db.add_item(cid, args.name, args.qty)
    else:
        inv = db.remove_item(cid, args.name, args.qty)
    db.log_event(cid, "inventory", f"{args.action} {args.name} x{args.qty}")
    _out({"inventory": inv})


def cmd_reward(args) -> None:
    cid = _target(args)
    char = db.adjust_resources(cid,
                               rerolls=args.qty if args.kind == "reroll" else 0,
                               power_rolls=args.qty if args.kind == "power" else 0)
    db.log_event(cid, "reward", f"{args.reason or 'story reward'}: {args.kind} +{args.qty}")
    _out({"granted": {args.kind: args.qty},
          "tokens": {"rerolls": char.get("rerolls", 0), "power": char.get("power_rolls", 0)}})


def cmd_log(args) -> None:
    cid = _target(args)
    _out({"log": db.get_log(cid, limit=args.limit)})


def main() -> None:
    ap = argparse.ArgumentParser(description="Fateweaver headless engine (CC mode)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="create a character (ability scores auto-rolled)")
    p.add_argument("name")
    p.add_argument("--scenario", default="tavern", choices=list(scenarios.ORDER))
    p.add_argument("--role", default="")
    p.add_argument("--race", default="")
    p.add_argument("--lang", default="en", choices=["en", "canto"])
    p.add_argument("--premise", default="", help="custom scenario premise")
    p.set_defaults(fn=cmd_new)

    for name, fn in (("state", cmd_state), ("heroes", cmd_heroes)):
        p = sub.add_parser(name)
        p.add_argument("--id", type=int)
        p.set_defaults(fn=fn)

    p = sub.add_parser("check", help="d20 ability check vs DC")
    p.add_argument("trait", help="str|dex|con|int|wis|cha")
    p.add_argument("dc", type=int)
    p.add_argument("--prof", action="store_true", help="add proficiency bonus")
    p.add_argument("--power", action="store_true", help="spend ⚡ power token: +10")
    p.add_argument("--reroll", action="store_true", help="spend ↻ reroll token")
    p.add_argument("--advantage", action="store_true")
    p.add_argument("--disadvantage", action="store_true")
    p.add_argument("--reason", default="")
    p.add_argument("--id", type=int)
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("roll", help="raw dice roll (damage, etc.)")
    p.add_argument("notation")
    p.add_argument("--reason", default="")
    p.add_argument("--id", type=int)
    p.set_defaults(fn=cmd_roll)

    p = sub.add_parser("sheet", help="apply HP/gold/XP deltas, level-ups")
    p.add_argument("--hp", type=int, default=0)
    p.add_argument("--gold", type=int, default=0)
    p.add_argument("--xp", type=int, default=0)
    p.add_argument("--level", type=int)
    p.add_argument("--max-hp", dest="max_hp", type=int)
    p.add_argument("--reason", default="")
    p.add_argument("--id", type=int)
    p.set_defaults(fn=cmd_sheet)

    p = sub.add_parser("item", help="inventory changes")
    p.add_argument("action", choices=["add", "remove"])
    p.add_argument("name")
    p.add_argument("--qty", type=int, default=1)
    p.add_argument("--id", type=int)
    p.set_defaults(fn=cmd_item)

    p = sub.add_parser("reward", help="grant dice tokens as story rewards")
    p.add_argument("kind", choices=["reroll", "power"])
    p.add_argument("--qty", type=int, default=1)
    p.add_argument("--reason", default="")
    p.add_argument("--id", type=int)
    p.set_defaults(fn=cmd_reward)

    p = sub.add_parser("log", help="recent events")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--id", type=int)
    p.set_defaults(fn=cmd_log)

    args = ap.parse_args()
    db.init_db()
    args.fn(args)


if __name__ == "__main__":
    main()
