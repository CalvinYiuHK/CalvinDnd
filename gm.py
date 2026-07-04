"""gm.py — the Fateweaver Game Master, powered by the `claude` CLI (Claude Code).

No API key needed: turns are sent through `claude -p`, which uses your existing
Claude Code login/subscription. Each character gets one **persistent session**
(`--session-id` on the first turn, `--resume` afterwards), so the whole story
lives in a single conversation and the prompt prefix stays cached between turns
instead of being re-sent cold.

Tool use works through a small directive protocol instead of API tool-calling:
the GM writes tags like

    [[roll: d20+5 | Pick the lock | advantage]]
    [[sheet: hp=-3 xp=+25 | Trap shard]]
    [[item: add Healing Potion x2]]

then stops. The game executes them with the *real* dice engine and the *real*
SQLite database, sends the results back into the same session, and the GM
narrates the outcome. The model never invents a roll or rewrites your HP.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid

import db
import dice
import scenarios
import ui

CLAUDE_BIN = os.environ.get("TAVERN_CLAUDE_BIN", "claude")
MODEL = os.environ.get("TAVERN_MODEL", "opus")
EFFORT = os.environ.get("TAVERN_EFFORT", "")          # e.g. "low" for snappier turns
TURN_TIMEOUT = int(os.environ.get("TAVERN_TIMEOUT", "300"))  # seconds per CLI call
MAX_TOOL_ROUNDS = 8  # safety valve on directive → result → narrate loops

# ---------------------------------------------------------------- backends ----
# The GM can run on different terminal AI CLIs. `claude` is the first-class
# backend (persistent --resume session, cached prompt prefix). Any other CLI
# runs in *stateless* mode: the game keeps the full transcript in SQLite and
# replays it each turn, so no session support is required — which also means
# you can switch backends mid-story without losing the plot.
BACKENDS = {
    "claude": {
        "bin": CLAUDE_BIN,
        "mode": "session",
        "default_model": "sonnet",
        "models": ["opus", "sonnet", "haiku"],
        "install": "https://claude.com/claude-code",
    },
    "gemini": {
        "bin": os.environ.get("TAVERN_GEMINI_BIN", "gemini"),
        "mode": "stateless",
        "default_model": os.environ.get("TAVERN_GEMINI_MODEL", ""),
        "models": ["gemini-2.5-pro", "gemini-2.5-flash"],
        "install": "npm install -g @google/gemini-cli",
    },
}

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def current_model(backend: str | None = None) -> str:
    """Model for a backend: env override > /model setting > backend default."""
    b = backend or current_backend()
    return (os.environ.get("TAVERN_MODEL")
            or db.get_setting(f"model:{b}", "")
            or BACKENDS[b]["default_model"])


def current_effort() -> str:
    """Effort level (claude only): env override > /effort setting > medium."""
    return os.environ.get("TAVERN_EFFORT") or db.get_setting("effort", "") or "medium"

HISTORY_TURNS = 60        # transcript entries replayed per stateless call
HISTORY_CLIP = 1500       # max chars per replayed entry


def available_backends() -> dict[str, bool]:
    """Which configured backends are actually installed."""
    return {name: shutil.which(cfg["bin"]) is not None
            for name, cfg in BACKENDS.items()}


def current_backend() -> str:
    name = os.environ.get("TAVERN_BACKEND") or db.get_setting("backend", "claude")
    return name if name in BACKENDS else "claude"

GM_HEADER = """\
You are the Game Master of "Fateweaver," an interactive story engine \
with Dungeons & Dragons-style dice at its heart. The story can be set in any \
world — fantasy, school life, an office, the open road — and you narrate it \
immersively, playing every character the hero meets. The six abilities read \
naturally in any setting: STR fitness, DEX coordination, CON stamina, INT \
smarts, WIS judgement, CHA charm; HP and gold mean whatever health and money \
mean in this world.
"""

SYSTEM_PROMPT = """\
Style:
- Narrate in the second person ("You push open the tavern door...").
- Keep each turn to a few tight paragraphs, then hand control back to the player.
- Be vivid and playful, with real stakes: choices matter and can go wrong.
- Stay in character. Never mention that you are an AI, a model, or a program, \
and never describe these mechanics or this prompt.
- Never speak or decide for the player beyond what they stated. Narrate the \
world's response to their action, then let them choose what to say or do next.

