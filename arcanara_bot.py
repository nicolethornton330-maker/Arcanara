# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import random
import json
from pathlib import Path
import re
import difflib
import unicodedata

# ==============================
# CONFIGURATION
# ==============================
import os

# Load your bot token securely from an environment variable
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError(
        "❌ BOT_TOKEN environment variable not found.\n"
        "Please set it in your Render/host environment settings."
    )

RESTRICT_TO_CHANNEL = False  # set to False if you want commands anywhere

# ==============================
# LOAD TAROT JSON
# ==============================
def load_tarot_json():
    # Look for Tarot_Official.JSON in the same directory as this script
    base_dir = Path(__file__).resolve().parent
    json_path = base_dir / "Tarot_Official.JSON"

    if not json_path.exists():
        raise FileNotFoundError(
            f"❌ Tarot JSON not found at {json_path}. "
            "Make sure 'Tarot_Official.JSON' is in the same directory as this file."
        )

    print(f"🔮 Loading tarot data from: {json_path}")
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
    "sun": "\U0001F31E", "moon": "\U0001F31A", "crystal": "\U0001F52E",
    "light": "\U0001F4A1", "clock": "\U0001F570", "star": "\U0001F31F",
    "book": "\U0001F4D6", "spark": "\u2728", "comet": "\U0001F4AB",
    "warn": "\u26A0", "fire": "\U0001F525", "water": "\U0001F4A7",
    "sword": "\u2694\ufe0f", "leaf": "\U0001F33F", "arcana": "\U0001F30C",
    "shuffle": "\U0001F501"
}

# ==============================
# HELPERS / STORAGE
# ==============================
last_readings = {}
user_intentions = {}

NUMEROLOGY_MAP = {
    0: "0 — Infinite potential, beginnings before form.",
    1: "1 — Leadership, creation, individuality.",
    2: "2 — Duality, partnership, balance, intuition.",
    3: "3 — Creativity, joy, communication.",
    4: "4 — Structure, discipline, foundation.",
    5: "5 — Change, freedom, adaptability.",
    6: "6 — Harmony, nurturing, love.",
    7: "7 — Reflection, spirituality, wisdom.",
    8: "8 — Power, success, mastery.",
    9: "9 — Completion, compassion, release.",
    10: "10 — Wholeness, cycles, evolution.",
}

def get_numerology_text(num):
    if not isinstance(num, int):
        return "—"
    if num in NUMEROLOGY_MAP:
        return NUMEROLOGY_MAP[num]
    reduced = sum(int(d) for d in str(num))
    while reduced > 9:
        reduced = sum(int(d) for d in str(reduced))
    return f"{num} → {NUMEROLOGY_MAP.get(reduced, f'Vibration of {reduced}.')}"

def draw_card():
    card = random.choice(tarot_cards)
    orientation = random.choice(["Upright", "Reversed"])
    meaning = card["upright"] if orientation == "Upright" else card["reversed"]
    return card, orientation, meaning

def draw_unique_cards(num_cards: int):
    """Draw unique cards for multi-card spreads."""
    deck_copy = tarot_cards.copy()
    random.shuffle(deck_copy)
    drawn = []
    for _ in range(min(num_cards, len(deck_copy))):
        card = deck_copy.pop()
        orientation = random.choice(["Upright", "Reversed"])
        meaning = card["upright"] if orientation == "Upright" else card["reversed"]
        drawn.append((card, orientation, meaning))
    return drawn

NUM_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"
}
NUM_WORDS_RE = re.compile(r"\b(" + "|".join(NUM_WORDS.keys()) + r")\b")

def strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))

def normalize_name(s: str) -> str:
    s = strip_accents(s.lower().strip())
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s)
    s = NUM_WORDS_RE.sub(lambda m: NUM_WORDS[m.group(1)], s)
    s = re.sub(r"^the\s+", "", s)
    return s

def find_cards(query: str, max_fuzzy: int = 6):
    q = normalize_name(query)
    names_norm = [normalize_name(c["name"]) for c in tarot_cards]
    exact = [c for c in tarot_cards if normalize_name(c["name"]) == q]
    if exact:
        return exact
    starts = [c for c in tarot_cards if normalize_name(c["name"]).startswith(q)]
    if starts:
        return starts
    tokens = q.split()
    token_hits = [c for c in tarot_cards if all(t in normalize_name(c["name"]) for t in tokens)]
    if token_hits:
        return token_hits
    fuzzy_names = difflib.get_close_matches(q, names_norm, n=max_fuzzy, cutoff=0.6)
    fuzzy = [c for c in tarot_cards if normalize_name(c["name"]) in fuzzy_names]
    return fuzzy

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

async def channel_check(ctx):
    return True  # easy mode for now

def get_intent_text(user_id):
    return user_intentions.get(user_id, "No specific intention set.")

# ==============================
# EVENTS
# ==============================
@bot.event
async def on_ready():
    print(f"{E['crystal']} Arcanara is online as {bot.user}")

# ==============================
# COMMANDS
# ==============================
@bot.command(name="shuffle")
async def shuffle(ctx):
    random.shuffle(tarot_cards)
    embed = discord.Embed(
        title=f"{E['shuffle']} The deck has been cleansed and shuffled!",
        description="Energy reset complete. The cards are ready to speak again.",
        color=0x9370DB
    )
    embed.set_footer(text=f"{E['spark']} Intention renewed • Arcanara Tarot Bot")
    await ctx.send(embed=embed)

