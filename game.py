#!/usr/bin/env python3
"""game.py — Fateweaver: any story, real dice, an AI game master.

Run it:
    python game.py

Create a hero (or load a saved one), then just type what you want to do. The
game master narrates the world, calls for dice rolls, and keeps your stats in
SQLite. In-game commands: /stats  /inventory  /log  /help  /quit
"""

from __future__ import annotations

import os
import sys

import db
import dice
import ui

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"

import scenarios as scen_mod

BANNER = rf"""{YELLOW}
 ╔═╗┌─┐┌┬┐┌─┐╦ ╦┌─┐┌─┐┬  ┬┌─┐┬─┐
 ╠╣ ├─┤ │ ├┤ ║║║├┤ ├─┤└┐┌┘├┤ ├┬┘
 ╚  ┴ ┴ ┴ └─┘╚╩╝└─┘┴ ┴ └┘ └─┘┴└─
{RESET}{DIM}  any story, real dice — an AI game master in your terminal{RESET}
"""

# Constitution modifier feeds starting HP; hit die varies a touch by class flavor.
CLASS_HIT_DIE = {
    "Fighter": 10, "Barbarian": 12, "Ranger": 10, "Cleric": 8,
    "Rogue": 8, "Bard": 8, "Wizard": 6,
}


def ability_mod(score: int) -> int:
    return (score - 10) // 2


