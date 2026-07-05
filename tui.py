#!/usr/bin/env python3
"""tui.py — Fateweaver's clickable terminal UI (Textual).

Run `./start.sh` (or `python3 tui.py`) for the full experience:

  * story log with the GM's colored narration
  * a live character panel — HP bar, XP, gold, tokens, stats, gear, skills
  * clickable choice buttons after every GM turn (with ⚡ power variants)
  * skill buttons, one click to use a signature move
  * a battle panel with ANSI art for every enemy (presets + generated)
  * dialogs for rerolls and level-up attribute allocation

The classic prompt game (`python3 game.py`) remains available with zero
dependencies; this front-end needs `pip install textual`.
"""

from __future__ import annotations

import contextlib
import io
import threading

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

import art
import db
import dice
import game
import gm as gm_mod
import scenarios as scen_mod
import ui


def ansi(text: str) -> Text:
    return Text.from_ansi(text)


class _LogWriter(io.TextIOBase):
    """Captures the engine's print() output and feeds it into the story log."""

    def __init__(self, app: "Fateweaver"):
        self.app = app
        self._buf = ""

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False  # engine skips spinners/animations under the TUI

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.app.call_from_thread(self.app.log_line, line)
        return len(s)

    def flush(self) -> None:
        if self._buf:
            self.app.call_from_thread(self.app.log_line, self._buf)
            self._buf = ""