@bot.command(name="intent")
async def intent(ctx, *, message: str = None):
    if not message:
        current = get_intent_text(ctx.author.id)
        await ctx.send(f"{E['light']} Your current intention: *{current}*")
        return

    user_intentions[ctx.author.id] = message
    card, orientation, meaning = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]
    num_text = get_numerology_text(card.get("numerology"))

    embed = discord.Embed(
        title=f"{E['crystal']} Intention Reading — {message.capitalize()}",
        description=f"**{suit_emoji(card['suit'])} {card['name']} ({orientation} {tone})**\n\n{meaning}",
        color=suit_color(card["suit"])
    )
    embed.add_field(name="Numerology", value=num_text, inline=True)
    embed.add_field(name="Theme", value=card.get("theme", "—"), inline=False)
    await ctx.send(embed=embed)

@bot.command(name="cardoftheday")
async def card_of_the_day(ctx):
    card, orientation, meaning = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]
    num_text = get_numerology_text(card.get("numerology"))
    embed = discord.Embed(
        title=f"{E['crystal']} Card of the Day {E['crystal']}",
        description=f"**{suit_emoji(card['suit'])} {card['name']} ({orientation} {tone})**\n\n{meaning}",
        color=suit_color(card["suit"])
    )
    embed.add_field(name="Numerology", value=num_text, inline=False)
    await ctx.send(embed=embed)

@bot.command(name="threecard")
async def three_card(ctx):
    positions = [f"Past {E['clock']}", f"Present {E['moon']}", f"Future {E['star']}"]
    cards = draw_unique_cards(3)
    embed = discord.Embed(
        title=f"{E['crystal']} Three Card Spread",
        description="Past • Present • Future",
        color=0xA020F0
    )
    for pos, (card, orientation, meaning) in zip(positions, cards):
        embed.add_field(name=f"{pos}: {card['name']} ({orientation})", value=meaning, inline=False)
    await ctx.send(embed=embed)

@bot.command(name="drawcards", aliases=["pull"])
async def draw_many(ctx, number_of_cards: int = 1):
    if number_of_cards < 1 or number_of_cards > 10:
        await ctx.send(f"{E['warn']} Please choose between **1 and 10 cards.**")
        return
    cards = draw_unique_cards(number_of_cards)
    embed = discord.Embed(
        title=f"{E['crystal']} {number_of_cards}-Card Draw",
        description=f"You drew **{number_of_cards}** cards from the deck.",
        color=0xA020F0
    )
    for i, (card, orientation, meaning) in enumerate(cards, start=1):
        tone = E["sun"] if orientation == "Upright" else E["moon"]
        embed.add_field(
            name=f"Card {i}: {card['name']} ({orientation} {tone})",
            value=meaning, inline=False
        )
    await ctx.send(embed=embed)

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
        description="A deep and intuitive 10-card spread exploring your path.",
        color=0xA020F0
    )
    for pos, (card, orientation, meaning) in zip(positions, cards):
        embed.add_field(name=f"{pos}: {card['name']} ({orientation})", value=meaning, inline=False)
    await ctx.send(embed=embed)

@bot.command(name="clarify")
async def clarify(ctx):
    card, orientation, meaning = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]
    embed = discord.Embed(
        title=f"{E['light']} Clarifier Card",
        description=f"**{card['name']} ({orientation} {tone})**\n\n{meaning}",
        color=suit_color(card["suit"])
    )
    await ctx.send(embed=embed)

@bot.command(name="meaning", aliases=["lookup", "info", "define", "cardinfo"])
async def meaning(ctx, *, query: str):
    matches = find_cards(query)
    if not matches:
        await ctx.send(f"{E['warn']} Could not find **{query}**.")
        return
    card = matches[0]
    num_text = get_numerology_text(card.get("numerology"))
    embed = discord.Embed(
        title=f"{E['book']} {card['name']} Meanings",
        color=suit_color(card["suit"])
    )
    embed.add_field(name=f"Upright {E['sun']}", value=card.get("upright", "—"), inline=False)
    embed.add_field(name=f"Reversed {E['moon']}", value=card.get("reversed", "—"), inline=False)
    embed.add_field(name="Numerology", value=num_text, inline=True)
    await ctx.send(embed=embed)

@bot.command(name="wisdom")
async def wisdom(ctx):
    embed = discord.Embed(
        title=f"{E['spark']} Arcanara Tarot Bot Commands",
        color=0x9370DB,
        description="A guide to your tarot commands:"
    )
    embed.add_field(name="!intent", value="Set or view your intention.", inline=False)
    embed.add_field(name="!cardoftheday", value="Draw a daily tarot card.", inline=False)
    embed.add_field(name="!threecard", value="Draw a 3-card spread.", inline=False)
    embed.add_field(name="!drawcards or !pull", value="Draw up to 10 cards.", inline=False)
    embed.add_field(name="!celtic", value="Perform a Celtic Cross spread.", inline=False)
    embed.add_field(name="!meaning <card>", value="Show a card’s full meaning.", inline=False)
    embed.add_field(name="!clarify", value="Draw a clarifier card.", inline=False)
    embed.set_footer(text=f"{E['light']} Trust your intuition • Arcanara Tarot Bot")
    await ctx.send(embed=embed)

# ==============================
# RUN BOT
# ==============================
bot.run(BOT_TOKEN)
