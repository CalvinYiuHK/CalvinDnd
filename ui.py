"""ui.py — terminal rendering for Fateweaver.

The GM speaks markdown; terminals speak ANSI. This module translates —
**bold**, *italic*, `code`, > quotes, headings — and adds the polish that
makes a terminal game feel good:

  * warm 256-color "tavern" palette (falls back to 8-color, honors NO_COLOR)
  * width-aware word wrap, including CJK text (Chinese chars are 2 cells wide)
  * dialogue coloring for "...", “...” and 「...」 speech
  * a braille spinner while the GM is thinking
  * an HP bar and horizontal rules for the character sheet

Pure stdlib. Everything degrades gracefully when piped or colorless.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time
import unicodedata

# ------------------------------------------------------------------ palette --

def _color_mode() -> int:
    """0 = no color, 1 = basic 8/16, 2 = 256-color."""
    if os.environ.get("NO_COLOR") is not None:
        return 0
    if not sys.stdout.isatty() and os.environ.get("TAVERN_FORCE_COLOR") is None:
        return 0
    term = os.environ.get("TERM", "")
    if "256" in term or os.environ.get("COLORTERM"):
        return 2
    return 1


MODE = _color_mode()


def _fg(c256: int, basic: str) -> str:
    if MODE == 0:
        return ""
    if MODE == 2:
        return f"\033[38;5;{c256}m"
    return basic


RESET = "\033[0m" if MODE else ""
BOLD = "\033[1m" if MODE else ""
ITALIC = "\033[3m" if MODE else ""
DIM = "\033[2m" if MODE else ""

AMBER = _fg(214, "\033[33m")          # lantern light — headings, accents
GOLD = _fg(178, "\033[33m")           # coin gold
PARCHMENT = _fg(223, "\033[37m")      # body text warmth
EMBER = _fg(208, "\033[31m")          # warnings, fumbles
SPEECH = _fg(150, "\033[32m")         # spoken dialogue — sage green
ARCANE = _fg(110, "\033[36m")         # dice, system, magic — dusty blue
BLOOD = _fg(167, "\033[31m")          # damage, HP low
MOSS = _fg(108, "\033[32m")           # buffs, healing
SHADOW = _fg(240, "\033[90m" if MODE else "")  # rules, hints
NAME = BOLD + _fg(220, "\033[33m")    # the hero's name — bright gold


def width() -> int:
    return min(shutil.get_terminal_size((88, 24)).columns, 88)


# ------------------------------------------------------ ANSI-aware measuring --

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _char_w(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def visible_width(s: str) -> int:
    return sum(_char_w(ch) for ch in _ANSI_RE.sub("", s))


def wrap_ansi(text: str, wrap_width: int | None = None, indent: str = "") -> str:
    """Word-wrap ANSI-styled text; CJK breaks anywhere, styles survive breaks."""
    w = (wrap_width or width()) - visible_width(indent)
    out_lines: list[str] = []

    for raw_line in text.split("\n"):
        if not raw_line.strip():
            out_lines.append("")
            continue

        # Tokenize into ANSI codes and characters.
        tokens: list[tuple[str, str]] = []  # (kind, value): "ansi" | "ch"
        i = 0
        while i < len(raw_line):
            m = _ANSI_RE.match(raw_line, i)
            if m:
                tokens.append(("ansi", m.group(0)))
                i = m.end()
            else:
                tokens.append(("ch", raw_line[i]))
                i += 1

        line = ""
        line_w = 0
        active: list[str] = []      # styles in effect (for carry-over)
        break_at = -1               # index in `line` of the last safe breakpoint
        break_w = 0

        def flush(upto: int | None = None):
            nonlocal line, line_w, break_at, break_w
            if upto is None or upto <= 0:
                emitted, rest = line, ""
            else:
                emitted, rest = line[:upto], line[upto:].lstrip(" ")
            out_lines.append(indent + emitted + (RESET if active and MODE else ""))
            line = ("".join(active) if MODE else "") + rest
            line_w = visible_width(rest)
            break_at = -1
            break_w = 0

        for kind, val in tokens:
            if kind == "ansi":
                line += val
                if val == RESET or val == "\033[0m":
                    active.clear()
                else:
                    active.append(val)
                continue
            cw = _char_w(val)
            if line_w + cw > w:
                if break_at > 0:
                    flush(break_at)
                else:
                    flush(None)
            line += val
            line_w += cw
            if val == " " or cw == 2:  # break after spaces or any CJK char
                break_at = len(line)
                break_w = line_w
        if line.strip() or not out_lines:
            out_lines.append(indent + line + (RESET if active and MODE else ""))

    return "\n".join(out_lines)


# --------------------------------------------------------- markdown → ANSI ---

def md(text: str) -> str:
    """Render the GM's markdown-ish prose to ANSI."""
    if MODE == 0:
        # Still strip the markup so plain terminals don't see asterisks.
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)
        text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
        text = re.sub(r"`([^`\n]+)`", r"\1", text)
        return text

    out_lines = []
    for line in text.split("\n"):
        # headings
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            out_lines.append(f"{BOLD}{AMBER}{m.group(2)}{RESET}")
            continue
        # block quotes
        m = re.match(r"^>\s?(.*)$", line)
        if m:
            out_lines.append(f"{SHADOW}▎{RESET}{ITALIC}{DIM}{m.group(1)}{RESET}")
            continue
        # bullets
        line = re.sub(r"^(\s*)[-*]\s+", rf"\1{AMBER}•{RESET} ", line)
        out_lines.append(line)
    text = "\n".join(out_lines)

    # inline styles (bold before italic so ** isn't eaten by *). Close with
    # targeted off-codes (22/23) — a full RESET would also wipe the dialogue
    # color when emphasis sits inside a quote.
    bold_off = "\033[22m"
    italic_off = "\033[23m"
    text = re.sub(r"\*\*(.+?)\*\*", rf"{BOLD}\1{bold_off}", text, flags=re.S)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", rf"{ITALIC}\1{italic_off}", text)
    text = re.sub(r"`([^`\n]+)`", rf"{ARCANE}\1{RESET}", text)

    # spoken dialogue — colored so voices pop out of the prose
    text = re.sub(r"「[^」]*」|『[^』]*』|“[^”]*”|\"[^\"\n]+\"",
                  lambda m: f"{SPEECH}{m.group(0)}{RESET}", text)
    return text


