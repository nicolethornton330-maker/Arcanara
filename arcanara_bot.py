# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
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
intents.guilds = True
intents.message_content = True  # can be True or False; slash commands don't need it
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
# TYPING SIMULATION (ephemeral helper)
# ==============================
def _prepend_in_character(embed: discord.Embed, mood: str) -> discord.Embed:
    line = random.choice(in_character_lines.get(mood, in_character_lines["general"]))
    if embed.description:
        embed.description = f"*{line}*\n\n{embed.description}"
    else:
        embed.description = f"*{line}*"
    return embed


async def _send_ephemeral(interaction: discord.Interaction, **kwargs):
    """
    Safely send an ephemeral message whether or not the interaction
    has already been responded to.
    """
    kwargs.setdefault("ephemeral", True)

    if interaction.response.is_done():
        return await interaction.followup.send(**kwargs)

    return await interaction.response.send_message(**kwargs)


async def send_ephemeral(
    interaction: discord.Interaction,
    *,
    embed: Optional[discord.Embed] = None,
    embeds: Optional[List[discord.Embed]] = None,
    content: Optional[str] = None,
    mood: str = "general",
    file_obj: Optional[discord.File] = None,
):
    # Apply in-character line to the first embed only
    if embed is not None:
        embed = _prepend_in_character(embed, mood)
        await _send_ephemeral(interaction, content=content, embed=embed, file=file_obj)
        return

    if embeds is not None and len(embeds) > 0:
        embeds = list(embeds)
        embeds[0] = _prepend_in_character(embeds[0], mood)
        await _send_ephemeral(interaction, content=content, embeds=embeds, file=file_obj)
        return

    await _send_ephemeral(interaction, content=content or "—")

# ==============================
# EVENTS
# ==============================
@bot.event
async def on_ready():
    global _DB_READY
    if not _DB_READY:
        ensure_tables()
        _DB_READY = True

    try:
        await bot.tree.sync()
        print("✅ Slash commands synced.")
    except Exception as e:
        print(f"⚠️ Slash sync failed: {e}")

    print(f"{E['crystal']} Arcanara is awake and shimmering as {bot.user}")


# ==============================
# SLASH COMMANDS (EPHEMERAL)
# ==============================

@bot.tree.command(name="shuffle", description="Cleanse and reset the deck’s energy.")
async def shuffle_slash(interaction: discord.Interaction):
    random.shuffle(tarot_cards)
    embed = discord.Embed(
        title=f"{E['shuffle']} The Deck Has Been Cleansed {E['shuffle']}",
        description="Energy reset complete. The cards are ready to speak again.",
        color=0x9370DB
    )
    await send_ephemeral(interaction, embed=embed, mood="shuffle")


@bot.tree.command(name="cardoftheday", description="Reveal the card that guides your day.")
async def cardoftheday_slash(interaction: discord.Interaction):
    card, orientation = draw_card()
    mode = get_effective_mode(interaction.user.id)
    meaning = render_card_text(card, orientation, mode)

    is_reversed = (orientation == "Reversed")
    file_obj, attach_url = make_image_attachment(card["name"], is_reversed)
    if not attach_url and file_obj is not None:
        attach_url = f"attachment://{file_obj.filename}"

    tone = E["sun"] if orientation == "Upright" else E["moon"]
    intent_text = user_intentions.get(interaction.user.id)

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

    await send_ephemeral(interaction, embed=embed, mood="daily", file_obj=file_obj)


