#!/usr/bin/env python3
"""tui.py — Fateweaver's clickable terminal UI (Textual).

Run `./start.sh` (or `python3 tui.py`) for the full experience:

  * story log with the GM's colored narration
  * a tabbed sidebar — Hero / Gear / Skills / Foes — always in view:
    click gear to equip it, click skills to use or forget them, and watch
    every enemy's ANSI art and HP live in the Foes tab (it takes focus the
    moment a fight starts)
  * big clickable choice buttons with highlighted stat badges
    (trait, your modifier, and the d20 target as colored chips)
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
from textual.widgets import (Button, Footer, Header, Input, RichLog, Static,
                             TabbedContent, TabPane)

import art
import db
import dice
import game
import gm as gm_mod
import scenarios as scen_mod
import ui


def ansi(text: str) -> Text:
    return Text.from_ansi(text)


# chip styles for the choice badges
_POS = "bold black on #87af5f"      # buffed check — green chip
_NEG = "bold white on #af5f5f"      # debuffed check — red chip
_NEU = "bold black on #5fafd7"      # neutral check — blue chip
_NEED = "bold #ffd75f"              # the d20 target
_NUM = "bold black on #ffaf5f"      # choice number chip
_NOROLL = "dim"


class _LogWriter(io.TextIOBase):
    """Captures the engine's print() output and feeds it into the story log."""

    def __init__(self, app: "Fateweaver"):
        self.app = app
        self._buf = ""

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False  # engine skips spinners/animations under the TUI

    def _emit(self, line: str) -> None:
        # redirect_stdout is process-global: writes can arrive from the GM
        # worker thread (usual) or the app thread itself (stray prints).
        try:
            self.app.call_from_thread(self.app.log_line, line)
        except RuntimeError:
            self.app.log_line(line)

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line)
        return len(s)

    def flush(self) -> None:
        if self._buf:
            self._emit(self._buf)
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