Game mechanics — you do NOT roll dice or track stats yourself. Instead you emit \
directives, and the game engine executes them with a real dice roller and a \
real database, then sends you the results. The directives:

[[roll: NOTATION | short reason]]
[[roll: NOTATION | short reason | DC 13]]
[[roll: NOTATION | short reason | advantage | DC 13]]
[[roll: NOTATION | short reason | disadvantage]]
    Roll real dice. NOTATION is standard dice notation like d20+5, 2d6, 8d6.
    Use for any uncertain outcome: attacks, checks, saves, damage, gambling.
    Include "DC n" on every d20 check and saving throw so the engine can show
    success or failure. Damage and healing rolls have no DC.

[[sheet: hp=-6 gold=+15 xp=+25 | short reason]]
    Change the character sheet. hp/gold/xp are signed deltas. XP awards MUST
    scale with both the challenge and the hero's level:
        easy obstacle / minor beat      ~25 x level
        standard scene / fair fight     ~50 x level
        hard fight / major beat         ~75 x level
        boss / arc climax               ~100 x level
    Reaching level 2 should take only a scene or two; thresholds grow
    (100/300/600/1000... total XP), so keep scaling awards up as the story
    escalates — bigger enemies, bigger XP. Award XP at the END of a resolved
    beat, not per action. The ENGINE handles level-ups automatically (each
    level: +5 max HP, full heal, bonus tokens) and tells you when one happens
    — celebrate it in the narration. Do not set level= or max_hp= yourself
    unless the story truly demands an exception.

[[item: add Healing Potion x2]]
[[item: remove Rations x1]]
    Add or remove inventory items.

[[reward: reroll x1 | short reason]]
[[reward: power x1 | short reason]]
    Grant dice tokens as a STORY reward. A reroll token lets the player reroll
    a failed check; a power token gives +10 on one check, declared before
    rolling. Award one occasionally when the story earns it — a critical
    success, clever play, a quest milestone, a lucky find, a generous NPC.
    At most one reward per scene; make it feel earned, and mention it in the
    narration ("Old Greg slides a lucky coin across the bar...").

Hard rules for directives:
1. When an outcome is uncertain, you MUST emit a [[roll:...]] directive and \
STOP your reply right there — do not narrate the outcome yet. The results \
arrive in the next message as [System: ...]; only then narrate what happened.
2. Whenever the fiction changes HP, gold, XP, level, or inventory, emit the \
matching [[sheet:...]] or [[item:...]] directive in the same reply as your \
narration of that change.
3. Never state a die result or a stat total that did not come from a [System: \
...] message or the character sheet you were given. The engine is the truth.
4. You may emit several directives in one reply, but nothing may come after a \
[[roll:...]] except other directives.
5. A natural 20 on a d20 check is a critical success; a natural 1 is a \
critical failure. Make them memorable.