@bot.tree.command(name="read", description="Three-card reading: Situation • Obstacle • Guidance.")
@app_commands.describe(focus="Your question or focus (example: my career path)")
async def read_slash(interaction: discord.Interaction, focus: str):
    user_intentions[interaction.user.id] = focus
    mode = get_effective_mode(interaction.user.id)

    cards = draw_unique_cards(3)
    positions = [f"Situation {E['sun']}", f"Obstacle {E['sword']}", f"Guidance {E['star']}"]

    embed = discord.Embed(
        title=f"{E['crystal']} Intuitive Reading {E['crystal']}",
        description=f"{E['light']} **Focus:** *{focus}*\n\n**Mode:** {mode}",
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
    await send_ephemeral(interaction, embed=embed, mood="spread")


@bot.tree.command(name="threecard", description="Past • Present • Future spread.")
async def threecard_slash(interaction: discord.Interaction):
    positions = [f"Past {E['clock']}", f"Present {E['moon']}", f"Future {E['star']}"]
    cards = draw_unique_cards(3)

    mode = get_effective_mode(interaction.user.id)
    intent_text = user_intentions.get(interaction.user.id)

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

    await send_ephemeral(interaction, embed=embed, mood="spread")


@bot.tree.command(name="celtic", description="Full 10-card Celtic Cross spread.")
async def celtic_slash(interaction: discord.Interaction):
    positions = [
        "1️⃣ Present Situation", "2️⃣ Challenge", "3️⃣ Root Cause", "4️⃣ Past",
        "5️⃣ Conscious Goal", "6️⃣ Near Future", "7️⃣ Self", "8️⃣ External Influence",
        "9️⃣ Hopes & Fears", "🔟 Outcome"
    ]
    cards = draw_unique_cards(10)
    mode = get_effective_mode(interaction.user.id)

    # We may need multiple messages due to embed limits.
    embeds_to_send: List[discord.Embed] = []
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
            embeds_to_send.append(embed)
            embed = discord.Embed(
                title=f"{E['crystal']} Celtic Cross (Continued)",
                description=f"**Mode:** {mode}",
                color=0xA020F0
            )
            total_length = len(embed.title) + len(embed.description)

        embed.add_field(name=field_name, value=field_value, inline=False)
        total_length += field_length

    embeds_to_send.append(embed)

    # Send first response + followups, all ephemeral
    embeds_to_send[0] = _prepend_in_character(embeds_to_send[0], "deep")
    await interaction.response.send_message(embeds=[embeds_to_send[0]], ephemeral=True)

    for e in embeds_to_send[1:]:
        await interaction.followup.send(embeds=[e], ephemeral=True)


@bot.tree.command(name="meaning", description="Show upright and reversed meanings for a card (using your current mode).")
@app_commands.describe(card="Card name (example: The Lovers)")
async def meaning_slash(interaction: discord.Interaction, card: str):
    norm_query = normalize_card_name(card)

    matches = [
        c for c in tarot_cards
        if normalize_card_name(c["name"]) == norm_query
        or norm_query in normalize_card_name(c["name"])
    ]

    if not matches:
        await interaction.response.send_message(f"{E['warn']} I searched the deck but found no card named **{card}**.", ephemeral=True)
        return

    chosen = matches[0]
    mode = get_effective_mode(interaction.user.id)

    # default upright image
    file_obj, attach_url = make_image_attachment(chosen["name"], is_reversed=False)
    if not attach_url and file_obj is not None:
        attach_url = f"attachment://{file_obj.filename}"

    embed_top = discord.Embed(
        title=f"{E['book']} {chosen['name']} • mode: {mode}",
        description="",
        color=suit_color(chosen["suit"])
    )
    if attach_url:
        embed_top.set_image(url=attach_url)

    embed_body = discord.Embed(
        description=f"**{chosen['name']}** reveals both sides of its nature:",
        color=suit_color(chosen["suit"])
    )

    upright_text = clip_field(render_card_text(chosen, "Upright", mode), 1024)
    reversed_text = clip_field(render_card_text(chosen, "Reversed", mode), 1024)

    embed_body.add_field(name=f"Upright {E['sun']} • {mode}", value=upright_text, inline=False)
    embed_body.add_field(name=f"Reversed {E['moon']} • {mode}", value=reversed_text, inline=False)
    embed_body.set_footer(text=f"{E['light']} Interpreting symbols through Arcanara • Tarot Bot")

    await send_ephemeral(interaction, embeds=[embed_top, embed_body], mood="general", file_obj=file_obj)


async def card_name_autocomplete(interaction: discord.Interaction, current: str):
    current = (current or "").lower()
    hits = [c["name"] for c in tarot_cards if current in c["name"].lower()]
    return [app_commands.Choice(name=name, value=name) for name in hits[:25]]

@meaning_slash.autocomplete("card")
async def meaning_card_autocomplete(interaction: discord.Interaction, current: str):
    return await card_name_autocomplete(interaction, current)


@bot.tree.command(name="clarify", description="Draw a clarifier card for your current focus.")
async def clarify_slash(interaction: discord.Interaction):
    card, orientation = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]
    intent_text = user_intentions.get(interaction.user.id)

    mode = get_effective_mode(interaction.user.id)
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

    await send_ephemeral(interaction, embed=embed, mood="general")


@bot.tree.command(name="intent", description="Set (or view) your current intention/focus.")
@app_commands.describe(focus="Leave blank to view your current intention.")
async def intent_slash(interaction: discord.Interaction, focus: Optional[str] = None):
    if not focus:
        current = user_intentions.get(interaction.user.id)
        if current:
            await interaction.response.send_message(f"{E['light']} Your current intention is: *{current}*", ephemeral=True)
        else:
            await interaction.response.send_message(f"{E['warn']} You haven’t set an intention yet. Use `/intent focus: ...`", ephemeral=True)
        return

    user_intentions[interaction.user.id] = focus
    await interaction.response.send_message(f"{E['spark']} Intention set to: *{focus}*", ephemeral=True)