def prompt(msg: str) -> str:
    try:
        return input(f"{CYAN}{msg}{RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)


def choose(msg: str, options: list[str]) -> str:
    print(f"\n{msg}")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    while True:
        raw = prompt("Choose a number (or type your own):")
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw:
            return raw


NAME = ui.NAME  # the hero's name — matches the narration highlight


def _stat(char: dict, key: str) -> str:
    mod = ability_mod(char[key])
    color = ui.MOSS if mod > 0 else ui.BLOOD if mod < 0 else DIM
    return f"{DIM}{key.upper()}{RESET} {char[key]:>2} {color}({mod:+d}){RESET}"


def show_sheet(char: dict) -> None:
    inv = db.get_inventory(char["id"])
    inv_str = ", ".join(f"{i['item']} x{i['qty']}" for i in inv) or "(nothing)"
    lang = "廣東話 (繁體中文)" if char.get("lang") == "canto" else "English"
    stats = [_stat(char, k) for k in ("str", "dex", "con", "int", "wis", "cha")]
    print()
    scen = scen_mod.SCENARIOS.get(char.get("scenario") or "tavern",
                                  scen_mod.SCENARIOS["tavern"])
    who = f"{char['race']} {char['class']}" if char["race"] != "—" else char["class"]
    print(ui.rule(f"{char['name']} · lvl {char['level']} {who} · {scen['emoji']} {scen['title']}"))
    print(f"  {DIM}HP{RESET}   {ui.hp_bar(char['hp'], char['max_hp'])}"
          f"     {ui.GOLD}⛁ {char['gold']} gold{RESET}   "
          f"{ui.ARCANE}✦ {char['xp']}/{db.xp_for_next(char['level'])} xp "
          f"({db.xp_for_next(char['level']) - char['xp']} to lvl {char['level'] + 1}){RESET}   "
          f"{ui.GOLD}⚡ {char.get('power_rolls', 0)}{RESET}   "
          f"{ui.ARCANE}↻ {char.get('rerolls', 0)}{RESET}   {DIM}[{lang}]{RESET}")
    print(f"  {'   '.join(stats[:3])}")
    print(f"  {'   '.join(stats[3:])}")
    print(f"  {DIM}Pack{RESET} {inv_str}")
    print(ui.rule())


def create_character() -> int:
    print(f"\n{BOLD}Let's roll up a hero.{RESET}")

    # Pick tonight's story first — it shapes everything else.
    labels = [f"{scen_mod.SCENARIOS[k]['emoji']} {scen_mod.SCENARIOS[k]['title']}"
              f"  {DIM}— {scen_mod.SCENARIOS[k]['tagline']}{RESET}"
              for k in scen_mod.ORDER]
    picked = choose("Pick tonight's story:", labels)
    scenario = scen_mod.ORDER[labels.index(picked)] if picked in labels else "custom"
    scen = scen_mod.SCENARIOS[scenario]

    premise = ""
    if scenario == "custom":
        print(f"\n{DIM}Describe your story in a sentence or two — setting, tone, "
              f"who you are. The GM builds the world around it.{RESET}")
        while not premise:
            premise = prompt("Your premise:")

    name = ""
    while not name:
        name = prompt("What is your character's name?")
    race = choose("Pick a race:", scen["races"]) if scen["races"] else "—"
    char_class = choose("Pick your background:", scen["roles"])
    lang_pick = choose("Story language / 故事語言:",
                       ["English", "廣東話 (繁體中文)"])
    lang = "canto" if "廣東話" in lang_pick or "chin" in lang_pick.lower() else "en"

    # Roll ability scores — reroll the whole line as many times as you like.
    order = ["str", "dex", "con", "int", "wis", "cha"]
    while True:
        print(f"\n{DIM}Rolling ability scores (4d6, drop the lowest)...{RESET}")
        scores = {}
        for ab in order:
            a = dice.roll_ability()
            scores[ab] = a["score"]
            print(f"  {ab.upper()}: {a['score']:>2}   {DIM}({a['detail']}){RESET}")
        if prompt("\nKeep these scores? (Y = keep / n = reroll)").lower() != "n":
            break

    hit_die = CLASS_HIT_DIE.get(char_class, 8)
    max_hp = max(1, hit_die + ability_mod(scores["con"]))
    gold_notation, gold_mult = scen["gold_dice"]
    starting_gold = dice.roll(gold_notation).total * gold_mult

    cid = db.create_character(name, race, char_class, scores, max_hp,
                              gold=starting_gold, lang=lang,
                              scenario=scenario, premise=premise)

    # Scenario starting kit, plus class gear in the fantasy story.
    for item, qty in scen["kit"]:
        db.add_item(cid, item, qty)
    if scenario == "tavern":
        if char_class in ("Fighter", "Barbarian", "Ranger"):
            db.add_item(cid, "Sword", 1)
        elif char_class == "Rogue":
            db.add_item(cid, "Daggers", 2)
        elif char_class in ("Wizard", "Bard"):
            db.add_item(cid, "Spellbook", 1)
        elif char_class == "Cleric":
            db.add_item(cid, "Holy symbol", 1)

    who = f"{name} the {race} {char_class}" if race != "—" else f"{name} the {char_class}"
    print(f"\n{GREEN}{who} is ready — {scen['emoji']} {scen['title']}. "
          f"HP {max_hp}, {starting_gold} gold.{RESET}")
    return cid


def pick_or_create() -> int:
    while True:
        existing = db.list_characters()
        if not existing:
            return create_character()
        print(f"\n{BOLD}Saved heroes:{RESET}")
        for i, c in enumerate(existing, 1):
            sc = scen_mod.SCENARIOS.get(c.get("scenario") or "tavern",
                                        scen_mod.SCENARIOS["tavern"])
            who = f"{c['race']} {c['class']}" if c["race"] != "—" else c["class"]
            print(f"  {i}. {sc['emoji']} {NAME}{c['name']}{RESET} — lvl {c['level']} "
                  f"{who} {DIM}(HP {c['hp']}/{c['max_hp']}){RESET}")
        print(f"  {len(existing) + 1}. + Create a new hero")
        print(f"{DIM}  (type d2 to delete hero 2){RESET}")
        redraw = False
        while not redraw:
            raw = prompt("Choose:").lower().strip()
            if raw.isdigit():
                n = int(raw)
                if 1 <= n <= len(existing):
                    return existing[n - 1]["id"]
                if n == len(existing) + 1:
                    return create_character()
            elif raw.startswith("d") and raw[1:].strip().isdigit():
                n = int(raw[1:].strip())
                if 1 <= n <= len(existing):
                    victim = existing[n - 1]
                    sure = prompt(f"Delete {victim['name']} and their whole story? "
                                  f"This cannot be undone. (y/N)").lower()
                    if sure == "y":
                        db.delete_character(victim["id"])
                        print(f"{RED}{victim['name']}'s tale is struck from the record.{RESET}")
                    redraw = True  # re-list heroes


HELP = f"""
{BOLD}How to play{RESET}
  The GM ends each turn with 3 options. Type {CYAN}1{RESET}, {CYAN}2{RESET} or {CYAN}3{RESET} to pick one —
  options tagged {GREEN}[STR +2]{RESET} etc. roll a d20 with your stat as buff/debuff;
  {DIM}[no roll]{RESET} options just happen. Or ignore the menu and type anything.

{BOLD}Dice tokens{RESET} {DIM}(the GM awards more as story rewards){RESET}
  {YELLOW}⚡ power{RESET}   type {YELLOW}p2{RESET} instead of 2 to add +10 to that roll (start with 1)
  {CYAN}↻ reroll{RESET}  after a failed roll you'll be offered a reroll (start with 3)

{BOLD}Commands{RESET}
  /stats       show your character sheet
  /inventory   show your inventory
  /log         show recent events (rolls, story beats)
  /roll 2d6+1  roll dice yourself, outside the story
  /lang        switch story language (English ↔ 廣東話)
  /backend     switch the AI engine running the GM (claude / gemini)
  /model       show or set the model (/model sonnet) — /effort low..max too
  /help        this help
  /quit        save and exit — pick the same hero later to resume the story
Anything else you type is your action, spoken to the Game Master.
"""


def game_loop(cid: int) -> None:
    from gm import GameMaster, MissingCredentials  # lazy: only needs the SDK here

    char = db.get_character(cid)
    try:
        gm = GameMaster(cid)
    except MissingCredentials as e:
        print(f"{RED}Could not start the Game Master: {e}{RESET}")
        return
    except Exception as e:
        print(f"{RED}Could not start the Game Master: {e}{RESET}")
        return

    resuming = bool(gm.messages)
    show_sheet(char)
    print(HELP)

    if resuming:
        print(f"{DIM}Resuming your adventure...{RESET}")
        opener = ("[The player has returned. Briefly recap where things stood, "
                  "then continue the scene and present the three choice options.]")
    else:
        scen = scen_mod.SCENARIOS.get(char.get("scenario") or "tavern",
                                      scen_mod.SCENARIOS["tavern"])
        who = (f"{char['name']}, a {char['race']} {char['class']},"
               if char["race"] != "—" else f"{char['name']}, {char['class']},")
        opener = f"[Begin the adventure. {who} {scen['opener']}]"

    def gm_turn(text: str = "", choice: int | None = None, power: bool = False) -> None:
        try:
            if choice is not None:
                gm.play_choice(choice, power=power)
            else:
                gm.send(text)
        except RuntimeError as e:
            print(f"\n{RED}The Game Master stumbled: {e}{RESET}")
            print(f"{DIM}Your progress is saved — just try your action again.{RESET}")

    try:
        gm_turn(opener)
        while True:
            char = db.get_character(cid)
            if char["hp"] <= 0:
                print(f"\n{RED}You have fallen. Your tale ends here... "
                      f"unless the story says otherwise.{RESET}")
            action = prompt("\n> ")
            if not action:
                continue
            # Picking a numbered option from the GM's choice menu: the engine
            # rolls d20 + your stat modifier for the tagged trait.
            if action.isdigit() and gm.choices and 1 <= int(action) <= len(gm.choices):
                gm_turn(choice=int(action) - 1)
                continue
            # p2 = pick option 2 with a ⚡ power token (+10 on the roll)
            pm = action.lower().strip()
            if (len(pm) == 2 and pm[0] == "p" and pm[1].isdigit() and gm.choices
                    and 1 <= int(pm[1]) <= len(gm.choices)):
                gm_turn(choice=int(pm[1]) - 1, power=True)
                continue
            cmd = action.lower()
            if cmd in ("/quit", "/exit", "/q"):
                print(f"{DIM}Your progress is saved. Farewell, adventurer.{RESET}")
                break
            if cmd in ("/help", "/h"):
                print(HELP)
                continue
            if cmd in ("/stats", "/sheet"):
                show_sheet(db.get_character(cid))
                continue
            if cmd in ("/inventory", "/inv", "/i"):
                inv = db.get_inventory(cid)
                if inv:
                    for it in inv:
                        print(f"  - {it['item']} x{it['qty']}")
                else:
                    print("  (empty)")
                continue
            if cmd in ("/log", "/journal"):
                for e in db.get_log(cid, limit=20):
                    print(f"  {DIM}[{e['kind']}]{RESET} {e['content'][:200]}")
                continue
            if cmd.startswith("/model") or cmd.startswith("/effort"):
                import gm as gm_mod
                parts = action.split()
                arg = parts[1].lower() if len(parts) > 1 else ""
                if cmd.startswith("/effort"):
                    if arg in gm_mod.EFFORT_LEVELS:
                        if os.environ.get("TAVERN_EFFORT"):
                            print(f"{RED}TAVERN_EFFORT is set in your environment "
                                  f"and overrides this — unset it first.{RESET}")
                        else:
                            db.set_setting("effort", arg)
                            print(f"{GREEN}Effort set to {arg}.{RESET} "
                                  f"{DIM}(applies from the next turn){RESET}")
                        continue
                elif arg:  # /model <name>
                    if os.environ.get("TAVERN_MODEL"):
                        print(f"{RED}TAVERN_MODEL is set in your environment "
                              f"and overrides this — unset it first.{RESET}")
                    else:
                        db.set_setting(f"model:{gm.backend}", arg)
                        print(f"{GREEN}Model for {gm.backend} set to {arg}.{RESET} "
                              f"{DIM}(applies from the next turn){RESET}")
                    continue
                # no/invalid arg → show current setup
                eff = gm_mod.current_effort() or "CLI default (xhigh for Opus in Claude Code)"
                print(f"\n{BOLD}Current GM engine{RESET}")
                print(f"  backend  {GREEN}{gm.backend}{RESET} "
                      f"{DIM}({gm_mod.BACKENDS[gm.backend]['mode']} mode){RESET}")
                print(f"  model    {GREEN}{gm_mod.current_model(gm.backend)}{RESET} "
                      f"{DIM}(suggestions: {', '.join(gm_mod.BACKENDS[gm.backend]['models'])}){RESET}")
                print(f"  effort   {GREEN}{eff}{RESET} {DIM}(claude only){RESET}")
                print(f"{DIM}Switch with: /model sonnet · /effort low · /backend gemini{RESET}")
                continue
            if cmd.startswith("/backend"):
                import gm as gm_mod
                avail = gm_mod.available_backends()
                parts = action.split()
                pick = parts[1].lower() if len(parts) > 1 else ""
                if pick not in avail:
                    cur = gm.backend
                    print(f"\n{BOLD}AI engines{RESET} (current: {GREEN}{cur}{RESET})")
                    for name, ok in avail.items():
                        mode = gm_mod.BACKENDS[name]["mode"]
                        status = f"{GREEN}installed{RESET}" if ok else \
                                 f"{DIM}not found — {gm_mod.BACKENDS[name]['install']}{RESET}"
                        print(f"  {name:<8} {DIM}({mode}){RESET}  {status}")
                    print(f"{DIM}Switch with: /backend gemini{RESET}")
                    continue
                if not avail[pick]:
                    print(f"{RED}`{pick}` isn't installed: "
                          f"{gm_mod.BACKENDS[pick]['install']}{RESET}")
                    continue
                db.set_setting("backend", pick)
                gm = GameMaster(cid)
                print(f"{GREEN}GM now runs on {pick}.{RESET} "
                      f"{DIM}The story continues from the saved transcript.{RESET}")
                continue
            if cmd.startswith("/lang"):
                new_lang = "en" if char.get("lang") == "canto" else "canto"
                db.set_language(cid, new_lang)
                label = "廣東話 (繁體中文)" if new_lang == "canto" else "English"
                print(f"{GREEN}Story language switched to {label}.{RESET}")
                gm_turn(f"[The player switched the story language to "
                        f"{'Cantonese/Traditional Chinese' if new_lang == 'canto' else 'English'}. "
                        f"From now on follow the narration language rules for it. "
                        f"Briefly acknowledge in the new language and continue the scene.]")
                continue
            if cmd.startswith("/roll"):
                parts = action.split(maxsplit=1)
                notation = parts[1] if len(parts) > 1 else "d20"
                try:
                    print(f"  🎲 {dice.roll(notation).detail()}")
                except ValueError as e:
                    print(f"  {RED}{e}{RESET}")
                continue
            if cmd.startswith("/"):
                print(f"{DIM}Unknown command. Try /help.{RESET}")
                continue

            gm_turn(action)
    except KeyboardInterrupt:
        print(f"\n{DIM}Progress saved. Farewell.{RESET}")


def main() -> None:
    import shutil

    db.init_db()
    print(BANNER)
    if shutil.which(os.environ.get("TAVERN_CLAUDE_BIN", "claude")) is None:
        print(f"{DIM}Tip: the Game Master runs on the `claude` CLI (Claude Code), "
              f"which wasn't found on PATH. Install it from "
              f"https://claude.com/claude-code — character creation and dice "
              f"still work without it.{RESET}\n")
    cid = pick_or_create()
    game_loop(cid)


if __name__ == "__main__":
    main()
