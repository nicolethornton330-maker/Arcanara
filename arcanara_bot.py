# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import random
import json
import asyncio
from pathlib import Path
import os

# ==============================
# CONFIGURATION
# ==============================
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable not found. Please set it in your host environment settings.")

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
import re

# Convert number words ↔ digits for flexible matching
NUM_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}
NUM_WORDS_RE = re.compile(r"\b(" + "|".join(NUM_WORDS.keys()) + r")\b")

def normalize_card_name(name: str) -> str:
    """Normalize card names and queries for flexible matching."""
    s = name.lower().strip()
    # Replace number words with digits (e.g., 'two' → '2')
    s = NUM_WORDS_RE.sub(lambda m: NUM_WORDS[m.group(1)], s)
    # Remove extra spaces and punctuation
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s

# ==============================
# HELPERS
# ==============================
def draw_card():
    card = random.choice(tarot_cards)
    orientation = random.choice(["Upright", "Reversed"])
    meaning = card["upright"] if orientation == "Upright" else card["reversed"]
    return card, orientation, meaning

def draw_unique_cards(num_cards: int):
    deck = tarot_cards.copy()
    random.shuffle(deck)
    drawn = []
    for _ in range(min(num_cards, len(deck))):
        card = deck.pop()
        orientation = random.choice(["Upright", "Reversed"])
        meaning = card["upright"] if orientation == "Upright" else card["reversed"]
        drawn.append((card, orientation, meaning))
    return drawn

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
async def send_with_typing(ctx, embed, delay_range=(1.5, 3.0), mood="general"):
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
        await ctx.send(embed=embed)

# ==============================
# EVENTS
# ==============================
@bot.event
async def on_ready():
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
    card, orientation, meaning = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]
    embed = discord.Embed(
        title=f"{E['crystal']} Card of the Day",
        description=f"**{card['name']} ({orientation} {tone})**\n\n{meaning}",
        color=suit_color(card["suit"])
    )
    await send_with_typing(ctx, embed, delay_range=(1.5, 2.5), mood="daily")

@bot.command(name="threecard")
async def three_card(ctx):
    positions = [f"Past {E['clock']}", f"Present {E['moon']}", f"Future {E['star']}"]
    cards = draw_unique_cards(3)
    embed = discord.Embed(
        title=f"{E['crystal']} Three-Card Spread",
        description="Past • Present • Future",
        color=0xA020F0
    )
    for pos, (card, orientation, meaning) in zip(positions, cards):
        embed.add_field(name=f"{pos}: {card['name']} ({orientation})", value=meaning, inline=False)
    await send_with_typing(ctx, embed, delay_range=(2.5, 4.0), mood="spread")

@bot.command(name="celtic")
async def celtic_cross(ctx):
    positions = [
        "1️⃣ Present Situation", "2️⃣ Challenge", "3️⃣ Root Cause", "4️⃣ Past",
        "5️⃣ Conscious Goal", "6️⃣ Near Future", "7️⃣ Self", "8️⃣ External Influence",
        "9️⃣ Hopes & Fears", "🔟 Outcome"
    ]
    cards = draw_unique_cards(10)
    embed = discord.Embed(
        title=f"{E['crystal']} Celtic Cross Spread {E['crystal']}",
        description="A deep, archetypal exploration of your path.",
        color=0xA020F0
    )
    for pos, (card, orientation, meaning) in zip(positions, cards):
        embed.add_field(name=f"{pos}: {card['name']} ({orientation})", value=meaning, inline=False)
    await send_with_typing(ctx, embed, delay_range=(3.5, 5.0), mood="deep")

@bot.command(name="clarify")
async def clarify(ctx):
    card, orientation, meaning = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]
    embed = discord.Embed(
        title=f"{E['light']} Clarifier Card",
        description=f"**{card['name']} ({orientation} {tone})**\n\n{meaning}",
        color=suit_color(card["suit"])
    )
    await send_with_typing(ctx, embed, delay_range=(1.5, 2.5), mood="general")

@bot.command(name="meaning")
async def meaning(ctx, *, query: str):
    """Look up a tarot card meaning (without in-character response)."""
    norm_query = normalize_card_name(query)

    matches = [
        c for c in tarot_cards
        if normalize_card_name(c["name"]) == norm_query
        or norm_query in normalize_card_name(c["name"])
    ]

    if not matches:
        await ctx.send(f"{E['warn']} I searched the deck but found no card named **{query}**.")
        return

    card = matches[0]
    embed = discord.Embed(
        title=f"{E['book']} {card['name']} Meanings",
        description=f"**{card['name']}** reveals both sides of its nature:",
        color=suit_color(card["suit"])
    )
    embed.add_field(name=f"Upright {E['sun']}", value=card.get("upright", "—"), inline=False)
    embed.add_field(name=f"Reversed {E['moon']}", value=card.get("reversed", "—"), inline=False)
    embed.set_footer(text=f"{E['light']} Interpreting symbols through Arcanara • Tarot Bot")

    async with ctx.typing():
        await asyncio.sleep(random.uniform(1.0, 2.0))

    await ctx.send(embed=embed)
    
@bot.command(name="insight")
async def insight(ctx):
    """Provides a quick, low-delay command overview."""
    embed = discord.Embed(
        title=f"{E['spark']} Arcanara Insight Menu",
        color=0x9370DB,
        description="Here are the paths you can walk with me:"
    )
    embed.add_field(name="!cardoftheday", value="Draw your daily tarot card.", inline=False)
    embed.add_field(name="!threecard", value="Explore your Past, Present, and Future.", inline=False)
    embed.add_field(name="!celtic", value="Perform a full Celtic Cross spread.", inline=False)
    embed.add_field(name="!clarify", value="Draw a clarifier for your last reading.", inline=False)
    embed.add_field(name="!meaning <card>", value="See upright and reversed meanings.", inline=False)
    embed.add_field(name="!shuffle", value="Cleanse and reset the deck’s energy.", inline=False)
    embed.set_footer(text=f"{E['light']} Trust your intuition • Arcanara Tarot Bot")

    # short, gentle typing animation (1–1.5 seconds)
    async with ctx.typing():
        await asyncio.sleep(random.uniform(1.0, 1.5))

    await ctx.send(embed=embed)

# ==============================
# RUN BOT
# ==============================
bot.run(BOT_TOKEN)