@bot.tree.command(name="mode", description="Set your default tarot reading mode.")
@app_commands.choices(mode=[
    app_commands.Choice(name="full", value="full"),
    app_commands.Choice(name="direct", value="direct"),
    app_commands.Choice(name="shadow", value="shadow"),
    app_commands.Choice(name="poetic", value="poetic"),
    app_commands.Choice(name="quick", value="quick"),
    app_commands.Choice(name="love", value="love"),
    app_commands.Choice(name="work", value="work"),
    app_commands.Choice(name="money", value="money"),
])
async def mode_slash(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    chosen = set_user_mode(interaction.user.id, mode.value)
    await interaction.response.send_message(f"✅ Default tarot mode set to **{chosen}**.", ephemeral=True)


@bot.tree.command(name="mode_reset", description="Reset your mode back to the default.")
async def mode_reset_slash(interaction: discord.Interaction):
    chosen = reset_user_mode(interaction.user.id)
    await interaction.response.send_message(f"✅ Mode reset. Default tarot mode is **{chosen}**.", ephemeral=True)


@bot.tree.command(name="mystery", description="Pull a mystery card (image only). Use /reveal to see the meaning.")
async def mystery_slash(interaction: discord.Interaction):
    card = random.choice(tarot_cards)
    is_reversed = random.random() < 0.5

    MYSTERY_STATE[interaction.user.id] = {
        "name": card["name"],
        "is_reversed": is_reversed,
        "ts": time.time(),
    }

    embed_top = discord.Embed(
        title=f"{E['crystal']} {card['name']}" + (" — Reversed" if is_reversed else ""),
        description="Type **/reveal** to see the meaning.",
        color=suit_color(card["suit"])
    )

    file_obj, attach_url = make_image_attachment(card["name"], is_reversed)
    if not attach_url and file_obj is not None:
        attach_url = f"attachment://{file_obj.filename}"
    if attach_url:
        embed_top.set_image(url=attach_url)

    await send_ephemeral(interaction, embed=embed_top, mood="general", file_obj=file_obj)


@bot.tree.command(name="reveal", description="Reveal the meaning of your last mystery card.")
async def reveal_slash(interaction: discord.Interaction):
    state = MYSTERY_STATE.get(interaction.user.id)
    if not state:
        await interaction.response.send_message(f"{E['warn']} No mystery card on file. Use **/mystery** first.", ephemeral=True)
        return

    name = state["name"]
    is_reversed = state["is_reversed"]

    card = next((c for c in tarot_cards if c["name"] == name), None)
    if not card:
        await interaction.response.send_message(f"{E['warn']} I lost track of that card. Try **/mystery** again.", ephemeral=True)
        return

    mode = get_effective_mode(interaction.user.id)
    orientation = "Reversed" if is_reversed else "Upright"
    meaning = render_card_text(card, orientation, mode)

    embed = discord.Embed(
        title=f"{E['book']} Reveal: {card['name']} ({orientation}) • mode: {mode}",
        description=meaning,
        color=suit_color(card["suit"])
    )
    embed.set_footer(text=f"{E['light']} Interpreting symbols through Arcanara • Tarot Bot")

    del MYSTERY_STATE[interaction.user.id]
    await send_ephemeral(interaction, embed=embed, mood="general")


@bot.tree.command(name="insight", description="Show Arcanara’s command index and your current settings.")
async def insight_slash(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    user_name = interaction.user.display_name

    first_time = user_id not in known_seekers
    if first_time:
        greeting = f"{E['spark']} **Welcome, {user_name}.**\nThe deck senses a new presence — your journey begins here."
        known_seekers[user_id] = {"name": user_name}
        save_known_seekers(known_seekers)
    else:
        greeting = f"{E['spark']} **Welcome back, {user_name}.**\nYour energy feels familiar — shall we continue?"

    current_mode = get_effective_mode(interaction.user.id)
    current_intent = user_intentions.get(interaction.user.id, "—")

    # Dynamically list all slash commands
    cmds = [c for c in bot.tree.get_commands() if isinstance(c, app_commands.Command)]
    cmds = sorted(cmds, key=lambda c: c.name)

    # Build a readable list
    lines = []
    for c in cmds:
        desc = (c.description or "").strip()
        lines.append(f"• `/{c.name}` — {desc}" if desc else f"• `/{c.name}`")

    # Split if necessary to avoid field limits
    chunk = "\n".join(lines)
    if len(chunk) > 900:
        # rough chunking
        chunks = []
        buf = []
        size = 0
        for line in lines:
            if size + len(line) + 1 > 900:
                chunks.append("\n".join(buf))
                buf = [line]
                size = len(line) + 1
            else:
                buf.append(line)
                size += len(line) + 1
        if buf:
            chunks.append("\n".join(buf))
    else:
        chunks = [chunk]

    embed = discord.Embed(
        title=f"{E['crystal']} Arcanara Insight Menu {E['crystal']}",
        description=f"{greeting}\n\n**Mode:** `{current_mode}`\n**Intention:** *{current_intent}*\n\n━━━━━━━━━━━━━━━━━━━━━━━",
        color=0xB28DFF
    )

    embed.add_field(name="📜 Available Commands", value=chunks[0] or "—", inline=False)
    for i, part in enumerate(chunks[1:], start=2):
        embed.add_field(name=f"📜 Available Commands (cont. {i})", value=part, inline=False)

    embed.set_footer(text=f"{E['light']} Trust your intuition • Arcanara Tarot Bot")
    await send_ephemeral(interaction, embed=embed, mood="general")


# ==============================
# RUN BOT
# ==============================
bot.run(BOT_TOKEN)
