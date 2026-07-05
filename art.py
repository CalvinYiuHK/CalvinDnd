"""art.py — ANSI battle art for Fateweaver.

Every enemy gets a face. `art_for(name)` keyword-matches the enemy's name to a
preset archetype (rat, goblin, skeleton, dragon, ...); names that match nothing
get a one-of-a-kind procedurally generated creature, which is stored in the
`enemy_art` table so the same foe always shows the same face.

Art is plain text with `{c}`/`{r}` color placeholders filled at render time so
stored art stays color-agnostic.
"""

from __future__ import annotations

import hashlib
import sqlite3

import db
import ui

# ------------------------------------------------------------------ presets --

# Each preset: (color, art). Art lines are ~14-22 cols. {c}=tint {d}=dim {r}=reset
PRESETS: dict[str, tuple[str, str]] = {
    "rat": (ui.GOLD, r"""
{d}   (\,/){r}
{c}   oo   '''//{r}
{c} ,/_;~,       \,{r}
{c} "'  \    (  \{r}
{d}      \|   ||{r}
{d}      (_/ (_/{r}"""),
    "goblin": (ui.MOSS, r"""
{c}   ,      ,{r}
{c}  /(.-""-.)\{r}
{d}  |\  \/  /|{r}
{c}  | \ / = \ /|{r}
{c}   \( {r}◉  ◉{c} )/{r}
{c}    \  ⌄  /{r}
{d}    /`~~~~`\{r}"""),
    "skeleton": (ui.PARCHMENT, r"""
{c}    .-----.{r}
{c}   /       \{r}
{c}  | {r}(){c}   {r}(){c} |{r}
{c}   \   ∆   /{r}
{c}    |uuuuu|{r}
{d}    /|-|-|\{r}
{d}     |   |{r}"""),
    "wolf": (ui.SHADOW, r"""
{c}   /\   /\{r}
{c}  ( {r}◣ {c}Y{r} ◢{c} ){r}
{c}   \  ▼  /{r}
{c}   /`___`\——,{r}
{d}  /  /   \  \\{r}
{d}  \_/     \_/{r}"""),
    "spider": (ui.ARCANE, r"""
{d}  /\  {c}.-.{r}{d}  /\{r}
{c} //\\({r}◉◉{c})//\\{r}
{c} \\  \\--//  //{r}
{d}  \\ /{c}~~~~{r}{d}\\ //{r}
{d}   V      V{r}"""),
    "snake": (ui.MOSS, r"""
{c}    ____{r}
{c}   / {r}◉ {c}\_______{r}
{c}   \__  ~~ ___ \{r}
{d}      \__/   \ \{r}
{c}    ~~~~~~~~~/ /{r}
{d}   ~~~~~~~~~~/{r}"""),
    "dragon": (ui.EMBER, r"""
{c}        /\____/\   ,{r}
{c}   ~~~ ( {r}✦  ✦{c} ) //{r}
{c}  (    )\ ▼▼ /_//{r}
{c}   \___/ \__/  /{r}
{d}     /|______|\{r}
{c}    ^^        ^^   {r}"""),
    "witch": (ui.ARCANE, r"""
{c}      /\{r}
{c}     /  \{r}
{c}    /____\{r}
{c}   ( {r}✦  ✦{c} ){r}
{d}    \ ωω /{r}
{c}   ~/|  |\~{r}
{d}    /|__|\ {r}"""),
    "ghost": (ui.PARCHMENT, r"""
{c}   .-''''-.{r}
{c}  /  {r}○  ○{c}  \{r}
{c} |    △    |{r}
{c} |  ______ |{r}
{c}  \/ \/ \/ \/{r}"""),
    "knight": (ui.SHADOW, r"""
{c}     ____{r}
{c}    /----\   ║{r}
{c}   | {r}▬▬▬▬{c} |  ║{r}
{c}   |  --  | ═╬═{r}
{d}   /|====|\  ║{r}
{d}    |    |   ║{r}"""),
    "bandit": (ui.GOLD, r"""
{c}    ____{r}
{c}   /    \{r}
{c}  | {r}◉ {d}██{r}{c} |   ,{r}
{c}   \ __ /   /|{r}
{d}   /|  |\  / |{r}
{d}    |==|  x  |{r}"""),
    "demon": (ui.BLOOD, r"""
{c}  \\        //{r}
{c}   \\.-””-.//{r}
{c}   ( {r}▲  ▲{c} ){r}
{c}    \ ‸‸‸ /{r}
{c}  ,__\    /__,{r}
{d}     /|  |\{r}"""),
    "slime": (ui.MOSS, r"""
{c}    ______{r}
{c}  /        \{r}
{c} |  {r}●    ●{c}  |{r}
{c} |     ‿    |{r}
{c}  \________/{r}
{d}  ~~~~~~~~~~{r}"""),
    "bear": (ui.EMBER, r"""
{c}  (\_/)  (\_/){r}
{c}   (  {r}●  ●{c}  ){r}
{c}   (   ▼   ){r}
{c}  /|       |\{r}
{d}   |_______|{r}
{d}    w     w{r}"""),
}

