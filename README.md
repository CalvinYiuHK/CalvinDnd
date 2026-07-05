# Fateweaver 🎲

**Any story, real dice.** A terminal adventure game with an AI Game Master —
pick a story (fantasy tavern, school life, office drama, backpacking, waking up
as your younger self, or anything you type), create a hero, and play by talking
or by picking from three trait-tagged options each turn. Claude **Opus** runs
the entire plot as GM through the `claude` CLI — no API key, your Claude Code
login is enough.

What keeps it honest: the GM doesn't make up numbers. Checks resolve **D&D
5e-style** — d20 + ability modifier (+ proficiency) against a DC — rolled by a
real dice engine, with stats in a real **SQLite** database. The model narrates;
the code is the truth.

## Quick start

Requirements: Python 3.10+, and [Claude Code](https://claude.com/claude-code)
installed and logged in (`claude` on your PATH).

```bash
./start-web.sh            # the web app → http://127.0.0.1:8000 (needs Node.js once, to build)
./start.sh                # the clickable TUI (auto-installs textual into .venv)
./start.sh --classic      # zero-dependency classic prompt mode
```

**The web app** is the nicest way to play: a React interface (“the loom of
fate” — ink-dark, candlelit gold) with the story as an illuminated column,
every dice roll appearing as an animated d20 knot on a golden thread, three
clickable choice cards with highlighted stat badges and `need N+` targets
(each with a ⚡+10 power variant), and a sidebar with Hero / Gear / Skills /
Foes tabs — enemy ANSI art, tiered stat visibility, and live HP bars included.
Reroll offers and level-up point allocation are dialogs; hero creation is a
full wizard (story pick, race/background, stat rolling with rerolls,
English/廣東話). First run installs `fastapi`+`uvicorn` into `.venv` and
the frontend ships prebuilt, so Node/npm are not needed to play
(`REBUILD=1 ./start-web.sh` rebuilds it with npm ≥ 8).

Three switchable looks ship with it — **⟐ Loom** (ink-dark, a golden
fate-thread through the story), **☙ Grimoire** (aged parchment, oxblood
drop caps), **◈ Nightglass** (frosted glass over deep blue) — switch live
from the top bar; your pick is remembered. Player avatars are generated
per-hero (DiceBear), and foes get matching fantasy icons
(game-icons.net) beside their ANSI art.

The TUI gives you a story pane and a **tabbed sidebar — Hero / Gear / Skills /
Foes** — always in view: click gear to equip it, click a skill to use it (or
forget it), and the **Foes tab** shows every enemy's ANSI art, stats, and live
HP, grabbing focus the moment a fight starts. Choices are big clickable rows
with **highlighted stat badges** (trait chip, your modifier, and the `need N+`
target), each with a ⚡+10 power variant. Reroll offers and level-up training
are dialogs. **Three layouts** ship built-in — press F1/F2/F3 to switch live
(your pick is remembered): **Codex** (a centered book column, borderless, quiet
amber accents), **Deck** (the command table — framed story, card sidebar, and a
"fate line" pinning your latest roll above the input), **Stage** (cinematic —
one status ribbon, full-width story, sidebar appears only in combat, choices as
three cards). Enemy art: preset creatures (rats, goblins, dragons, witches,
ghosts…) matched by name — Chinese names too — and one-of-a-kind generated art
for anything new, stored so the same foe always wears the same face.

## How a turn plays

The GM narrates, then offers **three options**, each tagged with the trait it
tests and what your d20 needs to show:

```
 1  Read the runes on the trapdoor   ⚅ INT +4★ need 9+
 2  Kick the cellar door down        ⚅ STR -1  need 16+
 3  Quietly finish your drink        · no roll ·
```

Type `1`–`3` (or any freeform action). Tagged picks roll an animated d20 with
your **ability modifier** as buff/debuff — `★` marks class proficiency (+2 at
low levels, 5e scaling) — against the GM's **DC** (5 easy → 20 nearly
impossible). Natural 20 always crits; natural 1 always fumbles. Damage rolls
(`2d6+1`) follow separately, no DC.

