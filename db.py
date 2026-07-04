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
            """
        )
        # Migrations for databases created before newer columns existed.
        cols = {r["name"] for r in c.execute("PRAGMA table_info(characters)")}
        for col, decl in (("lang", "TEXT NOT NULL DEFAULT 'en'"),
                          ("scenario", "TEXT NOT NULL DEFAULT 'tavern'"),
                          ("premise", "TEXT NOT NULL DEFAULT ''"),
                          ("rerolls", "INTEGER NOT NULL DEFAULT 3"),
                          ("power_rolls", "INTEGER NOT NULL DEFAULT 1")):
            if col not in cols:
                c.execute(f"ALTER TABLE characters ADD COLUMN {col} {decl}")


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


def adjust_character(character_id: int, *, hp: int = 0, gold: int = 0, xp: int = 0,
                     level: Optional[int] = None, max_hp: Optional[int] = None) -> dict:
    """Apply deltas (hp/gold/xp) and optional absolute sets (level/max_hp).

    HP is clamped to [0, max_hp]; gold and xp are clamped at 0.
    Returns the updated character row.
    """
    char = get_character(character_id)
    if char is None:
        raise ValueError(f"no character with id {character_id}")

    new_max_hp = max_hp if max_hp is not None else char["max_hp"]
    new_hp = max(0, min(new_max_hp, char["hp"] + hp))
    new_gold = max(0, char["gold"] + gold)
    new_xp = max(0, char["xp"] + xp)
    new_level = level if level is not None else char["level"]

    with _conn() as c:
        c.execute(
            """UPDATE characters
               SET hp=?, max_hp=?, gold=?, xp=?, level=?, updated_at=?
               WHERE id=?""",
            (new_hp, new_max_hp, new_gold, new_xp, new_level, _now(), character_id),
        )
    return get_character(character_id)


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
