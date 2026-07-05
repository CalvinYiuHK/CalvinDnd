"""db.py — SQLite persistence for characters, stats, inventory, and saves.

Everything the game needs to survive a restart lives here:
  * characters   — identity, level, HP, gold, XP, and the six ability scores
  * inventory    — items a character is carrying
  * event_log    — a running journal of rolls and story beats
  * conversation — the serialized GM message history, for resuming a session
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.environ.get("TAVERN_DB", os.path.join(os.path.dirname(__file__), "tavern.db"))

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call every launch."""
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS characters (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                race       TEXT,
                class      TEXT,
                level      INTEGER NOT NULL DEFAULT 1,
                max_hp     INTEGER NOT NULL DEFAULT 10,
                hp         INTEGER NOT NULL DEFAULT 10,
                gold       INTEGER NOT NULL DEFAULT 0,
                xp         INTEGER NOT NULL DEFAULT 0,
                str        INTEGER NOT NULL DEFAULT 10,
                dex        INTEGER NOT NULL DEFAULT 10,
                con        INTEGER NOT NULL DEFAULT 10,
                int        INTEGER NOT NULL DEFAULT 10,
                wis        INTEGER NOT NULL DEFAULT 10,
                cha        INTEGER NOT NULL DEFAULT 10,
                lang       TEXT NOT NULL DEFAULT 'en',
                scenario   TEXT NOT NULL DEFAULT 'tavern',
                premise    TEXT NOT NULL DEFAULT '',
                rerolls    INTEGER NOT NULL DEFAULT 3,
                power_rolls INTEGER NOT NULL DEFAULT 1,
                attr_points INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inventory (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                item         TEXT NOT NULL,
                qty          INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS event_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                kind         TEXT NOT NULL,
                content      TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS conversation (
                character_id INTEGER PRIMARY KEY,
                messages     TEXT NOT NULL,
                updated_at   TEXT NOT NULL,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS equipment (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                name         TEXT NOT NULL,
                slot         TEXT NOT NULL DEFAULT 'trinket',
                rarity       TEXT NOT NULL DEFAULT 'normal',
                bonuses      TEXT NOT NULL DEFAULT '{}',
                abilities    TEXT NOT NULL DEFAULT '[]',
                equipped     INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS enemies (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                name         TEXT NOT NULL,
                level        INTEGER NOT NULL DEFAULT 1,
                attrs        TEXT NOT NULL DEFAULT '{}',
                hp           INTEGER NOT NULL,
                max_hp       INTEGER NOT NULL,
                armor        INTEGER NOT NULL DEFAULT 0,
                gear         TEXT NOT NULL DEFAULT '[]',
                skills       TEXT NOT NULL DEFAULT '[]',
                icon         TEXT NOT NULL DEFAULT '',
                active       INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS skills (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                name         TEXT NOT NULL,
                attrs        TEXT NOT NULL DEFAULT '["str"]',
                dice         TEXT NOT NULL DEFAULT '1d6',
                descr        TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            );
            """
        )
        # Migrations for databases created before newer columns existed.
        cols = {r["name"] for r in c.execute("PRAGMA table_info(characters)")}
        for col, decl in (("lang", "TEXT NOT NULL DEFAULT 'en'"),
                          ("scenario", "TEXT NOT NULL DEFAULT 'tavern'"),
                          ("premise", "TEXT NOT NULL DEFAULT ''"),
                          ("rerolls", "INTEGER NOT NULL DEFAULT 3"),
                          ("power_rolls", "INTEGER NOT NULL DEFAULT 1"),
                          ("attr_points", "INTEGER NOT NULL DEFAULT 0")):
            if col not in cols:
                c.execute(f"ALTER TABLE characters ADD COLUMN {col} {decl}")
        ecols = {r["name"] for r in c.execute("PRAGMA table_info(enemies)")}
        if ecols and "icon" not in ecols:
            c.execute("ALTER TABLE enemies ADD COLUMN icon TEXT NOT NULL DEFAULT ''")


# ---------------------------------------------------------------- characters --

def create_character(name: str, race: str, char_class: str, abilities: dict,
                     max_hp: int, gold: int = 0, lang: str = "en",
                     scenario: str = "tavern", premise: str = "") -> int:
    ts = _now()
    with _conn() as c:
        cur = c.execute(
            f"""INSERT INTO characters
                (name, race, class, level, max_hp, hp, gold, xp,
                 {', '.join(ABILITIES)}, lang, scenario, premise,
                 created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,{','.join('?' * 6)},?,?,?,?,?)""",
            (name, race, char_class, 1, max_hp, max_hp, gold, 0,
             *[int(abilities[a]) for a in ABILITIES], lang, scenario, premise,
             ts, ts),
        )
        return cur.lastrowid


def adjust_resources(character_id: int, rerolls: int = 0, power_rolls: int = 0) -> dict:
    """Apply deltas to the dice-token pools, clamped to [0, 9] each."""
    char = get_character(character_id)
    if char is None:
        raise ValueError(f"no character with id {character_id}")
    new_r = max(0, min(9, char.get("rerolls", 0) + rerolls))
    new_p = max(0, min(9, char.get("power_rolls", 0) + power_rolls))
    with _conn() as c:
        c.execute("UPDATE characters SET rerolls=?, power_rolls=?, updated_at=? WHERE id=?",
                  (new_r, new_p, _now(), character_id))
    return get_character(character_id)


def delete_character(character_id: int) -> None:
    """Delete a hero and everything attached (inventory, log, conversation)."""
    with _conn() as c:
        c.execute("DELETE FROM characters WHERE id=?", (character_id,))


def get_setting(key: str, default: str = "") -> str:
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO settings (key, value) VALUES (?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def set_language(character_id: int, lang: str) -> None:
    with _conn() as c:
        c.execute("UPDATE characters SET lang=?, updated_at=? WHERE id=?",
                  (lang, _now(), character_id))


def get_character(character_id: int) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone()
    return dict(row) if row else None


def list_characters() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM characters ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def xp_for_next(level: int) -> int:
    """Total XP needed to reach the next level.

    A gentle triangular curve — 100, 300, 600, 1000, ... — so a level-up
    lands every handful of scenes at typical 10-50 XP story grants.
    """
    return 50 * level * (level + 1)


def adjust_character(character_id: int, *, hp: int = 0, gold: int = 0, xp: int = 0,
                     level: Optional[int] = None, max_hp: Optional[int] = None) -> dict:
    """Apply deltas (hp/gold/xp) and optional absolute sets (level/max_hp).

    HP is clamped to [0, max_hp]; gold and xp are clamped at 0. When gained XP
    crosses the curve (and no absolute level was set), the engine auto-levels:
    +5 max HP, a full heal, and +1 reroll & +1 power token per level. The
    returned row carries "_leveled_up": <levels gained>.
    """
    char = get_character(character_id)
    if char is None:
        raise ValueError(f"no character with id {character_id}")

    new_max_hp = max_hp if max_hp is not None else char["max_hp"]
    new_hp = max(0, min(new_max_hp, char["hp"] + hp))
    new_gold = max(0, char["gold"] + gold)
    new_xp = max(0, char["xp"] + xp)
    new_level = level if level is not None else char["level"]

    leveled = 0
    if level is None:
        while new_xp >= xp_for_next(new_level):
            new_level += 1
            new_max_hp += 5
            leveled += 1
        if leveled:
            new_hp = new_max_hp  # level-up comes with a full heal

    with _conn() as c:
        c.execute(
            """UPDATE characters
               SET hp=?, max_hp=?, gold=?, xp=?, level=?, updated_at=?
               WHERE id=?""",
            (new_hp, new_max_hp, new_gold, new_xp, new_level, _now(), character_id),
        )
    if leveled:
        adjust_resources(character_id, rerolls=leveled, power_rolls=leveled)
        with _conn() as c:
            c.execute("UPDATE characters SET attr_points = attr_points + ? WHERE id=?",
                      (4 * leveled, character_id))
    result = get_character(character_id)
    result["_leveled_up"] = leveled
    return result


# ----------------------------------------------------------------- inventory --

def get_inventory(character_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT item, qty FROM inventory WHERE character_id=? ORDER BY item",
            (character_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_item(character_id: int, item: str, qty: int = 1) -> list[dict]:
    item = item.strip()
    with _conn() as c:
        row = c.execute(
            "SELECT id, qty FROM inventory WHERE character_id=? AND item=? COLLATE NOCASE",
            (character_id, item),
        ).fetchone()
        if row:
            c.execute("UPDATE inventory SET qty=? WHERE id=?", (row["qty"] + qty, row["id"]))
        else:
            c.execute(
                "INSERT INTO inventory (character_id, item, qty) VALUES (?,?,?)",
                (character_id, item, max(1, qty)),
            )
    return get_inventory(character_id)


def remove_item(character_id: int, item: str, qty: int = 1) -> list[dict]:
    with _conn() as c:
        row = c.execute(
            "SELECT id, qty FROM inventory WHERE character_id=? AND item=? COLLATE NOCASE",
            (character_id, item.strip()),
        ).fetchone()
        if row:
            remaining = row["qty"] - qty
            if remaining > 0:
                c.execute("UPDATE inventory SET qty=? WHERE id=?", (remaining, row["id"]))
            else:
                c.execute("DELETE FROM inventory WHERE id=?", (row["id"],))
    return get_inventory(character_id)


# ------------------------------------------------------------------ logging ---

def log_event(character_id: int, kind: str, content: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO event_log (character_id, kind, content, created_at) VALUES (?,?,?,?)",
            (character_id, kind, content, _now()),
        )


def get_log(character_id: int, limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT kind, content, created_at FROM event_log "
            "WHERE character_id=? ORDER BY id DESC LIMIT ?",
            (character_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ------------------------------------------------------- conversation saves ---

def save_conversation(character_id: int, messages) -> None:
    """Persist session state (any JSON-serializable value — e.g. the claude
    CLI session id as {"session_id": ...})."""
    with _conn() as c:
        c.execute(
            """INSERT INTO conversation (character_id, messages, updated_at)
               VALUES (?,?,?)
               ON CONFLICT(character_id)
               DO UPDATE SET messages=excluded.messages, updated_at=excluded.updated_at""",
            (character_id, json.dumps(messages), _now()),
        )


def load_conversation(character_id: int):
    with _conn() as c:
        row = c.execute(
            "SELECT messages FROM conversation WHERE character_id=?", (character_id,)
        ).fetchone()
    return json.loads(row["messages"]) if row else []


# ------------------------------------------------------ progression: gear ----

RARITIES = ("normal", "uncommon", "rare", "epic", "legendary")
# maximum special abilities an item of each rarity may carry
RARITY_ABILITY_CAP = {"normal": 0, "uncommon": 0, "rare": 1, "epic": 3, "legendary": 5}
GEAR_SLOTS = ("weapon", "armor", "trinket")

STAT_CAP = 24  # ability scores can't be raised past this


def add_equipment(character_id: int, name: str, slot: str, rarity: str,
                  bonuses: dict, abilities: list[str]) -> dict:
    """Add a piece of gear; auto-equips if its slot is empty."""
    slot = slot if slot in GEAR_SLOTS else "trinket"
    rarity = rarity if rarity in RARITIES else "normal"
    abilities = list(abilities)[: RARITY_ABILITY_CAP[rarity]]
    bonuses = {k: int(v) for k, v in bonuses.items() if k in ABILITIES and int(v)}
    with _conn() as c:
        taken = c.execute(
            "SELECT 1 FROM equipment WHERE character_id=? AND slot=? AND equipped=1",
            (character_id, slot)).fetchone()
        cur = c.execute(
            "INSERT INTO equipment (character_id, name, slot, rarity, bonuses, "
            "abilities, equipped) VALUES (?,?,?,?,?,?,?)",
            (character_id, name.strip(), slot, rarity, json.dumps(bonuses),
             json.dumps(abilities), 0 if taken else 1))
        eid = cur.lastrowid
    return get_equipment_item(eid)


def get_equipment_item(equipment_id: int) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM equipment WHERE id=?", (equipment_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["bonuses"] = json.loads(d["bonuses"])
    d["abilities"] = json.loads(d["abilities"])
    d["equipped"] = bool(d["equipped"])
    return d


def list_equipment(character_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM equipment WHERE character_id=? "
            "ORDER BY equipped DESC, id", (character_id,)).fetchall()
    return [get_equipment_item(r["id"]) for r in rows]


def equip_item(character_id: int, equipment_id: int) -> Optional[dict]:
    """Equip an owned item, unequipping whatever holds its slot."""
    item = get_equipment_item(equipment_id)
    if item is None or item["character_id"] != character_id:
        return None
    with _conn() as c:
        c.execute("UPDATE equipment SET equipped=0 WHERE character_id=? AND slot=?",
                  (character_id, item["slot"]))
        c.execute("UPDATE equipment SET equipped=1 WHERE id=?", (equipment_id,))
    return get_equipment_item(equipment_id)


def equipment_bonuses(character_id: int) -> dict:
    """Aggregate ability bonuses from all equipped gear, e.g. {'str': 2}."""
    total: dict = {}
    for item in list_equipment(character_id):
        if item["equipped"]:
            for k, v in item["bonuses"].items():
                total[k] = total.get(k, 0) + v
    return total


# ----------------------------------------------------- progression: skills ---

def max_skill_slots(level: int) -> int:
    """Skill slots: 3 at level 1, +1 every two levels."""
    return 3 + max(0, level - 1) // 2


def add_skill(character_id: int, name: str, attrs: list[str], dice_notation: str,
              descr: str = "") -> Optional[dict]:
    """Learn a skill. Returns None if all skill slots are full."""
    char = get_character(character_id)
    existing = list_skills(character_id)
    if len(existing) >= max_skill_slots(char["level"]):
        return None
    attrs = [a for a in attrs if a in ABILITIES][:2] or ["str"]
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO skills (character_id, name, attrs, dice, descr) "
            "VALUES (?,?,?,?,?)",
            (character_id, name.strip(), json.dumps(attrs), dice_notation, descr))
        sid = cur.lastrowid
    return get_skill(sid)


def get_skill(skill_id: int) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["attrs"] = json.loads(d["attrs"])
    return d


def list_skills(character_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT id FROM skills WHERE character_id=? ORDER BY id",
                         (character_id,)).fetchall()
    return [get_skill(r["id"]) for r in rows]


def remove_skill(character_id: int, skill_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM skills WHERE id=? AND character_id=?",
                        (skill_id, character_id))
    return cur.rowcount > 0


# ------------------------------------------------ progression: attr points ---

def spend_attr_points(character_id: int, allocation: dict) -> dict:
    """Spend saved attribute points, +1 per point, capped at STAT_CAP.

    `allocation` maps ability -> points, e.g. {"str": 2, "con": 2}.
    Raises ValueError on overspend, unknown ability, or cap violations.
    """
    char = get_character(character_id)
    total = sum(int(v) for v in allocation.values())
    if total < 1:
        raise ValueError("nothing to allocate")
    if total > char.get("attr_points", 0):
        raise ValueError(f"only {char.get('attr_points', 0)} points available")
    sets, vals = [], []
    for ab, pts in allocation.items():
        ab = ab.lower()
        if ab not in ABILITIES:
            raise ValueError(f"unknown ability {ab!r}")
        pts = int(pts)
        if pts < 0:
            raise ValueError("points must be positive")
        if char[ab] + pts > STAT_CAP:
            raise ValueError(f"{ab.upper()} would exceed the cap of {STAT_CAP}")
        sets.append(f"{ab} = {ab} + ?")
        vals.append(pts)
    with _conn() as c:
        c.execute(
            f"UPDATE characters SET {', '.join(sets)}, attr_points = attr_points - ?, "
            f"updated_at = ? WHERE id = ?",
            (*vals, total, _now(), character_id))
    return get_character(character_id)


# ------------------------------------------------------------------ combat ---

def enemy_max_hp(level: int, con_mod: int) -> int:
    """Enemy HP formula: 10 + 6x(level-1) + 2xCON_mod, minimum 4."""
    return max(4, 10 + 6 * (level - 1) + 2 * con_mod)


def damage_total(dice_total: int, attr_mod: int, attacker_level: int,
                 defender_armor: int) -> int:
    """The damage formula, both directions:

        damage = dice + attr_mod + attacker_level//2 - defender_armor, min 1
    """
    return max(1, dice_total + attr_mod + attacker_level // 2 - defender_armor)


def hero_armor(character_id: int) -> int:
    """Hero damage reduction: total bonus points on the equipped armor item."""
    for e in list_equipment(character_id):
        if e["equipped"] and e["slot"] == "armor":
            return sum(abs(v) for v in e["bonuses"].values())
    return 0


def add_enemy(character_id: int, name: str, level: int, attrs: dict,
              gear: list[str], skills: list[str], armor: Optional[int] = None,
              icon: str = "") -> dict:
    attrs = {a: int(attrs.get(a, 10)) for a in ABILITIES}
    con_mod = (attrs["con"] - 10) // 2
    hp = enemy_max_hp(level, con_mod)
    if armor is None:
        armor = level // 3
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO enemies (character_id, name, level, attrs, hp, max_hp, "
            "armor, gear, skills, icon, active) VALUES (?,?,?,?,?,?,?,?,?,?,1)",
            (character_id, name.strip(), max(1, level), json.dumps(attrs),
             hp, hp, max(0, armor), json.dumps(gear), json.dumps(skills),
             icon.strip().lower()))
        eid = cur.lastrowid
    return get_enemy(eid)


def get_enemy(enemy_id: int) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM enemies WHERE id=?", (enemy_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["attrs"] = json.loads(d["attrs"])
    d["gear"] = json.loads(d["gear"])
    d["skills"] = json.loads(d["skills"])
    d["active"] = bool(d["active"])
    return d


def list_enemies(character_id: int, active_only: bool = True) -> list[dict]:
    q = "SELECT id FROM enemies WHERE character_id=?"
    if active_only:
        q += " AND active=1"
    with _conn() as c:
        rows = c.execute(q + " ORDER BY id", (character_id,)).fetchall()
    return [get_enemy(r["id"]) for r in rows]


def find_enemy(character_id: int, name: str) -> Optional[dict]:
    """Active enemy by (partial, case-insensitive) name; falls back to first."""
    active = list_enemies(character_id)
    if not active:
        return None
    name = (name or "").strip().lower()
    for e in active:
        if name and name in e["name"].lower():
            return e
    return active[0]


def damage_enemy(enemy_id: int, amount: int) -> dict:
    """Apply damage; at 0 HP the enemy is marked defeated (inactive)."""
    e = get_enemy(enemy_id)
    new_hp = max(0, e["hp"] - max(0, amount))
    with _conn() as c:
        c.execute("UPDATE enemies SET hp=?, active=? WHERE id=?",
                  (new_hp, 0 if new_hp == 0 else 1, enemy_id))
    return get_enemy(enemy_id)


def end_encounter(character_id: int) -> int:
    """Deactivate all enemies (fled / spared / scene over). Returns count."""
    with _conn() as c:
        cur = c.execute("UPDATE enemies SET active=0 WHERE character_id=? AND active=1",
                        (character_id,))
    return cur.rowcount