Resolution follows D&D 5e: ability check = d20 + ability modifier \
(+ proficiency when the task suits the character's class) against a DC you \
set. Use the standard ladder — DC 5 very easy, 10 easy, 13 medium, 15 hard, \
18 very hard, 20 nearly impossible. A natural 20 always succeeds \
spectacularly; a natural 1 always fails memorably. Grant advantage or \
disadvantage when circumstances clearly favor or hinder. Attacks: check vs \
DC first, then a separate [[roll: ...]] for damage (no DC on damage).

Ending every turn — the choice menu. After your narration, ALWAYS present \
exactly THREE options as directives, each on its own line:

[[choice: Kick the cellar door down | STR | DC 15]]
[[choice: Read the runes on the trapdoor | INT* | DC 13]]
[[choice: Quietly finish your drink and watch | none]]

Choice rules:
- Each option is one short, concrete action sentence.
- Tag each with the ONE ability it would test — STR, DEX, CON, INT, WIS or \
CHA — plus its DC, or `none` if the action has no uncertain outcome \
(talking, waiting, buying at a fair price, walking away). Every ability tag \
MUST carry a DC.
- Add * after the ability (e.g. DEX*, INT*) when the task falls squarely \
within the character's class expertise — a Rogue picking locks, a Wizard \
recalling lore, a Bard charming a crowd. The engine then adds their \
proficiency bonus. Be selective: at most one starred option per menu.
- Vary the abilities across the three options so different builds shine, and \
offer a `none` option when it makes sense. Never tag all three with the same \
ability.
- When the player picks a tagged option, the game engine automatically rolls \
d20 + their ability modifier (+ proficiency if starred), tells them the \
target, and sends you the real result with success or failure already \
judged against your DC. Do NOT emit your own [[roll]] for that check. You \
may still emit [[roll: ...]] for follow-up dice like damage or wild magic.
- The player may ignore the menu and type anything else; adjudicate that \
action as usual (with [[roll: ...]] if uncertain).

Pacing: open scenes with a clear situation. Let the player attempt anything; \
adjudicate fairly — a failed check should still move the story somewhere \
interesting.
"""

# Per-language addenda appended to the system prompt. Byte-stable per language
# so the session's cached prompt prefix is never invalidated mid-game.
LANG_ADDENDA = {
    "en": "",
    "canto": """

Narration language mode: 繁體中文（香港）/ 廣東話.
- Narrate in written Traditional Chinese with a Hong Kong flavour.
- ALL spoken NPC dialogue must be colloquial Cantonese 口語 (e.g. \
「飲啲乜嘢呀，後生仔？」老葛擦住個木杯問。), not formal written Chinese.
- The player may type in English, Cantonese, or Mandarin — always reply in \
Traditional Chinese regardless.
- Always write the hero's name EXACTLY as it appears on the character sheet \
— never translate, transliterate, or nickname it — and use the name (not \
just 你) at least once per reply so it stands out in the narration.
- CRITICAL: directives keep their EXACT English syntax — [[roll: d20+5 | \
reason]], [[sheet: hp=-3 | reason]], [[item: add Name x1]], and the choice \
menu [[choice: 揀選嘅行動 | DEX | DC 13]]. Never translate the keywords \
roll/sheet/item/choice/reward, the ability tags STR/DEX/CON/INT/WIS/CHA/none, \
DC, hp/gold/xp/level/max_hp, add/remove, reroll/power, \
advantage/disadvantage, or the dice notation. The free-text action sentences, reasons and item names should be \
in Chinese.
""",
}

# [[kind: body]] — tolerant of whitespace and newlines inside the body.
_DIRECTIVE_RE = re.compile(r"\[\[\s*(roll|sheet|item|reward)\s*:\s*(.*?)\s*\]\]", re.IGNORECASE | re.DOTALL)
_CHOICE_RE = re.compile(r"\[\[\s*choice\s*:\s*(.*?)\s*\]\]", re.IGNORECASE | re.DOTALL)

ABILITY_TAGS = ("str", "dex", "con", "int", "wis", "cha")


def ability_mod(score: int) -> int:
    return (score - 10) // 2


def proficiency_bonus(level: int) -> int:
    """5e proficiency: +2 at levels 1-4, +3 at 5-8, and so on."""
    return 2 + max(0, level - 1) // 4


_DC_RE = re.compile(r"dc\s*=?\s*(\d+)", re.IGNORECASE)

# Styling lives in ui.py (256-color palette, NO_COLOR-aware).
DIM, RESET = ui.DIM, ui.RESET
CYAN, GREEN, RED, NAME = ui.ARCANE, ui.MOSS, ui.BLOOD, ui.NAME


class MissingCLI(RuntimeError):
    pass


# game.py historically imports this name; keep it as an alias.
MissingCredentials = MissingCLI


class GameMaster:
    def __init__(self, character_id: int):
        self.character_id = character_id
        self.backend = current_backend()
        cfg = BACKENDS[self.backend]
        if shutil.which(cfg["bin"]) is None:
            others = [n for n, ok in available_backends().items() if ok]
            hint = f" Installed alternatives: {', '.join(others)} (switch with /backend)." \
                   if others else ""
            raise MissingCLI(
                f"`{cfg['bin']}` not found on PATH — install it first "
                f"({cfg['install']}).{hint}"
            )
        state = db.load_conversation(character_id)
        # state is {"session_id": ..., "history": [...]} once play has begun.
        self.session_id: str | None = (
            state.get("session_id") if isinstance(state, dict) else None
        )
        # Full transcript, kept for stateless backends, recaps, and switching.
        self.history: list[dict] = (
            state.get("history", []) if isinstance(state, dict) else [])
        char = db.get_character(character_id)
        self.name = char["name"]
        self._name_re = re.compile(re.escape(self.name), re.IGNORECASE)
        self.choices: list[tuple[str, str]] = []  # (action text, trait tag)

    def _system(self) -> str:
        char = db.get_character(self.character_id)
        lang = (char.get("lang") or "en").strip()
        scen = scenarios.SCENARIOS.get(char.get("scenario") or "tavern",
                                       scenarios.SCENARIOS["tavern"])
        premise = (char.get("premise") or "").strip() or scen["premise"]
        if char.get("scenario") == "custom" and premise:
            premise = f"Tonight's story, in the player's own words: {premise}"
        return f"{GM_HEADER}\n{premise}\n\n{SYSTEM_PROMPT}{LANG_ADDENDA.get(lang, '')}"

    # `game.py` uses truthiness of `gm.messages` to detect a resumable game.
    @property
    def messages(self):
        return [self.session_id] if self.session_id else []

    # ------------------------------------------------------------- CLI call ----
    def _save_state(self) -> None:
        db.save_conversation(self.character_id,
                             {"session_id": self.session_id, "history": self.history})

    def _remember(self, role: str, text: str) -> None:
        self.history.append({"role": role, "text": text})

    def _invoke(self, prompt: str) -> str:
        """One GM turn on the configured backend."""
        if BACKENDS[self.backend]["mode"] == "session":
            return self._claude(prompt)
        return self._stateless(prompt)

    def _stateless(self, prompt: str) -> str:
        """Backends with no session support (e.g. gemini): replay the
        transcript from SQLite on every call. Works with any `-p`-style CLI."""
        cfg = BACKENDS[self.backend]
        lines = []
        for entry in self.history[-HISTORY_TURNS:]:
            role = {"player": "Player", "gm": "GM", "system": "System"}.get(
                entry["role"], entry["role"])
            lines.append(f"{role}: {entry['text'][:HISTORY_CLIP]}")
        transcript = ("\n\n[Transcript so far — continue this story consistently]\n"
                      + "\n".join(lines) + "\n" if lines else "")
        full = (f"{self._system()}\n{transcript}\n"
                f"[Respond now as the GM to this, following all the rules above]\n"
                f"{prompt}")
        cmd = [cfg["bin"]]
        model = current_model(self.backend)
        if model:
            cmd += ["-m", model]
        cmd += ["-p", full]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=TURN_TIMEOUT,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"the Game Master took longer than {TURN_TIMEOUT}s — try again")
        except FileNotFoundError:
            raise MissingCLI(f"`{cfg['bin']}` not found — {cfg['install']}")
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"{self.backend} CLI failed: {err[:500]}")
        return (proc.stdout or "").strip()

    def _recap(self) -> str:
        """Story recap from the event log, used when a session can't be resumed."""
        lines = [f"[{e['kind']}] {e['content'][:300]}" for e in db.get_log(self.character_id, 30)]
        return ("[System: the previous conversation was lost. Recent story log, "
                "oldest first — reconstruct the scene from it and continue "
                "seamlessly.]\n" + "\n".join(lines) + "\n\n")

    def _claude(self, prompt: str) -> str:
        """One turn against the persistent session. Returns the GM's text."""
        resuming = bool(self.session_id)
        cmd = [
            CLAUDE_BIN, "-p",
            "--model", current_model("claude"),
            "--output-format", "json",
            "--tools", "",                  # the GM narrates; our engine executes
            "--disable-slash-commands",
            "--strict-mcp-config",          # ignore any configured MCP servers
            "--system-prompt", self._system(),
        ]
        effort = current_effort()
        if effort:
            cmd += ["--effort", effort]
        if resuming:
            cmd += ["--resume", self.session_id]
        else:
            self.session_id = str(uuid.uuid4())
            cmd += ["--session-id", self.session_id]
        cmd.append(prompt)

        # 1-hour prompt-cache TTL: player turns are often minutes apart, so the
        # default 5-minute cache window would expire between turns.
        env = {**os.environ, "ENABLE_PROMPT_CACHING_1H": "1"}
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=TURN_TIMEOUT,
                cwd=os.path.dirname(os.path.abspath(__file__)), env=env,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"the Game Master took longer than {TURN_TIMEOUT}s — try again")

        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()

        # A missing saved session (cleaned up / different machine) surfaces as a
        # plain-text "No conversation found..." line — exit code 0, not JSON.
        if resuming and re.search(r"no conversation found", out + err, re.I):
            print(f"{DIM}(previous session unavailable — starting a fresh one "
                  f"with a story recap){RESET}")
            self.session_id = None
            return self._claude(self._recap() + prompt)

        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI failed: {(err or out)[:500]}")

        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            # Shouldn't happen with --output-format json; fall back to raw text.
            return out

        # Keep whatever session id the CLI actually used, and persist it.
        self.session_id = payload.get("session_id", self.session_id)
        self._save_state()

        if payload.get("is_error"):
            raise RuntimeError(f"claude CLI error: {str(payload.get('result'))[:500]}")
        return payload.get("result") or ""

    # ---------------------------------------------------------- directives -----
    def _sheet_prefix(self) -> str:
        char = db.get_character(self.character_id)
        inv = db.get_inventory(self.character_id)
        inv_str = ", ".join(f"{i['item']} x{i['qty']}" for i in inv) or "(empty)"
        return (
            f"[Character sheet — authoritative: {char['name']}, level {char['level']} "
            f"{char['race']} {char['class']} | HP {char['hp']}/{char['max_hp']} | "
            f"Gold {char['gold']} | XP {char['xp']} | STR {char['str']} DEX {char['dex']} "
            f"CON {char['con']} INT {char['int']} WIS {char['wis']} CHA {char['cha']} | "
            f"XP to next level: {db.xp_for_next(char['level']) - char['xp']} | "
            f"Tokens: rerolls {char.get('rerolls', 0)}, power {char.get('power_rolls', 0)} | "
            f"Inventory: {inv_str}]"
        )

    def _show(self, line: str) -> None:
        print(f"{DIM}{CYAN}{line}{RESET}")

    def _exec_roll(self, body: str) -> str:
        parts = [p.strip() for p in body.split("|")]
        notation = parts[0]
        reason = parts[1] if len(parts) > 1 and parts[1] else "roll"
        # trailing parts may carry advantage/disadvantage and/or "DC n", any order
        extras = " ".join(parts[2:]).lower()
        dc_m = _DC_RE.search(extras)
        dc = int(dc_m.group(1)) if dc_m else None
        result = dice.roll(
            notation,
            advantage="advantage" in extras and "disadv" not in extras,
            disadvantage="disadvantage" in extras,
        )
        # natural d20 face, when this was a single-d20 style check
        nat = None
        if result.groups and result.groups[0].sides == 20:
            kept = result.groups[0].kept
            nat = kept[0] if len(kept) == 1 else None
        need = (dc - result.modifier) if (dc is not None and nat is not None) else None
        ui.roll_display(reason, result.detail(), result.total, nat=nat, dc=dc,
                        notation=notation, need=need)
        db.log_event(self.character_id, "roll",
                     f"{reason}{f' vs DC {dc}' if dc else ''}: {result.detail()}")
        rerolls_spent = 0
        if nat is not None and dc is not None:
            result, rerolls_spent = self._maybe_reroll(notation, result, dc, reason)
            g0 = result.groups[0]
            nat = g0.rolls[0] if (g0.sides == 20 and len(g0.kept) == 1) else nat
        verdict = ""
        if nat == 20:
            verdict = " → NATURAL 20, critical success"
        elif nat == 1:
            verdict = " → NATURAL 1, critical failure"
        elif dc is not None:
            verdict = (f" → SUCCESS vs DC {dc}" if result.total >= dc
                       else f" → FAILURE vs DC {dc}")
        if rerolls_spent:
            verdict += f" (player spent {rerolls_spent} reroll token(s); this is the final roll)"
        return f"roll ({reason}): {result.detail()}{verdict}"

    def _exec_sheet(self, body: str) -> str:
        parts = [p.strip() for p in body.split("|")]
        reason = parts[1] if len(parts) > 1 else ""
        deltas = {"hp": 0, "gold": 0, "xp": 0}
        absolutes: dict = {"level": None, "max_hp": None}
        for m in re.finditer(r"(hp|gold|xp|level|max_hp)\s*=\s*([+-]?\d+)", parts[0], re.I):
            key, val = m.group(1).lower(), int(m.group(2))
            if key in deltas:
                deltas[key] += val
            else:
                absolutes[key] = val
        char = db.adjust_character(self.character_id, **deltas,
                                   level=absolutes["level"], max_hp=absolutes["max_hp"])
        line = (f"{reason}  →  HP {char['hp']}/{char['max_hp']}  Gold {char['gold']}  "
                f"XP {char['xp']}/{db.xp_for_next(char['level'])}  Lvl {char['level']}")
        self._show(f"📜 {line}")
        db.log_event(self.character_id, "sheet", line)
        levelup = ""
        if char.get("_leveled_up"):
            self._show(f"🎉 LEVEL UP! {char['name'] if 'name' in char else 'The hero'} "
                       f"is now level {char['level']} — max HP {char['max_hp']}, fully "
                       f"healed, +1 ⚡ power and +1 ↻ reroll!")
            db.log_event(self.character_id, "levelup", f"Reached level {char['level']}")
            levelup = (f" *** LEVEL UP: the hero just reached level {char['level']} "
                       f"(max HP now {char['max_hp']}, fully healed, bonus tokens "
                       f"granted). Celebrate this in the narration! ***")
        status = "" if char["hp"] > 0 else " — THE CHARACTER IS AT 0 HP (down/dying)"
        return (f"sheet ({reason}): HP {char['hp']}/{char['max_hp']}, Gold {char['gold']}, "
                f"XP {char['xp']} (next level at {db.xp_for_next(char['level'])}), "
                f"Level {char['level']}{status}{levelup}")

    def _exec_item(self, body: str) -> str:
        m = re.match(r"(add|remove)\s+(.+?)(?:\s+x\s*(\d+))?\s*$", body.strip(), re.I | re.S)
        if not m:
            return f"item: could not parse {body!r} (use: add NAME x2 / remove NAME)"
        action, item, qty = m.group(1).lower(), m.group(2).strip(), int(m.group(3) or 1)
        if action == "add":
            inv = db.add_item(self.character_id, item, qty)
            self._show(f"🎒 Gained {item} x{qty}")
        else:
            inv = db.remove_item(self.character_id, item, qty)
            self._show(f"🎒 Lost {item} x{qty}")
        db.log_event(self.character_id, "inventory", f"{action} {item} x{qty}")
        inv_str = ", ".join(f"{i['item']} x{i['qty']}" for i in inv) or "(empty)"
        return f"item: {action} {item} x{qty} ok. Inventory now: {inv_str}"

    def _exec_reward(self, body: str) -> str:
        m = re.match(r"(reroll|power)s?\s*(?:x\s*(\d+))?\s*(?:\|\s*(.*))?$",
                     body.strip(), re.I | re.S)
        if not m:
            return f"reward: could not parse {body!r} (use: reroll x1 | reason)"
        kind, qty = m.group(1).lower(), int(m.group(2) or 1)
        reason = (m.group(3) or "").strip()
        char = db.adjust_resources(self.character_id,
                                   rerolls=qty if kind == "reroll" else 0,
                                   power_rolls=qty if kind == "power" else 0)
        icon = "↻" if kind == "reroll" else "⚡"
        self._show(f"🎁 {reason or 'Story reward'}  →  {icon} {kind} +{qty}  "
                   f"({char['rerolls']} rerolls, {char['power_rolls']} power)")
        db.log_event(self.character_id, "reward", f"{reason}: {kind} +{qty}")
        return (f"reward: {kind} +{qty} granted. Player now holds "
                f"{char['rerolls']} rerolls and {char['power_rolls']} power tokens.")

    def _maybe_reroll(self, notation: str, result, dc: int | None, label: str):
        """After a failed d20 check, offer to spend ↻ reroll tokens.

        Returns (final_result, rerolls_spent). Interactive only — skipped when
        stdin isn't a terminal (tests, pipes) unless TAVERN_TEST_REROLL is set.
        """
        spent = 0
        while True:
            g0 = result.groups[0] if result.groups else None
            nat = g0.rolls[0] if (g0 and g0.sides == 20 and len(g0.kept) == 1) else None
            failed = (nat == 1) or (dc is not None and result.total < dc and nat != 20)
            if not failed:
                break
            left = db.get_character(self.character_id).get("rerolls", 0)
            if left < 1:
                break
            auto = os.environ.get("TAVERN_TEST_REROLL", "")
            if not sys.stdin.isatty() and not auto:
                break
            try:
                ans = auto or input(
                    f"  {ui.GOLD}↻ Spend a reroll?{ui.RESET} "
                    f"{ui.DIM}({left} left — the new roll replaces this one) "
                    f"[y/N]{ui.RESET} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                break
            if auto:  # consume the test value so loops terminate
                os.environ["TAVERN_TEST_REROLL"] = ""
            if ans != "y":
                break
            db.adjust_resources(self.character_id, rerolls=-1)
            spent += 1
            result = dice.roll(notation)
            g0 = result.groups[0]
            nat2 = g0.rolls[0] if (g0.sides == 20 and len(g0.kept) == 1) else None
            need = (dc - result.modifier) if dc is not None else None
            ui.roll_display(f"{label} · reroll {spent}", result.detail(),
                            result.total, nat=nat2, dc=dc, notation=notation,
                            need=need)
            db.log_event(self.character_id, "roll",
                         f"reroll {spent} of {label}: {result.detail()}")
        return result, spent

    def _execute(self, kind: str, body: str) -> str:
        try:
            if kind == "roll":
                return self._exec_roll(body)
            if kind == "sheet":
                return self._exec_sheet(body)
            if kind == "item":
                return self._exec_item(body)
            if kind == "reward":
                return self._exec_reward(body)
        except Exception as e:
            return f"{kind}: ERROR — {e}"
        return f"{kind}: unknown directive"

    # -------------------------------------------------------- choice menu ------
    def _parse_choices(self, reply: str) -> list[tuple[str, str, bool, int | None]]:
        """Extract [[choice: text | TRAIT[*] | DC n]] → (text, trait, prof, dc)."""
        out = []
        for body in _CHOICE_RE.findall(reply):
            parts = [p.strip() for p in body.split("|")]
            text = parts[0]
            raw_trait = parts[1].lower() if len(parts) > 1 else "none"
            prof = "*" in raw_trait
            trait = raw_trait.replace("*", "").strip()
            if trait not in ABILITY_TAGS:
                trait = "none"
                prof = False
            dc = None
            for extra in parts[1:]:
                m = _DC_RE.search(extra)
                if m:
                    dc = int(m.group(1))
            # The engine guarantees a target even if the GM forgot one:
            # default to DC 13 (a medium check) and mark it as assumed.
            assumed = trait != "none" and dc is None
            if assumed:
                dc = 13
            if text:
                out.append((text, trait, prof, dc, assumed))
        return out

    def _check_mod(self, char: dict, trait: str, prof: bool) -> int:
        """Total d20 modifier: ability mod + proficiency when it applies."""
        return ability_mod(char[trait]) + (proficiency_bonus(char["level"]) if prof else 0)

    def _print_choices(self) -> None:
        char = db.get_character(self.character_id)
        print()
        print(ui.rule("choose"))
        for i, (text, trait, prof, dc, assumed) in enumerate(self.choices, 1):
            if trait == "none":
                tag = f"{ui.SHADOW}· no roll ·{RESET}"
            else:
                mod = self._check_mod(char, trait, prof)
                color = GREEN if mod > 0 else RED if mod < 0 else CYAN
                star = f"{ui.GOLD}★{RESET}" if prof else ""
                tag = f"{color}⚅ {trait.upper()} {mod:+d}{RESET}{star}"
                # the classic tabletop readout: what the d20 has to show
                need = max(2, min(20, dc - mod))
                tag += f" {ui.SHADOW}need {need}+{RESET}"
            body = ui.wrap_ansi(ui.md(text), indent="     ").lstrip()
            print(f" {ui.AMBER}{ui.BOLD}{i}{RESET}  {body}  {tag}")
        print(ui.rule())
        n = len(self.choices)
        print(f"{DIM}Pick 1-{n} (or {ui.GOLD}p1{RESET}{DIM}-p{n} to add "
              f"{ui.GOLD}⚡+10{RESET}{DIM}), or type your own action. "
              f"{ui.GOLD}★{RESET}{DIM} = proficiency "
              f"(+{proficiency_bonus(char['level'])}).{RESET}  "
              f"{ui.GOLD}⚡ {char.get('power_rolls', 0)}{RESET}{DIM} power · "
              f"{ui.ARCANE}↻ {char.get('rerolls', 0)}{RESET}{DIM} rerolls{RESET}")

    def play_choice(self, index: int, power: bool = False) -> None:
        """Resolve a menu pick 5e-style: d20 + ability mod (+ proficiency) vs DC.

        `power=True` spends a ⚡ power token for +10 on the roll (declared
        before rolling). A failed check then offers ↻ reroll tokens.
        """
        text, trait, prof, dc, assumed = self.choices[index]
        if trait == "none":
            if power:
                print(f"  {ui.SHADOW}That option has no roll — power token not needed.{RESET}")
            self.send(f'I choose: "{text}"')
            return
        char = db.get_character(self.character_id)
        mod = self._check_mod(char, trait, prof)

        power_used = False
        if power:
            if char.get("power_rolls", 0) < 1:
                print(f"  {ui.BLOOD}No ⚡ power tokens left — rolling normally.{RESET}")
            else:
                char = db.adjust_resources(self.character_id, power_rolls=-1)
                mod += 10
                power_used = True
                print(f"  {ui.GOLD}⚡ POWER ROLL — +10! "
                      f"({char['power_rolls']} power tokens left){RESET}")

        notation = f"d20{mod:+d}" if mod else "d20"
        result = dice.roll(notation)
        nat = result.groups[0].rolls[0]
        label = (f"{trait.upper()} check{' ★' if prof else ''}"
                 f"{' ⚡' if power_used else ''}")
        ui.roll_display(label, result.detail(), result.total, nat=nat, dc=dc,
                        notation=notation, need=dc - mod, assumed_dc=assumed)
        db.log_event(self.character_id, "roll",
                     f"{text} [{label} vs DC {dc}]: {result.detail()}")

        result, rerolls_spent = self._maybe_reroll(notation, result, dc, label)
        nat = result.groups[0].rolls[0]

        if nat == 20:
            verdict = "NATURAL 20 — automatic critical success"
        elif nat == 1:
            verdict = "NATURAL 1 — automatic critical failure"
        elif dc is not None:
            margin = result.total - dc
            verdict = (f"SUCCESS vs DC {dc} (by {margin})" if margin >= 0
                       else f"FAILURE vs DC {dc} (by {-margin})")
        else:
            verdict = "no DC given — judge the total yourself"
        if assumed:
            verdict += " [the engine assumed DC 13 because the choice had no DC — always include one]"
        extras = []
        if power_used:
            extras.append("the player spent a POWER token (+10 included in the total)")
        if rerolls_spent:
            extras.append(f"the player spent {rerolls_spent} reroll token(s); this is the final roll")
        extra_txt = f" ({'; '.join(extras)})" if extras else ""
        self.send(
            f'I choose: "{text}" — the engine rolled the {trait.upper()} check'
            f"{' with proficiency' if prof else ''}: {result.detail()} "
            f"(d20 showed {nat}) → {verdict}{extra_txt}. "
            f"Narrate the outcome using exactly this result."
        )

    # ------------------------------------------------------------ main turn ----
    def send(self, user_text: str) -> None:
        db.log_event(self.character_id, "player", user_text)
        self._remember("player", user_text)
        prompt = f"{self._sheet_prefix()}\n\nPlayer: {user_text}"
        self.choices = []
        print()

        for _ in range(MAX_TOOL_ROUNDS):
            with ui.Spinner(f"Fateweaver — the GM ({self.backend}) is narrating..."):
                reply = self._invoke(prompt)

            # The freshest choice menu wins (a roll continuation may re-offer).
            found = self._parse_choices(reply)
            if found:
                self.choices = found

            # Show narration: markdown → ANSI, hero's name highlighted, wrapped.
            narration = _CHOICE_RE.sub("", _DIRECTIVE_RE.sub("", reply)).strip()
            if narration:
                print(ui.narration(narration, self.name) + "\n")
                db.log_event(self.character_id, "gm", narration)
            self._remember("gm", reply)  # raw reply keeps directives for replay

            directives = _DIRECTIVE_RE.findall(reply)
            if not directives:
                break

            results = [self._execute(kind.lower(), body) for kind, body in directives]
            needs_narration = any(kind.lower() == "roll" for kind, _ in directives)
            if not needs_narration:
                # Sheet/item bookkeeping alongside narration — nothing to add.
                break

            print()
            prompt = (
                "[System: directive results — the real numbers]\n- "
                + "\n- ".join(results)
                + "\nContinue the scene now using exactly these results, then "
                  "present the three [[choice: ...]] options. "
                  "Do not repeat the directives you already emitted."
            )
            self._remember("system", "\n".join(results))

        if self.choices:
            self._print_choices()
        self._save_state()