class Fateweaver(App):
    """The Fateweaver TUI."""

    TITLE = "Fateweaver"
    SUB_TITLE = "any story, real dice"
    BINDINGS = [("ctrl+q", "quit_game", "Quit")]

    CSS = """
    #main { height: 1fr; }
    #story { width: 2fr; border: round $primary 30%; padding: 0 1; }
    #side-tabs { width: 42; }
    #side-tabs TabPane { padding: 0 1; }
    #choices { height: auto; padding: 0 1; }
    .choice-row { height: auto; }
    .choice-row Button { margin: 0 1 0 0; }
    .choice-main { width: 1fr; content-align: left middle; }
    #player-input { margin: 0 1; }
    #cmdbar { height: auto; padding: 0 1; }
    #cmdbar Button { margin: 0 1 0 0; min-width: 6; }
    .gear-item, .skill-item { width: 100%; margin: 0 0 0 0; content-align: left middle; }
    .skill-forget { min-width: 10; }
    #dialog {
        align: center middle; background: $surface; border: thick $primary;
        padding: 1 2; width: 80; height: auto; margin: 4 8;
    }
    #dialog-buttons { height: auto; align-horizontal: center; }
    #dialog-buttons Button { margin: 0 2; }
    #alloc-row { height: auto; align-horizontal: center; }
    #alloc-row Button { margin: 0 1; min-width: 10; }
    ConfirmScreen, AllocateScreen { align: center middle; }
    """

    def __init__(self, cid: int):
        super().__init__()
        self.cid = cid
        self.gm = gm_mod.GameMaster(cid)
        self.busy = False
        self._gen = 0          # generation counter for unique dynamic ids
        self._had_foes = False

    # ---------------------------------------------------------- layout -------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main"):
            yield RichLog(id="story", wrap=True, markup=False, auto_scroll=True)
            with TabbedContent(initial="tab-hero", id="side-tabs"):
                with TabPane("Hero", id="tab-hero"):
                    with VerticalScroll():
                        yield Static(id="sheet")
                with TabPane("Gear", id="tab-gear"):
                    yield VerticalScroll(id="gear-list")
                with TabPane("Skills", id="tab-skills"):
                    yield VerticalScroll(id="skill-list")
                with TabPane("Foes", id="tab-foes"):
                    with VerticalScroll():
                        yield Static(id="battle")
        with Vertical(id="choices"):
            pass
        yield Input(placeholder="Say or do anything… (or click a choice above)",
                    id="player-input")
        with Horizontal(id="cmdbar"):
            yield Button("Train ◆", id="cmd-train")
            yield Button("Roll d20", id="cmd-roll")
            yield Button("Lang 中/EN", id="cmd-lang")
            yield Button("Quit", id="cmd-quit", variant="error")
        yield Footer()

    async def on_mount(self) -> None:
        gm_mod.CONFIRM = self._confirm_from_engine
        await self.refresh_side()
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
        self.call_from_thread(self.clear_choices)
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

    def clear_choices(self) -> None:
        self.query_one("#choices", Vertical).remove_children()

    async def after_turn(self) -> None:
        await self.refresh_side()
        await self.set_choices(self.gm.choices)
        if db.get_character(self.cid).get("attr_points", 0) > 0:
            self.push_screen(AllocateScreen(self.cid),
                             lambda _res: self.call_later(self.refresh_side))

    # ----------------------------------------------------------- sidebar -----
    async def refresh_side(self) -> None:
        self._gen += 1
        gen = self._gen
        char = db.get_character(self.cid)

        # --- Hero tab ---
        lines = [""]
        lines.append(f" {ui.NAME}{char['name']}{ui.RESET}  "
                     f"{ui.SHADOW}lvl {char['level']} {char['class']}{ui.RESET}")
        lines.append(f" HP {ui.hp_bar(char['hp'], char['max_hp'], 18)}")
        nxt = db.xp_for_next(char["level"])
        lines.append(f" {ui.GOLD}⛁ {char['gold']}{ui.RESET}  "
                     f"{ui.ARCANE}✦ {char['xp']}/{nxt} xp{ui.RESET}  "
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
        pts = char.get("attr_points", 0)
        if pts:
            lines.append(f" {ui.GOLD}◆ {pts} points to train{ui.RESET}")
        inv = db.get_inventory(self.cid)
        if inv:
            lines.append(f" {ui.SHADOW}Pack:{ui.RESET} " +
                         ", ".join(f"{i['item']} x{i['qty']}" for i in inv))
        self.query_one("#sheet", Static).update(ansi("\n".join(lines)))

        # --- Gear tab: click an item to equip it ---
        gear_list = self.query_one("#gear-list", VerticalScroll)
        await gear_list.remove_children()
        gear = db.list_equipment(self.cid)
        if not gear:
            await gear_list.mount(Static(ansi(
                f"{ui.SHADOW}(no equipment yet — the story provides){ui.RESET}")))
        for e in gear:
            label = Text()
            label.append("● " if e["equipped"] else "○ ",
                         style="green" if e["equipped"] else "dim")
            label.append(ansi(ui.rarity(e["name"], e["rarity"])))
            label.append(f"  [{e['rarity']} {e['slot']}] ", style="dim")
            bons = " ".join(f"{k.upper()}{v:+d}" for k, v in e["bonuses"].items())
            if bons:
                label.append(f" {bons} ", style=_POS)
            for ab in e["abilities"]:
                label.append(f"\n   ✧ {ab}", style="#ffd75f")
            await gear_list.mount(Button(label, id=f"gearbtn-{gen}-{e['id']}",
                                         classes="gear-item"))

        # --- Skills tab: use / forget ---
        skill_list = self.query_one("#skill-list", VerticalScroll)
        await skill_list.remove_children()
        skills = db.list_skills(self.cid)
        await skill_list.mount(Static(ansi(
            f"{ui.SHADOW}Slots {len(skills)}/{db.max_skill_slots(char['level'])} — "
            f"click to use in the story{ui.RESET}")))
        for i, sk in enumerate(skills):
            tags = "+".join(a.upper() for a in sk["attrs"])
            label = Text()
            label.append(f"✦ {sk['name']} ", style="bold #ffaf5f")
            label.append(f" {sk['dice']}+{tags} ", style=_NEU)
            if sk["descr"]:
                label.append(f"\n   {sk['descr']}", style="dim")
            row = Horizontal(classes="choice-row")
            await skill_list.mount(row)
            await row.mount(Button(label, id=f"useskill-{gen}-{i}",
                                   classes="gear-item choice-main"))
            await row.mount(Button("forget", id=f"forgetskill-{gen}-{sk['id']}",
                                   classes="skill-forget", variant="error"))

        # --- Foes tab: art + tiered stats, autofocus on new combat ---
        battle = self.query_one("#battle", Static)
        foes = db.list_enemies(self.cid)
        tabs = self.query_one(TabbedContent)
        pane = self.query_one("#tab-foes", TabPane)
        if foes:
            parts = []
            for e in foes:
                parts.append(art.art_for(e["name"]))
                parts.append("")
                parts.extend(line.strip("\n") for line in self.gm.enemy_view(e))
                parts.append("")
            battle.update(ansi("\n".join(parts)))
            try:
                tabs.get_tab("tab-foes").label = f"⚔ Foes ({len(foes)})"
            except Exception:
                pass
            if not self._had_foes:
                tabs.active = "tab-foes"
            self._had_foes = True
        else:
            battle.update(ansi(f"{ui.SHADOW}(no active enemies — for now){ui.RESET}"))
            try:
                tabs.get_tab("tab-foes").label = "Foes"
            except Exception:
                pass
            self._had_foes = False

    # ------------------------------------------------------- choice buttons --
    async def set_choices(self, choices: list) -> None:
        box = self.query_one("#choices", Vertical)
        await box.remove_children()
        char = db.get_character(self.cid)
        self._gen += 1
        gen = self._gen
        for i, (text, trait, prof, dc, _assumed) in enumerate(choices):
            label = Text()
            label.append(f" {i + 1} ", style=_NUM)
            label.append(f" {text}  ")
            if trait == "none":
                label.append(" · no roll · ", style=_NOROLL)
            else:
                mod = self.gm._check_mod(char, trait, prof)
                need = max(2, min(20, (dc or 13) - mod))
                chip = _POS if mod > 0 else _NEG if mod < 0 else _NEU
                label.append(f" ⚅ {trait.upper()} {mod:+d}{'★' if prof else ''} ",
                             style=chip)
                label.append("  ")
                label.append(f"need {need}+", style=_NEED)
            row = Horizontal(classes="choice-row")
            await box.mount(row)
            await row.mount(Button(label, id=f"choice-{gen}-{i}",
                                   classes="choice-main", variant="primary"))
            if trait != "none" and char.get("power_rolls", 0) > 0:
                await row.mount(Button(f"⚡+10", id=f"powerchoice-{gen}-{i}",
                                       variant="warning"))

    # ------------------------------------------------------------ actions ----
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        part = bid.split("-")
        if bid.startswith(("choice-", "powerchoice-", "useskill-")) and self.busy:
            return
        if bid.startswith("choice-"):
            self.run_turn(choice=int(part[2]))
        elif bid.startswith("powerchoice-"):
            self.run_turn(choice=int(part[2]), power=True)
        elif bid.startswith("useskill-"):
            self.run_turn(skill=int(part[2]))
        elif bid.startswith("gearbtn-"):
            item = db.equip_item(self.cid, int(part[2]))
            if item:
                self.log_line(f"Equipped {ui.rarity(item['name'], item['rarity'])}.")
                self.call_later(self.refresh_side)
        elif bid.startswith("forgetskill-"):
            skill_id = int(part[2])
            sk = db.get_skill(skill_id)

            def finish(answer: bool | None) -> None:
                if answer and sk:
                    db.remove_skill(self.cid, skill_id)
                    self.log_line(f"{ui.SHADOW}Forgot {sk['name']} — a slot is "
                                  f"free.{ui.RESET}")
                    self.call_later(self.refresh_side)

            self.push_screen(
                ConfirmScreen(f"Forget {sk['name'] if sk else 'this skill'}?",
                              "Forget", "Keep"), finish)
        elif bid == "cmd-train":
            if db.get_character(self.cid).get("attr_points", 0) > 0:
                self.push_screen(AllocateScreen(self.cid),
                                 lambda _res: self.call_later(self.refresh_side))
            else:
                self.log_line(f"{ui.SHADOW}No unspent attribute points — level "
                              f"up to earn more.{ui.RESET}")
        elif bid == "cmd-roll":
            r = dice.roll("d20")
            self.log_line(f"  ⚅ {r.detail()}")
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
