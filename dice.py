"""dice.py — dice roller for the tavern game.

Parses standard tabletop dice notation and returns structured results so the
game master (and the game loop) can both roll and *show its work*.

Supported notation (case-insensitive, whitespace ignored):
    d20              one twenty-sided die
    2d6              two six-sided dice
    2d6+3            with a flat modifier
    1d8-1            negative modifier
    3d6+1d4+2        multiple dice terms plus a modifier
    4d6dl1           roll 4d6, drop the lowest 1 (used for ability scores)
    2d20kh1          roll 2d20, keep highest 1 (advantage)
    2d20kl1          roll 2d20, keep lowest 1 (disadvantage)

CLI:
    python dice.py 2d6+3
    python dice.py d20 --advantage
    python dice.py --ability      # roll a full 4d6-drop-lowest ability line
"""

from __future__ import annotations

import argparse
import random
import re
import secrets
from dataclasses import dataclass, field, asdict
from typing import List

# Use a cryptographically-seeded RNG so rolls aren't predictable across runs.
_rng = random.Random(secrets.randbits(128))

# One "NdMkhX / NdMdlX" style term, or a bare modifier like "+3".
_TERM_RE = re.compile(
    r"(?P<sign>[+-]?)\s*"
    r"(?:(?P<count>\d*)d(?P<sides>\d+)(?P<keep>(?:kh|kl|dh|dl)\d+)?|(?P<flat>\d+))",
    re.IGNORECASE,
)


@dataclass
class DieGroup:
    count: int
    sides: int
    rolls: List[int]
    kept: List[int]
    dropped: List[int] = field(default_factory=list)
    keep_rule: str = ""

    @property
    def subtotal(self) -> int:
        return sum(self.kept)


@dataclass
class RollResult:
    notation: str
    groups: List[DieGroup]
    modifier: int
    total: int
    crit: bool = False       # natural 20 on a lone d20
    fumble: bool = False     # natural 1 on a lone d20

    def to_dict(self) -> dict:
        return {
            "notation": self.notation,
            "total": self.total,
            "modifier": self.modifier,
            "crit": self.crit,
            "fumble": self.fumble,
            "groups": [asdict(g) for g in self.groups],
            "detail": self.detail(),
        }

    def detail(self) -> str:
        """Human-readable breakdown, e.g. '2d6 [4, 5] + 3 = 12'."""
        body = ""
        for i, g in enumerate(self.groups):
            shown = ", ".join(str(r) for r in g.rolls)
            note = ""
            if g.dropped:
                note = f" (drop {', '.join(str(d) for d in g.dropped)})"
            term = f"{g.count}d{g.sides} [{shown}]{note}"
            neg = g.subtotal < 0  # a subtracted dice term
            if i == 0:
                body = f"{'-' if neg else ''}{term}"
            else:
                body += f" {'-' if neg else '+'} {term}"
        if not self.groups:
            body = "0"
        if self.modifier:
            body += f" {'+' if self.modifier >= 0 else '-'} {abs(self.modifier)}"
        tag = ""
        if self.crit:
            tag = "  ** CRITICAL! **"
        elif self.fumble:
            tag = "  ** FUMBLE! **"
        return f"{body} = {self.total}{tag}"


def _apply_keep(rolls: List[int], keep_rule: str) -> tuple[List[int], List[int]]:
    """Return (kept, dropped) given a rule like 'kh1', 'kl1', 'dl1', 'dh2'."""
    if not keep_rule:
        return list(rolls), []
    kind = keep_rule[:2].lower()
    n = int(keep_rule[2:])
    ordered = sorted(rolls)
    if kind == "kh":       # keep highest n
        kept_set = ordered[-n:]
    elif kind == "kl":     # keep lowest n
        kept_set = ordered[:n]
    elif kind == "dl":     # drop lowest n
        kept_set = ordered[n:]
    elif kind == "dh":     # drop highest n
        kept_set = ordered[:-n] if n else ordered
    else:
        return list(rolls), []
    # Preserve original roll order in `kept`; compute dropped as the remainder.
    kept, dropped, pool = [], [], list(kept_set)
    for r in rolls:
        if r in pool:
            kept.append(r)
            pool.remove(r)
        else:
            dropped.append(r)
    return kept, dropped


def roll(notation: str, advantage: bool = False, disadvantage: bool = False) -> RollResult:
    """Roll `notation` and return a RollResult. Raises ValueError on bad input."""
    if advantage and disadvantage:
        advantage = disadvantage = False  # they cancel
    if advantage:
        notation = "2d20kh1"
    elif disadvantage:
        notation = "2d20kl1"

    raw = notation.replace(" ", "")
    if not raw:
        raise ValueError("empty dice notation")

    groups: List[DieGroup] = []
    modifier = 0
    consumed = 0
    for m in _TERM_RE.finditer(raw):
        if m.start() != consumed:
            raise ValueError(f"could not parse dice notation: {notation!r}")
        consumed = m.end()
        sign = -1 if m.group("sign") == "-" else 1
        if m.group("flat") is not None:
            modifier += sign * int(m.group("flat"))
            continue
        count = int(m.group("count") or 1)
        sides = int(m.group("sides"))
        if count < 1 or count > 1000 or sides < 1 or sides > 1000:
            raise ValueError(f"unreasonable dice term: {m.group(0)!r}")
        rolls = [_rng.randint(1, sides) for _ in range(count)]
        kept, dropped = _apply_keep(rolls, m.group("keep") or "")
        # A negative sign in front of a dice term subtracts its result.
        if sign == -1:
            kept = [-k for k in kept]
        groups.append(
            DieGroup(count=count, sides=sides, rolls=rolls, kept=[abs(k) for k in kept]
                     if sign == 1 else kept, dropped=dropped, keep_rule=m.group("keep") or "")
        )

    if consumed != len(raw):
        raise ValueError(f"trailing characters in dice notation: {notation!r}")

    total = sum(g.subtotal for g in groups) + modifier

    # Crit / fumble only make sense for a single, unmodified d20.
    crit = fumble = False
    if (len(groups) == 1 and groups[0].sides == 20 and groups[0].count == 1
            and not groups[0].keep_rule):
        nat = groups[0].rolls[0]
        crit = nat == 20
        fumble = nat == 1

    return RollResult(notation=notation, groups=groups, modifier=modifier,
                      total=total, crit=crit, fumble=fumble)


def roll_ability() -> dict:
    """Roll one ability score: 4d6, drop the lowest. Returns {score, detail}."""
    r = roll("4d6dl1")
    return {"score": r.total, "detail": r.detail()}


def _main() -> None:
    ap = argparse.ArgumentParser(description="Roll some dice.")
    ap.add_argument("notation", nargs="?", default="d20", help="e.g. 2d6+3")
    ap.add_argument("--advantage", action="store_true", help="roll 2d20 keep highest")
    ap.add_argument("--disadvantage", action="store_true", help="roll 2d20 keep lowest")
    ap.add_argument("--ability", action="store_true",
                    help="roll a full set of six 4d6-drop-lowest ability scores")
    args = ap.parse_args()

    if args.ability:
        names = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
        for n in names:
            a = roll_ability()
            print(f"{n}: {a['score']:>2}   ({a['detail']})")
        return

    try:
        result = roll(args.notation, advantage=args.advantage,
                      disadvantage=args.disadvantage)
    except ValueError as e:
        raise SystemExit(f"error: {e}")
    print(result.detail())


if __name__ == "__main__":
    _main()
