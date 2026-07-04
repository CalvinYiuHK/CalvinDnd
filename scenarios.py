"""scenarios.py — story presets for Fateweaver.

Each scenario defines the world the GM runs: a premise paragraph that goes
into the system prompt, the identity options offered at character creation,
a starting kit, and the opening-scene instruction. The dice, stats, and
choice mechanics are universal — STR/DEX/CON/INT/WIS/CHA read as fitness,
coordination, stamina, smarts, judgement, and charm in any setting.
"""

SCENARIOS = {
    "tavern": {
        "title": "The Tavern Cellar",
        "emoji": "🍺",
        "tagline": "classic fantasy — a smoky tavern, a thumping cellar, a secret",
        "premise": (
            "Tonight's story is classic fantasy. It begins in a lively, smoky "
            "tavern run by Old Greg, a one-eyed barkeep who knows more than he "
            "pours. Something thumps beneath the floorboards, adventurers "
            "trade rumors, and the road outside leads anywhere — dungeons, "
            "forests, courts, and stranger places. Magic is real, danger is "
            "real, and gold buys ale."
        ),
        "races": ["Human", "Elf", "Dwarf", "Halfling", "Half-Orc", "Tiefling", "Gnome"],
        "roles": ["Fighter", "Rogue", "Wizard", "Cleric", "Ranger", "Bard", "Barbarian"],
        "kit": [("Traveler's clothes", 1), ("Bedroll", 1), ("Rations", 3)],
        "gold_dice": ("3d6", 5),  # 3d6 x5 gold
        "opener": "has just pushed open the door of the tavern. Set the scene "
                  "vividly and finish with the three choice options.",
    },
    "school": {
        "title": "School Days",
        "emoji": "🏫",
        "tagline": "modern school life — friendships, rivals, exams, secrets",
        "premise": (
            "Tonight's story is modern school life — corridors, cliques, "
            "canteen politics, club rooms, exams, festivals, and the small "
            "dramas that feel enormous. Play it warm, funny, and real, with "
            "occasional mysteries worth chasing. There is no magic; stakes are "
            "social, academic, and personal. Treat HP as energy and morale, "
            "and gold as pocket money in dollars."
        ),
        "races": None,
        "roles": ["Transfer Student", "Team Captain", "Honor Student",
                  "Class Clown", "Art Kid", "Student Council", "Quiet Observer"],
        "kit": [("School bag", 1), ("Phone", 1), ("Instant noodles", 2)],
        "gold_dice": ("3d6", 10),
        "opener": "arrives at the school gate on the first day of a new term. "
                  "Set the scene and finish with the three choice options.",
    },
    "work": {
        "title": "Nine to Five",
        "emoji": "💼",
        "tagline": "office survival — deadlines, politics, one weird manager",
        "premise": (
            "Tonight's story is workplace drama — open-plan desks, deadlines, "
            "office politics, a printer that hates everyone, and a career to "
            "build or burn. Play it sharp and comedic with real stakes: "
            "promotions, layoffs, rivalries, maybe a company secret. No magic; "
            "treat HP as energy and stress resilience, and gold as money in "
            "dollars."
        ),
        "races": None,
        "roles": ["New Hire", "Middle Manager", "Sales Shark", "IT Gremlin",
                  "HR Diplomat", "Intern", "Founder's Nephew"],
        "kit": [("Laptop", 1), ("Coffee", 1), ("Lanyard", 1)],
        "gold_dice": ("3d6", 20),
        "opener": "badges into the office on a Monday that will not be normal. "
                  "Set the scene and finish with the three choice options.",
    },
    "travel": {
        "title": "The Long Way Home",
        "emoji": "✈️",
        "tagline": "backpacking adventure — strangers, detours, near-misses",
        "premise": (
            "Tonight's story is a backpacking adventure — night buses, hostels, "
            "street food, missed connections, generous strangers, and choices "
            "that turn a trip into a story. Keep the world real (no magic) but "
            "full of coincidence and wonder. Treat HP as health and stamina on "
            "the road, and gold as travel money in dollars."
        ),
        "races": None,
        "roles": ["Backpacker", "Photographer", "Food Hunter", "Digital Nomad",
                  "Gap-Year Wanderer", "Language Nerd"],
        "kit": [("Backpack", 1), ("Passport", 1), ("Camera", 1), ("Snacks", 2)],
        "gold_dice": ("3d6", 20),
        "opener": "steps off a delayed flight in a city they've never seen, "
                  "with one bag and no plan. Set the scene and finish with the "
                  "three choice options.",
    },
    "oldself": {
        "title": "The Old Self",
        "emoji": "⏪",
        "tagline": "wake up younger — same memories, second chances",
        "premise": (
            "Tonight's story is a second-chance drama: the hero wakes up as "
            "their younger self — same room they grew up in, same faces, but "
            "with every adult memory intact. School, family, old friends, old "
            "regrets: everything can be done differently this time, and small "
            "changes ripple. Play it bittersweet, funny, and sincere. No magic "
            "beyond the mystery of the return itself. Treat HP as energy and "
            "emotional resilience, and gold as pocket money in dollars."
        ),
        "races": None,
        "roles": ["Regretful Office Worker", "Retired Athlete", "Burned-out Doctor",
                  "Failed Musician", "Divorced Chef", "Laid-off Engineer"],
        "kit": [("Old schoolbag", 1), ("A photo you don't remember taking", 1)],
        "gold_dice": ("3d6", 5),
        "opener": "wakes to a childhood alarm clock, sixteen again, with every "
                  "memory of the life they already lived. Set the scene and "
                  "finish with the three choice options.",
    },
    "custom": {
        "title": "Your Own Story",
        "emoji": "✍️",
        "tagline": "type any premise — the GM builds the world around it",
        "premise": "",  # filled from the player's own text at creation
        "races": None,
        "roles": ["Protagonist"],
        "kit": [("A few belongings", 1)],
        "gold_dice": ("3d6", 10),
        "opener": "steps into the first scene. Set it vividly and finish with "
                  "the three choice options.",
    },
}

ORDER = ["tavern", "school", "work", "travel", "oldself", "custom"]