KEYWORDS = {
    "rat": ("rat", "mouse", "rodent", "鼠"),
    "goblin": ("goblin", "imp", "gremlin", "kobold", "哥布林", "小鬼"),
    "skeleton": ("skeleton", "bone", "skull", "lich", "骷髏", "骨"),
    "wolf": ("wolf", "hound", "dog", "jackal", "狼", "犬", "狗"),
    "spider": ("spider", "arachn", "蜘蛛"),
    "snake": ("snake", "serpent", "viper", "naga", "蛇"),
    "dragon": ("dragon", "wyrm", "drake", "wyvern", "龍", "龙"),
    "witch": ("witch", "mage", "wizard", "sorcer", "warlock", "shaman", "巫", "法師", "術士"),
    "ghost": ("ghost", "wraith", "spirit", "phantom", "specter", "shade", "鬼", "幽靈", "亡靈"),
    "knight": ("knight", "guard", "soldier", "warden", "captain", "paladin", "騎士", "衛", "士兵"),
    "bandit": ("bandit", "thug", "thief", "rogue", "brigand", "raider", "pirate", "賊", "盜", "海盜"),
    "demon": ("demon", "devil", "fiend", "hellspawn", "balor", "魔", "惡魔"),
    "slime": ("slime", "ooze", "jelly", "blob", "史萊姆"),
    "bear": ("bear", "boar", "beast", "熊", "野豬"),
}

# body parts for procedurally generated one-off creatures
_EYES = ("◉  ◉", "✦  ✦", "●  ●", "▰  ▰", "ø  ø", "☉  ☉", "•  •")
_MOUTHS = ("⌄", "▽", "ωω", "═══", "‸‸‸", "▼", "~~~")
_CROWNS = (" ,^^^, ", " /\\/\\ ", " ~~~~~ ", " .---. ", " \\\\|// ", " _____ ")
_SIDES = ("(", "[", "<", "|")
_FEET = (" /|  |\\ ", " (_)(_) ", "  w  w  ", " ~~~~~~ ", "  ^  ^  ")


def _generate(name: str) -> str:
    """Deterministic little creature from the enemy's name hash."""
    h = hashlib.sha256(name.encode("utf-8")).digest()
    eyes = _EYES[h[0] % len(_EYES)]
    mouth = _MOUTHS[h[1] % len(_MOUTHS)]
    crown = _CROWNS[h[2] % len(_CROWNS)]
    lb = _SIDES[h[3] % len(_SIDES)]
    rb = {"(": ")", "[": "]", "<": ">", "|": "|"}[lb]
    feet = _FEET[h[4] % len(_FEET)]
    return (f"\n{{d}}{crown}{{r}}\n"
            f"{{c}}{lb}       {rb}{{r}}\n"
            f"{{c}}{lb} {{r}}{eyes}{{c}} {rb}{{r}}\n"
            f"{{c}}{lb}  {mouth:^5} {rb}{{r}}\n"
            f"{{d}}{feet}{{r}}")


_GEN_COLORS = (ui.MOSS, ui.ARCANE, ui.EMBER, ui.GOLD, ui.BLOOD, ui.PARCHMENT)


def _archetype(name: str) -> str | None:
    low = name.lower()
    for arch, words in KEYWORDS.items():
        if any(w in low for w in words):
            return arch
    return None


def _load_stored(name: str) -> str | None:
    try:
        with sqlite3.connect(db.DB_PATH) as c:
            c.execute("CREATE TABLE IF NOT EXISTS enemy_art "
                      "(name TEXT PRIMARY KEY, art TEXT NOT NULL)")
            row = c.execute("SELECT art FROM enemy_art WHERE name=?",
                            (name.lower(),)).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def _store(name: str, art: str) -> None:
    try:
        with sqlite3.connect(db.DB_PATH) as c:
            c.execute("CREATE TABLE IF NOT EXISTS enemy_art "
                      "(name TEXT PRIMARY KEY, art TEXT NOT NULL)")
            c.execute("INSERT OR REPLACE INTO enemy_art (name, art) VALUES (?,?)",
                      (name.lower(), art))
    except sqlite3.Error:
        pass


def art_for(name: str) -> str:
    """Rendered ANSI art for an enemy name — preset, or generated-and-stored."""
    arch = _archetype(name)
    if arch:
        color, art = PRESETS[arch]
    else:
        art = _load_stored(name)
        if art is None:
            art = _generate(name)
            _store(name, art)
        h = hashlib.sha256(name.encode("utf-8")).digest()
        color = _GEN_COLORS[h[5] % len(_GEN_COLORS)]
    return art.format(c=color, d=ui.SHADOW, r=ui.RESET).strip("\n")