# ----------------------------------------------------------------- widgets ---

def rule(title: str = "") -> str:
    w = width()
    if not title:
        return f"{SHADOW}{'─' * w}{RESET}"
    t = f" {title} "
    side = max(2, (w - visible_width(t)) // 2)
    return f"{SHADOW}{'─' * side}{RESET}{AMBER}{t}{RESET}{SHADOW}{'─' * (w - side - visible_width(t))}{RESET}"


def hp_bar(hp: int, max_hp: int, bar_width: int = 20) -> str:
    max_hp = max(1, max_hp)
    filled = round(bar_width * max(0, hp) / max_hp)
    frac = hp / max_hp
    color = MOSS if frac > 0.5 else GOLD if frac > 0.25 else BLOOD
    return (f"{color}{'█' * filled}{SHADOW}{'░' * (bar_width - filled)}{RESET} "
            f"{color}{hp}{RESET}{SHADOW}/{max_hp}{RESET}")


class Spinner:
    """`with Spinner('the GM is narrating'):` — braille spinner on a TTY."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, text: str):
        self.text = text
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tty = sys.stdout.isatty()

    def _spin(self):
        i = 0
        while not self._stop.wait(0.09):
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r{AMBER}{frame}{RESET} {DIM}{self.text}{RESET}\033[K")
            sys.stdout.flush()
            i += 1

    def __enter__(self):
        if self._tty:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            print(f"... {self.text}")
        return self

    def __exit__(self, *exc):
        if self._thread:
            self._stop.set()
            self._thread.join()
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        return False


def _highlight_name(rendered: str, name: str) -> str:
    """Highlight the hero's name without wiping the surrounding color.

    If the name sits inside a colored dialogue span (「...」 etc.), closing
    with a bare RESET would strip the quote color from the rest of the
    sentence — instead we close bold and re-emit the speech color.
    """
    def repl(m: re.Match) -> str:
        if MODE == 0:
            return m.group(0)
        start = m.start()
        inside_speech = (SPEECH and
                         rendered.rfind(SPEECH, 0, start) > rendered.rfind(RESET, 0, start))
        close = f"\033[22m{SPEECH}" if inside_speech else RESET
        return f"{NAME}{m.group(0)}{close}"

    return re.sub(re.escape(name), repl, rendered, flags=re.IGNORECASE)


def narration(text: str, name: str | None = None) -> str:
    """Full pipeline for GM prose: markdown → name highlight → wrap."""
    rendered = md(text)
    if name:
        rendered = _highlight_name(rendered, name)
    return wrap_ansi(rendered)


# ------------------------------------------------------------ dice display ---

_DIE_FACES = "⚀⚁⚂⚃⚄⚅"


def roll_display(label: str, detail: str, total: int, nat: int | None = None,
                 dc: int | None = None, notation: str = "",
                 need: int | None = None, assumed_dc: bool = False) -> None:
    """A transparent dice roll:

      1. announce the formula and the target BEFORE rolling
         (⚅ INT check — rolling d20+2 vs DC 13 · need 11+)
      2. tumbling-die animation
      3. the full arithmetic and the verdict
         (→ 1d20 [13] + 2 = 15   ✓ success (DC 13))
    """
    import random as _random

    # 1 — what's about to happen, so the player knows the stakes up front
    pre = f"  {AMBER}⚅{RESET} {ARCANE}{label}{RESET}"
    if notation:
        pre += f" {SHADOW}—{RESET} rolling {BOLD}{notation}{RESET}"
    if dc is not None:
        pre += f" vs {BOLD}DC {dc}{RESET}"
        if assumed_dc:
            pre += f" {SHADOW}(assumed){RESET}"
        if need is not None:
            pre += f" {SHADOW}·{RESET} {GOLD}need {max(2, min(20, need))}+{RESET}"
    print(pre)

    # 2 — the tumble
    animate = sys.stdout.isatty() and MODE and os.environ.get("TAVERN_NO_ANIM") is None
    if animate:
        for i in range(16):
            face = _random.choice(_DIE_FACES)
            num = _random.randint(1, 20)
            sys.stdout.write(f"\r    {AMBER}{face}{RESET} {DIM}rolling...{RESET} "
                             f"{BOLD}{num}{RESET}\033[K")
            sys.stdout.flush()
            time.sleep(0.04 + i * 0.006)  # decelerate like a settling die
        sys.stdout.write("\r\033[K")

    # 3 — the landing: full arithmetic + verdict
    crit = nat == 20
    fumble = nat == 1
    if crit:
        verdict = f"   {BOLD}{GOLD}★ NATURAL 20 — critical success!{RESET}"
    elif fumble:
        verdict = f"   {BOLD}{BLOOD}✖ NATURAL 1 — critical failure!{RESET}"
    elif dc is not None:
        margin = total - dc
        verdict = (f"   {MOSS}✓ success by {margin}{RESET} {SHADOW}(DC {dc}){RESET}"
                   if margin >= 0 else
                   f"   {BLOOD}✗ failure by {-margin}{RESET} {SHADOW}(DC {dc}){RESET}")
    else:
        verdict = ""
    print(f"    {SHADOW}→{RESET} {detail}{verdict}")


# ------------------------------------------------------------ rarity colors --

RARITY_COLORS = {
    "normal": _fg(250, "\033[37m"),      # plain steel
    "uncommon": _fg(114, "\033[32m"),    # green
    "rare": _fg(75, "\033[34m"),         # blue
    "epic": _fg(135, "\033[35m"),        # purple
    "legendary": _fg(214, "\033[33m"),   # burning orange-gold
}


def rarity(name: str, tier: str) -> str:
    """Color an item name by its rarity tier; legendary also gets bold."""
    color = RARITY_COLORS.get(tier, RARITY_COLORS["normal"])
    weight = BOLD if tier in ("epic", "legendary") else ""
    return f"{weight}{color}{name}{RESET}"