**Dice tokens** — you start with **3 ↻ rerolls** and **1 ⚡ power roll**:
type `p2` instead of `2` to spend a power token (+10 on that roll); after a
failed check you're offered a reroll. The GM grants more as **story rewards**
(crits, clever play, milestones — `[[reward: ...]]`), capped at 9 each.

**Progression (BG3-style)** — level-ups grant **+4 attribute points you
allocate yourself**; the story drops **equipment** in five rarities
(normal → uncommon → **rare** → *epic* → **legendary**, color-coded) with stat
bonuses and — at rare and above — special abilities (rare 1, legendary up to
5); and you learn **skills** with fixed dice + your ability mods (`s1` to use
one as your action, like casting in BG3). `/gear`, `/skills`, `/train`.

**Combat** — when a fight starts the GM must stat every foe in full (level,
six attributes, armor, gear, skills); their HP comes from a formula
(`10 + 6×(level−1) + 2×CON_mod`). What *you* see scales with the level gap —
everything at their level or above (or with an inspect-type skill), then
partial → vague → silhouette. Every landed hit, both directions, prints the
full math and the target's HP bar:
`damage = dice + attr mod + level÷2 − armor (min 1)`, crits double the dice.
`/inspect` sizes up the field.

**CC mode** — play from the Claude phone app: point a Claude chat (with code
execution) at this repo and `CC_MODE.md`. Chat-Claude becomes the GM and runs
`cc.py` in its sandbox for all dice, stats, and tokens — same honest numbers,
no terminal needed.

## Stories

| Preset | Vibe |
|---|---|
| 🍺 The Tavern Cellar | classic fantasy — races, classes, a thumping cellar |
| 🏫 School Days | modern school life — friendships, rivals, exams |
| 💼 Nine to Five | office survival — deadlines, politics, secrets |
| ✈️ The Long Way Home | backpacking — strangers, detours, near-misses |
| ⏪ The Old Self | wake up sixteen again with every memory intact |
| ✍️ Your Own Story | type any premise; the GM builds the world |

The six stats read naturally everywhere: STR fitness, DEX coordination, CON
stamina, INT smarts, WIS judgement, CHA charm. HP and gold mean whatever health
and money mean in that world.

## Commands

```
/stats       character sheet (HP bar, stats, pack)
/inventory   what you're carrying
/log         recent rolls and story beats
/roll 2d6+1  roll dice yourself, outside the story
/lang        switch story language (English ↔ 廣東話)
/help        help
/quit        save and exit — pick the same hero later to resume
```

Each hero gets a **persistent Claude session** (resumed with `--resume`, cached
with the 1-hour prompt-cache TTL) — quit and return anytime; if a saved session
has expired, the game rebuilds context from your event log automatically. Story
language is per-hero: English or 廣東話 (繁體中文) with colloquial Cantonese
dialogue. Your hero's name glows gold in the narration.

## Files

| File | Role |
|------|------|
| `start-web.sh` | Web app entry point — FastAPI + built React UI |
| `server.py` | Web backend: REST + WebSocket around the same engine |
| `web/` | React frontend (Vite) — the loom-of-fate interface |
| `start.sh` | Entry point (pure stdlib — nothing to install) |
| `game.py` | Terminal loop — creation, menus, commands |
| `gm.py` | The GM: persistent `claude -p` session + directive protocol |
| `scenarios.py` | Story presets — add your own here |
| `dice.py` | Dice engine + CLI (`2d6+3`, advantage, crits) |
| `db.py` | SQLite: characters, stats, inventory, log, saves |
| `tui.py` | Clickable Textual UI — panels, buttons, battle art |
| `art.py` | Enemy ANSI art: presets + generated-and-stored |
| `ui.py` | Terminal rendering: markdown→ANSI, colors, spinner, HP bar |

## Customize

- Env vars: `TAVERN_MODEL` (default `sonnet`; try `opus` for richer storytelling), `TAVERN_EFFORT` (default `medium`; `low` = snappier),
  `TAVERN_TIMEOUT`, `TAVERN_DB`, `TAVERN_NO_ANIM=1` (skip dice animation),
  `NO_COLOR` (plain output).
- Add a story: drop a new entry in `scenarios.py` — premise, roles, kit, opener.
- Change the mechanics: the directive protocol lives in `gm.py`.
