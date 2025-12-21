# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import re
import random, time
import json
import asyncio
from pathlib import Path
import os
import psycopg
from psycopg.rows import dict_row
from typing import Dict, Any, List, Optional
from card_images import make_image_attachment # uses assets/cards/rws_stx/ etc.
MYSTERY_STATE: dict[int, dict] = {}
# ==============================
# CONFIGURATION
# ==============================
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable not found. Please set it in your host environment settings.")
    
# ==============================
# DATABASE (Render Postgres)
# ==============================
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL environment variable not found. Add your Render Postgres DATABASE_URL to this service.")

_DB_READY = False  # prevents re-creating tables multiple times

def db_connect():
    # psycopg3 will read ssl settings from DATABASE_URL if Render includes them
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def ensure_tables():
    """Create tables if they don't exist (safe to run on startup)."""
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tarot_user_prefs (
                    user_id BIGINT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
        conn.commit()
        
# ==============================
# TAROT MODES (DB-backed)
# ==============================
DEFAULT_MODE = "full"

MODE_SPECS = {
    "quick":  ["quick", "call_to_action"],
    "poetic": ["poetic_hint", "meaning", "mantra", "call_to_action"],

    "direct": ["reader_voice", "tell", "do_dont", "prescription", "watch_for", "pitfall", "questions", "next_24h", "call_to_action"],
    "shadow": ["reader_voice", "tell", "shadow", "watch_for", "pitfall", "questions", "call_to_action"],

    "love":   ["reader_voice", "tell", "relationships", "green_red", "pitfall", "questions", "call_to_action"],
    "work":   ["reader_voice", "tell", "work", "prescription", "watch_for", "next_24h", "call_to_action"],
    "money":  ["reader_voice", "tell", "money", "prescription", "watch_for", "next_24h", "call_to_action"],

    "full":   ["reader_voice", "tell", "meaning", "mantra", "do_dont", "prescription", "watch_for", "pitfall",
               "shadow", "green_red", "questions", "next_24h", "call_to_action"],
}

def get_effective_mode(user_id: int, mode_override: Optional[str] = None) -> str:
    if mode_override:
        return normalize_mode(mode_override)
    return get_user_mode(user_id)

def normalize_mode(mode: str) -> str:
    mode = (mode or "").lower().strip()
    return mode if mode in MODE_SPECS else DEFAULT_MODE

def get_user_mode(user_id: int) -> str:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT mode FROM tarot_user_prefs WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
    return normalize_mode(row["mode"]) if row else DEFAULT_MODE

def set_user_mode(user_id: int, mode: str) -> str:
    mode = normalize_mode(mode)
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tarot_user_prefs (user_id, mode)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    mode = EXCLUDED.mode,
                    updated_at = NOW()
            """, (user_id, mode))
        conn.commit()
    return mode

def reset_user_mode(user_id: int) -> str:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tarot_user_prefs WHERE user_id=%s", (user_id,))
        conn.commit()
    return DEFAULT_MODE

def _clip(text: str, max_len: int = 3800) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"

def render_card_text(card: Dict[str, Any], orientation: str, mode: str) -> str:
    """
    orientation: "Upright" or "Reversed"
    mode: one of MODE_SPECS keys
    """
    mode = normalize_mode(mode)
    spec = MODE_SPECS[mode]

    is_rev = (orientation.lower() == "reversed")
    meaning = card.get("reversed" if is_rev else "upright", "—")

    dg = card.get("direct_guidance", {}) or {}
    lenses = dg.get("lenses", {}) or {}

    def do_dont():
        do = dg.get("do", "")
        dont = dg.get("dont", "")
        if do and dont:
            return f"**Do:** {do}\n**Don't:** {dont}"
        return do or dont

    def questions():
        qs = dg.get("questions", []) or []
        qs = [q for q in qs if isinstance(q, str) and q.strip()]
        return "**Ask:** " + " | ".join(qs[:3]) if qs else ""

    blocks = []
    for token in spec:
        if token == "meaning":
            blocks.append(meaning)

        elif token == "mantra":
            m = dg.get("mantra", "")
            if m:
                blocks.append(f"**Mantra:** {m}")

        elif token == "quick":
            q = dg.get("quick", "")
            if q:
                blocks.append(q)

        elif token == "do":
            d = dg.get("do", "")
            if d:
                blocks.append(f"**Do:** {d}")

        elif token == "do_dont":
            dd = do_dont()
            if dd:
                blocks.append(dd)

        elif token == "watch_for":
            w = dg.get("watch_for", "")
            if w:
                blocks.append(f"**Watch for:** {w}")

        elif token == "shadow":
            s = dg.get("shadow", "")
            if s:
                blocks.append(f"**Shadow:** {s}")

        elif token == "questions":
            qs = questions()
            if qs:
                blocks.append(qs)

        elif token == "next_24h":
            n = dg.get("next_24h", "")
            if n:
                blocks.append(f"**Next 24h:** {n}")

        elif token == "relationships":
            txt = lenses.get("relationships") or dg.get("relationships", "")
            if txt:
                blocks.append(f"**Love/People:** {txt}")

        elif token == "work":
            txt = lenses.get("work") or dg.get("work", "")
            if txt:
                blocks.append(f"**Work:** {txt}")

        elif token == "money":
            txt = lenses.get("money") or dg.get("money", "")
            if txt:
                blocks.append(f"**Money:** {txt}")

        # ---- v2 fields ----
        elif token == "tell":
            t = dg.get("tell", "")
            if t:
                blocks.append(f"**The truth:** {t}")

        elif token == "prescription":
            p = dg.get("prescription", "")
            if p:
                blocks.append(f"**Do this:** {p}")

        elif token == "pitfall":
            p = dg.get("pitfall", "")
            if p:
                blocks.append(f"**Pitfall:** {p}")

        elif token == "green_red":
            gf = dg.get("green_flag", "")
            rf = dg.get("red_flag", "")
            if gf or rf:
                line = []
                if gf:
                    line.append(f"**Green flag:** {gf}")
                if rf:
                    line.append(f"**Red flag:** {rf}")
                blocks.append("\n".join(line))

        elif token == "reader_voice":
            rv = dg.get("reader_voice", "")
            if rv:
                blocks.append(f"*{rv}*")

        elif token == "poetic_hint":
            ph = dg.get("poetic_hint", "")
            if ph:
                blocks.append(f"*{ph}*")

        elif token == "call_to_action":
            a = card.get("call_to_action", "")
            if a:
                blocks.append(f"**Action:** {a}")

    return _clip("\n\n".join(blocks))

# ==============================
# LOAD TAROT JSON
# ==============================
def load_tarot_json():
    base_dir = Path(__file__).resolve().parent
    json_path = base_dir / "Tarot_Official.JSON"
    if not json_path.exists():
        raise FileNotFoundError(f"❌ Tarot JSON not found at {json_path}. Make sure 'Tarot_Official.JSON' is in the same directory.")
    with json_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)

tarot_cards = load_tarot_json()
print(f"✅ Loaded {len(tarot_cards)} tarot cards successfully!")

# ==============================
# SEEKER MEMORY SYSTEM
# ==============================
KNOWN_SEEKERS_FILE = Path("known_seekers.json")

def load_known_seekers():
    if KNOWN_SEEKERS_FILE.exists():
        try:
            with KNOWN_SEEKERS_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_known_seekers(data):
    with KNOWN_SEEKERS_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

known_seekers = load_known_seekers()
user_intentions = {}

# ==============================
# BOT SETUP
# ==============================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ==============================
# EMOJIS
# ==============================
E = {
    "sun": "☀️", "moon": "🌙", "crystal": "🔮",
    "light": "💡", "clock": "🕰️", "star": "🌟",
    "book": "📖", "spark": "✨", "warn": "⚠️",
    "fire": "🔥", "water": "💧", "sword": "⚔️",
    "leaf": "🌿", "arcana": "🌌", "shuffle": "🔁"
}

# ==============================
# NAME NORMALIZATION
# ==============================
NUM_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}
NUM_WORDS_RE = re.compile(r"\b(" + "|".join(NUM_WORDS.keys()) + r")\b")

def normalize_card_name(name: str) -> str:
    s = name.lower().strip()
    s = NUM_WORDS_RE.sub(lambda m: NUM_WORDS[m.group(1)], s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s

# ==============================
# HELPERS
# ==============================
def draw_card():
    card = random.choice(tarot_cards)
    orientation = random.choice(["Upright", "Reversed"])
    return card, orientation


def draw_unique_cards(num_cards: int):
    deck = tarot_cards.copy()
    random.shuffle(deck)
    drawn = []
    for _ in range(min(num_cards, len(deck))):
        card = deck.pop()
        orientation = random.choice(["Upright", "Reversed"])
        drawn.append((card, orientation))
    return drawn

def clip_field(text: str, limit: int = 1024) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"

def suit_color(suit):
    return {
        "Wands": 0xE25822, "Cups": 0x0077BE, "Swords": 0xB0B0B0,
        "Pentacles": 0x2E8B57, "Major Arcana": 0xA020F0
    }.get(suit, 0x9370DB)

def suit_emoji(suit):
    return {
        "Wands": E["fire"], "Cups": E["water"], "Swords": E["sword"],
        "Pentacles": E["leaf"], "Major Arcana": E["arcana"]
    }.get(suit, E["crystal"])

# ==============================
# IN-CHARACTER RESPONSES
# ==============================
in_character_lines = {
    "shuffle": [
        "The deck hums with fresh energy once more.",
        "All is reset. The cards breathe again.",
        "Order dissolves into possibility — the deck is ready."
    ],
    "daily": [
        "Here is the energy that threads through your day...",
        "This card has stepped forward to guide you.",
        "Its message hums softly — take it with you into the light."
    ],
    "spread": [
        "The weave of time unfolds — past, present, and future speak.",
        "Let us see how the threads intertwine for your path.",
        "Each card now reveals its whisper in the larger story."
    ],
    "deep": [
        "This spread carries depth — breathe as you read its symbols.",
        "A more ancient current flows beneath these cards.",
        "The deck speaks slowly now; listen beyond the words."
    ],
    "general": [
        "The veil lifts and a message takes shape...",
        "Listen closely — the cards are patient but precise.",
        "A single spark of insight is about to emerge..."
    ]
}

# ==============================
# TYPING SIMULATION
# ==============================
async def send_with_typing(ctx, embed, delay_range=(1.5, 3.0), mood="general", file_obj=None):
    thinking_lines = {
        "shuffle": [
            "🔮 Arcanara breathes deeply and stirs the deck...",
            "✨ The cards realign under unseen hands...",
            "🌬️ She scatters stardust across the table..."
        ],
        "daily": [
            "🌙 Arcanara turns a single card beneath the morning light...",
            "☀️ The deck whispers — one truth for today...",
            "🍃 The veil shimmers softly; a daily omen forms..."
        ],
        "spread": [
            "🪶 The cards slide into a pattern, each glowing faintly...",
            "🌌 A gentle rustle — the spread begins to reveal its order...",
            "🔮 Energy ripples through the layout..."
        ],
        "deep": [
            "🔥 The atmosphere thickens — this one reaches deep...",
            "💫 The circle tightens; symbols stir in the air...",
            "🌒 The ancient rhythm of the cards awakens..."
        ],
        "general": [
            "✨ Arcanara shuffles the cards and listens...",
            "🌙 The veil stirs with quiet anticipation...",
            "🔮 The energy turns — something wants to be said..."
        ]
    }

    thought = random.choice(thinking_lines.get(mood, thinking_lines["general"]))
    message = await ctx.send(thought)
    async with ctx.typing():
        await asyncio.sleep(random.uniform(*delay_range))
        await message.delete()
        line = random.choice(in_character_lines.get(mood, in_character_lines["general"]))
        await ctx.send(f"*{line}*")
        await asyncio.sleep(0.5)

        if file_obj:
            await ctx.send(embed=embed, file=file_obj)
        else:
            await ctx.send(embed=embed)

# ==============================
# EVENTS
# ==============================
@bot.event
async def on_ready():
    global _DB_READY
    if not _DB_READY:
        ensure_tables()
        _DB_READY = True

    print(f"{E['crystal']} Arcanara is awake and shimmering as {bot.user}")

# ==============================
# COMMANDS
# ==============================
@bot.command(name="shuffle")
async def shuffle(ctx):
    random.shuffle(tarot_cards)
    embed = discord.Embed(
        title=f"{E['shuffle']} The Deck Has Been Cleansed {E['shuffle']}",
        description="Energy reset complete. The cards are ready to speak again.",
        color=0x9370DB
    )
    await send_with_typing(ctx, embed, delay_range=(1.0, 2.0), mood="shuffle")

@bot.command(name="cardoftheday")
async def card_of_the_day(ctx):
    card, orientation = draw_card()
    mode = get_effective_mode(ctx.author.id)
    meaning = render_card_text(card, orientation, mode)

    is_reversed = (orientation == "Reversed")
    file_obj, attach_url = make_image_attachment(card["name"], is_reversed)

    if not attach_url and file_obj is not None:
        attach_url = f"attachment://{file_obj.filename}"

    tone = E["sun"] if orientation == "Upright" else E["moon"]
    intent_text = user_intentions.get(ctx.author.id)

    desc = f"**{card['name']} ({orientation} {tone}) • mode: {mode}**\n\n{meaning}"
    if intent_text:
        desc += f"\n\n{E['light']} **Focus:** *{intent_text}*"

    embed = discord.Embed(
        title=f"{E['crystal']} Card of the Day",
        description=desc,
        color=suit_color(card["suit"])
    )

    if attach_url:
        embed.set_image(url=attach_url)

    await send_with_typing(ctx, embed, delay_range=(1.5, 2.5), mood="daily", file_obj=file_obj)

@bot.command(name="read")
async def read(ctx, *, message: str = None):
    if not message:
        await ctx.send(f"{E['warn']} Please include a question or focus after the command. Example: `!read my career path`")
        return

    user_intentions[ctx.author.id] = message
    mode = get_effective_mode(ctx.author.id)

    cards = draw_unique_cards(3)
    positions = [f"Situation {E['sun']}", f"Obstacle {E['sword']}", f"Guidance {E['star']}"]

    desc = f"{E['light']} **Focus:** *{message}*\n\nThree cards emerge to illuminate your path:\n\n**Mode:** {mode}"

    embed = discord.Embed(
        title=f"{E['crystal']} Intuitive Reading {E['crystal']}",
        description=desc,
        color=0x9370DB
    )

    for pos, (card, orientation) in zip(positions, cards):
        meaning = render_card_text(card, orientation, mode)
        embed.add_field(
            name=f"{pos}: {card['name']} ({orientation})",
            value=meaning if len(meaning) < 1000 else meaning[:997] + "...",
            inline=False
        )

    embed.set_footer(text=f"{E['spark']} Let these cards guide your awareness, not dictate your choices.")
    await send_with_typing(ctx, embed, delay_range=(2.5, 4.0), mood="spread")

@bot.command(name="threecard")
async def three_card(ctx):
    positions = [f"Past {E['clock']}", f"Present {E['moon']}", f"Future {E['star']}"]
    cards = draw_unique_cards(3)
    intent_text = user_intentions.get(ctx.author.id)

    mode = get_effective_mode(ctx.author.id)

    desc = "Past • Present • Future"
    if intent_text:
        desc += f"\n\n{E['light']} **Focus:** *{intent_text}*"
    desc += f"\n\n**Mode:** {mode}"

    embed = discord.Embed(
        title=f"{E['crystal']} Three-Card Spread",
        description=desc,
        color=0xA020F0
    )

    for pos, (card, orientation) in zip(positions, cards):
        meaning = render_card_text(card, orientation, mode)
        embed.add_field(
            name=f"{pos}: {card['name']} ({orientation})",
            value=meaning if len(meaning) < 1000 else meaning[:997] + "...",
            inline=False
        )

    await send_with_typing(ctx, embed, delay_range=(2.5, 4.0), mood="spread")

@bot.command(name="celtic")
async def celtic_cross(ctx):
    positions = [
        "1️⃣ Present Situation", "2️⃣ Challenge", "3️⃣ Root Cause", "4️⃣ Past",
        "5️⃣ Conscious Goal", "6️⃣ Near Future", "7️⃣ Self", "8️⃣ External Influence",
        "9️⃣ Hopes & Fears", "🔟 Outcome"
    ]
    cards = draw_unique_cards(10)
    mode = get_effective_mode(ctx.author.id)

    embed = discord.Embed(
        title=f"{E['crystal']} Celtic Cross Spread {E['crystal']}",
        description=f"A deep, archetypal exploration of your path.\n\n**Mode:** {mode}",
        color=0xA020F0
    )

    total_length = len(embed.title) + len(embed.description)

    for pos, (card, orientation) in zip(positions, cards):
        meaning = render_card_text(card, orientation, mode)
        field_name = f"{pos}: {card['name']} ({orientation})"
        field_value = meaning if len(meaning) < 1000 else meaning[:997] + "..."
        field_length = len(field_name) + len(field_value)

        if total_length + field_length > 5800:
            await send_with_typing(ctx, embed, delay_range=(3.0, 4.0), mood="deep")
            embed = discord.Embed(
                title=f"{E['crystal']} Celtic Cross Spread (Continued)",
                description=f"**Mode:** {mode}",
                color=0xA020F0
            )
            total_length = len(embed.title) + len(embed.description)

        embed.add_field(name=field_name, value=field_value, inline=False)
        total_length += field_length

    await send_with_typing(ctx, embed, delay_range=(3.0, 4.0), mood="deep")

@bot.command(name="meaning")
async def meaning(ctx, *, query: str):
    # Detect "reversed" in the query (image rotation only)
    is_reversed = bool(re.search(r"\brev(?:ersed)?\b", query, re.I))
    clean_query = re.sub(r"\brev(?:ersed)?\b", "", query, flags=re.I).strip()

    norm_query = normalize_card_name(clean_query)

    matches = [
        c for c in tarot_cards
        if normalize_card_name(c["name"]) == norm_query
        or norm_query in normalize_card_name(c["name"])
    ]

    if not matches:
        await ctx.send(f"{E['warn']} I searched the deck but found no card named **{query}**.")
        return

    card = matches[0]
    mode = get_effective_mode(ctx.author.id)  # ✅ define mode BEFORE using it

    # ---- Embed A: title + image ----
    embed_top = discord.Embed(
        title=f"{E['book']} {card['name']} • mode: {mode}",
        color=suit_color(card["suit"])
    )

    file_obj, attach_url = make_image_attachment(card["name"], is_reversed)

    # If helper didn't give attach_url but did give a file, build the attachment URL
    if not attach_url and file_obj is not None:
        attach_url = f"attachment://{file_obj.filename}"

    if attach_url:
        embed_top.set_image(url=attach_url)

    # ---- Embed B: meanings (mode-rendered) ----
    embed_body = discord.Embed(
        description=f"**{card['name']}** reveals both sides of its nature:",
        color=suit_color(card["suit"])
    )

    upright_text = clip_field(render_card_text(card, "Upright", mode), 1024)
    reversed_text = clip_field(render_card_text(card, "Reversed", mode), 1024)

    embed_body.add_field(name=f"Upright {E['sun']} • {mode}", value=upright_text, inline=False)
    embed_body.add_field(name=f"Reversed {E['moon']} • {mode}", value=reversed_text, inline=False)
    embed_body.set_footer(text=f"{E['light']} Interpreting symbols through Arcanara • Tarot Bot")

    async with ctx.typing():
        await asyncio.sleep(random.uniform(1.0, 2.0))

    # ---- Send both embeds together ----
    try:
        if file_obj:
            await ctx.send(embeds=[embed_top, embed_body], file=file_obj)
        else:
            await ctx.send(embeds=[embed_top, embed_body])
    except TypeError:
        # Fallback for older discord.py
        if file_obj:
            await ctx.send(embed=embed_top, file=file_obj)
        else:
            await ctx.send(embed=embed_top)
        await ctx.send(embed=embed_body)

    
@bot.command(name="clarify")
async def clarify(ctx):
    card, orientation = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]
    intent_text = user_intentions.get(ctx.author.id)

    mode = get_effective_mode(ctx.author.id)
    meaning = render_card_text(card, orientation, mode)

    desc = f"**{card['name']} ({orientation} {tone}) • mode: {mode}**\n\n{meaning}"
    if intent_text:
        desc += f"\n\n{E['light']} **Clarifying Focus:** *{intent_text}*"

    embed = discord.Embed(
        title=f"{E['light']} Clarifier Card {E['light']}",
        description=desc,
        color=suit_color(card["suit"])
    )
    embed.set_footer(text=f"{E['spark']} A clarifier shines a smaller light within your larger spread.")

    await send_with_typing(ctx, embed, delay_range=(1.5, 2.5), mood="general")

@bot.command(name="intent")
async def intent(ctx, *, message: str = None):
    if not message:
        current = user_intentions.get(ctx.author.id)
        if current:
            await ctx.send(f"{E['light']} Your current intention is: *{current}*")
        else:
            await ctx.send(f"{E['warn']} You haven’t set an intention yet. Use `!intent your focus`.")
        return

    user_intentions[ctx.author.id] = message
    await ctx.send(f"{E['spark']} Intention set to: *{message}*")

@bot.command(name="insight")
async def insight(ctx):
    user_id = str(ctx.author.id)
    user_name = ctx.author.display_name

    first_time = user_id not in known_seekers
    if first_time:
        greeting = f"{E['spark']} **Welcome, {user_name}.**\nThe deck senses a new presence — your journey begins here."
        known_seekers[user_id] = {"name": user_name}
        save_known_seekers(known_seekers)
    else:
        greeting = f"{E['spark']} **Welcome back, {user_name}.**\nYour energy feels familiar — shall we continue?"

    embed = discord.Embed(
        title=f"{E['crystal']} Arcanara Insight Menu {E['crystal']}",
        description=(f"{greeting}\n\nYour intuition is your compass — here are the paths you may travel:\n\n━━━━━━━━━━━━━━━━━━━━━━━"),
        color=0xB28DFF
    )

    embed.add_field(
        name=f"{E['light']} **Intent & Focus**",
        value=("• `!intent <your focus>` — Set or view your current intention.\n"
               "• `!clarify` — Draw a clarifier for your most recent reading."),
        inline=False
    )

    embed.add_field(
        name=f"{E['book']} **Draws & Spreads**",
        value=("• `!cardoftheday` — Reveal the card that guides your day.\n"
               "• `!threecard` — Explore Past, Present, and Future energies.\n"
               "• `!read <focus>` — Receive a three-card reading (Situation, Obstacle, Guidance).\n"
               "• `!celtic` — Perform a full 10-card Celtic Cross spread."),
        inline=False
    )
    
    embed.add_field(
        name=f"{E['spark']} **Knowledge & Reflection**",
        value=("• `!meaning <card>` — Uncover upright and reversed meanings.\n"
               "• `!shuffle` — Cleanse and reset the deck’s energy.\n"
               "• `!insight` — Return to this sacred index anytime.\n"
               "• `!mystery` — Pull a mystery card and reflect without the meaning.\n"
               "• `!reveal` — Reveal the meanings of the mystery card."),
        inline=False
    )

    embed.set_footer(
        text=f"{E['light']} Trust your intuition • Arcanara Tarot Bot",
        icon_url="https://cdn-icons-png.flaticon.com/512/686/686589.png"
    )

    async with ctx.typing():
        await asyncio.sleep(random.uniform(0.8, 1.2))

    await ctx.send(embed=embed)

@bot.command(name="mode")
async def mode(ctx, *, mode: str = None):
    """Set your default tarot reading mode."""
    if not mode:
        current = get_user_mode(ctx.author.id)
        await ctx.send(f"{E['light']} Your current mode is **{current}**.")
        return

    chosen = set_user_mode(ctx.author.id, mode)
    await ctx.send(f"✅ Default tarot mode set to **{chosen}**.")

@bot.command(name="mode_reset")
async def mode_reset(ctx):
    chosen = reset_user_mode(ctx.author.id)
    await ctx.send(f"✅ Mode reset. Default tarot mode is **{chosen}**.")

# ==============================
# MYSTERY + REVEAL COMMANDS
# ==============================
mystery_draws = {}  # Temporary storage of mystery cards per user

@bot.command(name="mystery")
async def mystery(ctx):
    # pick a random card + orientation
    card = random.choice(tarot_cards)
    is_reversed = random.random() < 0.5

    # remember it for this user (one active mystery per user)
    MYSTERY_STATE[ctx.author.id] = {
        "name": card["name"],
        "is_reversed": is_reversed,
        "ts": time.time(),
    }

    # Embed A: title + image (no meanings yet)
    embed_top = discord.Embed(
        title=f"{E['crystal']} {card['name']}" + (" — Reversed" if is_reversed else ""),
        color=suit_color(card["suit"])
    )
    file_obj, attach_url = make_image_attachment(card["name"], is_reversed)
    if attach_url:
        embed_top.set_image(url=attach_url)

    # little nudge to the user
    embed_top.set_footer(text=f"Type !reveal to see the meaning")

    # send it
    if file_obj:
        await ctx.send(embed=embed_top, file=file_obj)
    else:
        await ctx.send(embed=embed_top)

@bot.command(name="reveal")
async def reveal(ctx):
    # fetch the user's last mystery draw
    state = MYSTERY_STATE.get(ctx.author.id)
    if not state:
        await ctx.send(f"{E['warn']} No mystery card on file. Use **!mystery** first.")
        return

    # find the card object by name
    name = state["name"]
    is_reversed = state["is_reversed"]
    card = next((c for c in tarot_cards if c["name"] == name), None)
    if not card:
        await ctx.send(f"{E['warn']} I lost track of that card, sorry. Try **!mystery** again.")
        return

    # Build the meaning embed: show ONLY the relevant orientation
    mode = get_effective_mode(ctx.author.id)
    orientation = "Reversed" if is_reversed else "Upright"
    meaning = render_card_text(card, orientation, mode)

    embed = discord.Embed(
        title=f"{E['book']} Reveal: {card['name']} ({orientation}) • mode: {mode}",
        description=meaning,
        color=suit_color(card["suit"])
    )
    embed.set_footer(text=f"{E['light']} Interpreting symbols through Arcanara • Tarot Bot")

    await ctx.send(embed=embed)

    # one-time reveal: clear stored draw
    del MYSTERY_STATE[ctx.author.id]

# ==============================
# RUN BOT
# ==============================
bot.run(BOT_TOKEN)