class ConfirmScreen(ModalScreen[bool]):
    """Yes/no dialog (reroll offers, forget-skill, quit)."""

    def __init__(self, question: str, yes: str = "Yes", no: str = "No"):
        super().__init__()
        self.question, self.yes, self.no = question, yes, no

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(ansi(self.question), id="question")
            with Horizontal(id="dialog-buttons"):
                yield Button(self.yes, id="yes", variant="success")
                yield Button(self.no, id="no", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class AllocateScreen(ModalScreen[None]):
    """Level-up attribute allocation — click +1 buttons until spent."""

    def __init__(self, cid: int):
        super().__init__()
        self.cid = cid

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("", id="alloc-title")
            with Horizontal(id="alloc-row"):
                for a in ("str", "dex", "con", "int", "wis", "cha"):
                    yield Button(f"{a.upper()} +1", id=f"alloc-{a}", variant="primary")
            with Horizontal(id="dialog-buttons"):
                yield Button("Save the rest for later", id="alloc-later")

    def on_mount(self) -> None:
        self.refresh_title()

    def refresh_title(self) -> None:
        c = db.get_character(self.cid)
        pts = c.get("attr_points", 0)
        stats = "   ".join(f"{a.upper()} {c[a]}" for a in
                           ("str", "dex", "con", "int", "wis", "cha"))
        self.query_one("#alloc-title", Static).update(
            f"◆ Level-up training — {pts} point{'s' if pts != 1 else ''} left "
            f"(+1 each, max {db.STAT_CAP})\n{stats}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "alloc-later":
            self.dismiss(None)
            return
        ab = bid.removeprefix("alloc-")
        try:
            db.spend_attr_points(self.cid, {ab: 1})
        except ValueError:
            pass
        c = db.get_character(self.cid)
        if c.get("attr_points", 0) < 1:
            self.dismiss(None)
        else:
            self.refresh_title()


class PickerScreen(ModalScreen[int | None]):
    """A titled list of clickable options; returns the picked index."""

    def __init__(self, title: str, options: list[str]):
        super().__init__()
        self.title_text, self.options = title, options

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(ansi(self.title_text), id="question")
            with VerticalScroll(id="picker-list"):
                for i, opt in enumerate(self.options):
                    yield Button(ansi(opt).plain[:70], id=f"pick-{i}")
            with Horizontal(id="dialog-buttons"):
                yield Button("Close", id="pick-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "pick-cancel":
            self.dismiss(None)
        elif bid.startswith("pick-"):
            self.dismiss(int(bid.split("-")[1]))


class Fateweaver(App):
    """The Fateweaver TUI."""

    TITLE = "Fateweaver"
    SUB_TITLE = "any story, real dice"
    BINDINGS = [("ctrl+q", "quit_game", "Quit")]

    CSS = """
    #main { height: 1fr; }
    #story { width: 2fr; border: round $primary 30%; padding: 0 1; }
    #side { width: 34; }
    #sheet { border: round $secondary 30%; padding: 0 1; height: auto; }
    #battle { border: round red 40%; padding: 0 1; height: auto; display: none; }
    #battle.visible { display: block; }
    #choices { height: auto; padding: 0 1; }
    #choices Button { margin: 0 1 0 0; min-width: 8; }
    #cmdbar { height: auto; padding: 0 1; }
    #cmdbar Button { margin: 0 1 0 0; min-width: 6; }
    #player-input { margin: 0 1; }
    #dialog {
        align: center middle; background: $surface; border: thick $primary;
        padding: 1 2; width: 80; height: auto; margin: 4 8;
    }
    #dialog-buttons { height: auto; align-horizontal: center; }
    #dialog-buttons Button { margin: 0 2; }
    #alloc-row { height: auto; align-horizontal: center; }
    #alloc-row Button { margin: 0 1; min-width: 10; }
    #picker-list { max-height: 14; }
    #picker-list Button { width: 100%; margin: 0 0 1 0; }
    ConfirmScreen, AllocateScreen, PickerScreen { align: center middle; }
    """

    def __init__(self, cid: int):
        super().__init__()
        self.cid = cid
        self.gm = gm_mod.GameMaster(cid)
        self.busy = False

    # ---------------------------------------------------------- layout -------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main"):
            yield RichLog(id="story", wrap=True, markup=False, auto_scroll=True)
            with VerticalScroll(id="side"):
                yield Static(id="sheet")
                yield Static(id="battle")
        with Horizontal(id="choices"):
            pass
        yield Input(placeholder="Say or do anything… (or click a choice above)",
                    id="player-input")
        with Horizontal(id="cmdbar"):
            yield Button("Gear", id="cmd-gear")
            yield Button("Skills", id="cmd-skills")
            yield Button("Inspect", id="cmd-inspect")
            yield Button("Train", id="cmd-train")
            yield Button("Lang 中/EN", id="cmd-lang")
            yield Button("Quit", id="cmd-quit", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        gm_mod.CONFIRM = self._confirm_from_engine
        self.refresh_side()
        char = db.get_character(self.cid)
        scen = scen_mod.SCENARIOS.get(char.get("scenario") or "tavern",
                                      scen_mod.SCENARIOS["tavern"])
        self.sub_title = f"{char['name']} · {scen['emoji']} {scen['title']}"
        if self.gm.messages:
            opener = ("[The player has returned. Briefly recap where things "
                      "stood, then continue the scene and present the three "
                      "choice options.]")
        else:
            who = (f"{char['name']}, a {char['race']} {char['class']},"
                   if char["race"] != "—" else f"{char['name']}, {char['class']},")
            opener = f"[Begin the adventure. {who} {scen['opener']}]"
        self.run_turn(opener)

    # ------------------------------------------------------- engine bridge ---
    def log_line(self, line: str) -> None:
        self.query_one("#story", RichLog).write(ansi(line))

    def _confirm_from_engine(self, question: str) -> bool:
        """Called from the GM worker thread; blocks it on a dialog."""
        result = {}
        done = threading.Event()

        def ask() -> None:
            def finish(answer: bool | None) -> None:
                result["yes"] = bool(answer)
                done.set()
            self.push_screen(ConfirmScreen(f"🎲 {question}", "Reroll!", "Keep it"),
                             finish)

        self.call_from_thread(ask)
        done.wait()
        return result.get("yes", False)

    @work(thread=True, exclusive=True)
    def run_turn(self, text: str = "", choice: int | None = None,
                 power: bool = False, skill: int | None = None) -> None:
        self.busy = True
        self.call_from_thread(self.set_choices, [])  # clear while thinking
        self.call_from_thread(self.log_line,
                              f"{ui.SHADOW}— the GM is narrating… —{ui.RESET}")
        writer = _LogWriter(self)
        try:
            with contextlib.redirect_stdout(writer):
                if skill is not None:
                    self.gm.use_skill(skill)
                elif choice is not None:
                    self.gm.play_choice(choice, power=power)
                else:
                    self.gm.send(text)
        except Exception as e:
            self.call_from_thread(
                self.log_line, f"{ui.BLOOD}The GM stumbled: {e} — your progress "
                               f"is saved, try again.{ui.RESET}")
        finally:
            writer.flush()
            self.busy = False
        self.call_from_thread(self.after_turn)

    async def after_turn(self) -> None:
        self.refresh_side()
        await self.set_choices(self.gm.choices)
        if db.get_character(self.cid).get("attr_points", 0) > 0:
            self.push_screen(AllocateScreen(self.cid),
                             lambda _res: self.refresh_side())

    # ----------------------------------------------------------- panels ------
    def refresh_side(self) -> None:
        char = db.get_character(self.cid)
        lines = [""]
        lines.append(f" {ui.NAME}{char['name']}{ui.RESET}  "
                     f"{ui.SHADOW}lvl {char['level']} {char['class']}{ui.RESET}")
        lines.append(f" HP {ui.hp_bar(char['hp'], char['max_hp'], 16)}")
        nxt = db.xp_for_next(char["level"])
        lines.append(f" {ui.GOLD}⛁ {char['gold']}{ui.RESET}  "
                     f"{ui.ARCANE}✦ {char['xp']}/{nxt}{ui.RESET}  "
                     f"{ui.GOLD}⚡{char.get('power_rolls', 0)}{ui.RESET} "
                     f"{ui.ARCANE}↻{char.get('rerolls', 0)}{ui.RESET}")
        bon = db.equipment_bonuses(self.cid)
        stats = []
        for a in ("str", "dex", "con", "int", "wis", "cha"):
            eff = char[a] + bon.get(a, 0)
            mod = (eff - 10) // 2
            stats.append(f"{a.upper()} {eff}({mod:+d})")
        lines.append(" " + "  ".join(stats[:3]))
        lines.append(" " + "  ".join(stats[3:]))
        gear = [e for e in db.list_equipment(self.cid) if e["equipped"]]
        if gear:
            lines.append(f" {ui.SHADOW}Gear{ui.RESET}")
            for e in gear:
                b = " ".join(f"{k.upper()}{v:+d}" for k, v in e["bonuses"].items())
                lines.append(f"  {ui.rarity(e['name'], e['rarity'])} "
                             f"{ui.SHADOW}{b}{ui.RESET}")
        skills = db.list_skills(self.cid)
        if skills:
            lines.append(f" {ui.SHADOW}Skills{ui.RESET}")
            for i, sk in enumerate(skills, 1):
                tags = "+".join(a.upper() for a in sk["attrs"])
                lines.append(f"  {i}. {ui.AMBER}{sk['name']}{ui.RESET} "
                             f"{ui.SHADOW}{sk['dice']}+{tags}{ui.RESET}")
        pts = char.get("attr_points", 0)
        if pts:
            lines.append(f" {ui.GOLD}◆ {pts} points to train{ui.RESET}")
        self.query_one("#sheet", Static).update(ansi("\n".join(lines)))

        # battle panel
        battle = self.query_one("#battle", Static)
        foes = db.list_enemies(self.cid)
        if not foes:
            battle.remove_class("visible")
            battle.update("")
        else:
            battle.add_class("visible")
            parts = []
            for e in foes:
                parts.append(art.art_for(e["name"]))
                parts.append("")
                for line in self.gm.enemy_view(e):
                    parts.append(line.strip("\n"))
                parts.append("")
            battle.update(ansi("\n".join(parts)))

    async def set_choices(self, choices: list) -> None:
        bar = self.query_one("#choices", Horizontal)
        await bar.remove_children()
        char = db.get_character(self.cid)
        for i, (text, trait, prof, dc, _assumed) in enumerate(choices):
            if trait == "none":
                label = f"{i + 1}. {text[:38]} ·no roll·"
            else:
                mod = self.gm._check_mod(char, trait, prof)
                need = max(2, min(20, (dc or 13) - mod))
                label = (f"{i + 1}. {text[:34]} ⚅{trait.upper()}{mod:+d}"
                         f"{'★' if prof else ''} {need}+")
            bar.mount(Button(label, id=f"choice-{i}", variant="primary"))
            if trait != "none" and char.get("power_rolls", 0) > 0:
                bar.mount(Button(f"⚡p{i + 1}", id=f"powerchoice-{i}",
                                 variant="warning"))
        skills = db.list_skills(self.cid)
        for i, sk in enumerate(skills[:5]):
            bar.mount(Button(f"✦ {sk['name'][:14]}", id=f"skill-{i}"))

    # ------------------------------------------------------------ actions ----
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if self.busy and (bid.startswith(("choice-", "powerchoice-", "skill-"))):
            return
        if bid.startswith("choice-"):
            self.run_turn(choice=int(bid.split("-")[1]))
        elif bid.startswith("powerchoice-"):
            self.run_turn(choice=int(bid.split("-")[1]), power=True)
        elif bid.startswith("skill-"):
            self.run_turn(skill=int(bid.split("-")[1]))
        elif bid == "cmd-gear":
            self.show_gear()
        elif bid == "cmd-skills":
            self.show_skills()
        elif bid == "cmd-inspect":
            self.show_inspect()
        elif bid == "cmd-train":
            if db.get_character(self.cid).get("attr_points", 0) > 0:
                self.push_screen(AllocateScreen(self.cid),
                                 lambda _res: self.refresh_side())
            else:
                self.log_line(f"{ui.SHADOW}No unspent attribute points — level "
                              f"up to earn more.{ui.RESET}")
        elif bid == "cmd-lang":
            char = db.get_character(self.cid)
            new_lang = "en" if char.get("lang") == "canto" else "canto"
            db.set_language(self.cid, new_lang)
            label = ("Cantonese/Traditional Chinese" if new_lang == "canto"
                     else "English")
            self.run_turn(f"[The player switched the story language to {label}. "
                          f"Follow its narration rules from now on; briefly "
                          f"acknowledge in the new language and continue.]")
        elif bid == "cmd-quit":
            self.action_quit_game()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text or self.busy:
            return
        low = text.lower()
        # numbered picks and p#/s# shortcuts still work from the keyboard
        if low.isdigit() and self.gm.choices and 1 <= int(low) <= len(self.gm.choices):
            self.run_turn(choice=int(low) - 1)
        elif (len(low) == 2 and low[0] == "p" and low[1].isdigit()
              and self.gm.choices and 1 <= int(low[1]) <= len(self.gm.choices)):
            self.run_turn(choice=int(low[1]) - 1, power=True)
        elif len(low) == 2 and low[0] == "s" and low[1].isdigit():
            self.run_turn(skill=int(low[1]) - 1)
        elif low.startswith("/roll"):
            parts = text.split(maxsplit=1)
            try:
                r = dice.roll(parts[1] if len(parts) > 1 else "d20")
                self.log_line(f"  ⚅ {r.detail()}")
            except ValueError as e:
                self.log_line(f"{ui.BLOOD}{e}{ui.RESET}")
        else:
            self.run_turn(text)

    # ------------------------------------------------------------- modals ----
    def show_gear(self) -> None:
        gear = db.list_equipment(self.cid)
        if not gear:
            self.log_line(f"{ui.SHADOW}(no equipment yet — the story will "
                          f"provide){ui.RESET}")
            return
        opts = []
        for e in gear:
            b = " ".join(f"{k.upper()}{v:+d}" for k, v in e["bonuses"].items())
            mark = "●" if e["equipped"] else "○"
            abil = f" — {'; '.join(e['abilities'])}" if e["abilities"] else ""
            opts.append(f"{mark} {e['name']} [{e['rarity']} {e['slot']}] {b}{abil}")

        def picked(idx: int | None) -> None:
            if idx is not None:
                item = db.equip_item(self.cid, gear[idx]["id"])
                self.log_line(f"Equipped {ui.rarity(item['name'], item['rarity'])}.")
                self.refresh_side()

        self.push_screen(PickerScreen("🎒 Click to equip (one per slot)", opts),
                         picked)

    def show_skills(self) -> None:
        skills = db.list_skills(self.cid)
        char = db.get_character(self.cid)
        if not skills:
            self.log_line(f"{ui.SHADOW}(no skills yet — trainers and milestones "
                          f"teach them){ui.RESET}")
            return
        opts = []
        for sk in skills:
            tags = "+".join(a.upper() for a in sk["attrs"])
            opts.append(f"✦ {sk['name']} ({sk['dice']}+{tags}) — {sk['descr']}")

        def picked(idx: int | None) -> None:
            if idx is not None:
                self.run_turn(skill=idx)

        self.push_screen(
            PickerScreen(f"✦ Skills {len(skills)}/{db.max_skill_slots(char['level'])} "
                         f"— click to use", opts), picked)

    def show_inspect(self) -> None:
        foes = db.list_enemies(self.cid)
        if not foes:
            self.log_line(f"{ui.SHADOW}(no active enemies){ui.RESET}")
            return
        for e in foes:
            self.log_line("")
            for line in art.art_for(e["name"]).split("\n"):
                self.log_line(line)
            for line in self.gm.enemy_view(e):
                self.log_line(line)

    def action_quit_game(self) -> None:
        def finish(answer: bool | None) -> None:
            if answer:
                self.exit()
        self.push_screen(
            ConfirmScreen("Save and leave the story?", "Quit", "Stay"), finish)


def main() -> None:
    db.init_db()
    print(game.BANNER)
    cid = game.pick_or_create()
    Fateweaver(cid).run()


if __name__ == "__main__":
    main()
