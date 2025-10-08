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
    json_path = Path(r"C:\Users\Nicole\Tarot\Tarot_Official.JSON")
    if not json_path.exists():
        raise FileNotFoundError(f"Tarot JSON not found at {json_path}.")
    with json_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)

tarot_cards = load_tarot_json()

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
user_intentions = {}  # user_id -> current intention string

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

# Convert number words to digits for flexible matching
# Words ↔ digits for flexible number matching
NUM_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"
}
NUM_WORDS_RE = re.compile(r"\b(" + "|".join(NUM_WORDS.keys()) + r")\b")

def strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))

def normalize_name(s: str) -> str:
    s = strip_accents(s.lower().strip())
    # unifying punctuation/spacing
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s)

    # convert number words to digits (five -> 5)
    s = NUM_WORDS_RE.sub(lambda m: NUM_WORDS[m.group(1)], s)

    # make “the fool” and “fool” equivalent
    s = re.sub(r"^the\s+", "", s)

    return s

def find_cards(query: str, max_fuzzy: int = 6):
    """Return a list of best card matches for the query (could be 0, 1, or many)."""
    q = normalize_name(query)
    names_norm = [normalize_name(c["name"]) for c in tarot_cards]

    # 1) Exact
    exact = [c for c in tarot_cards if normalize_name(c["name"]) == q]
    if exact:
        return exact

    # 2) Startswith (e.g., 'five of' or 'fiv')
    starts = [c for c in tarot_cards if normalize_name(c["name"]).startswith(q)]
    if starts:
        return starts

    # 3) All tokens containment (e.g., 'five wands' -> 'five of wands')
    tokens = q.split()
    token_hits = [
        c for c in tarot_cards
        if all(t in normalize_name(c["name"]) for t in tokens)
    ]
    if token_hits:
        return token_hits

    # 4) Fuzzy (typos etc.)
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
    """Restrict to a specific channel if enabled."""
    if RESTRICT_TO_CHANNEL and ctx.channel.id != CHANNEL_ID:
        await ctx.send(f"{E['warn']} This command only works in <#{CHANNEL_ID}>.")
        return False
    return True

def get_intent_text(user_id):
    """Return the user’s active intention, or a default message."""
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
    if not await channel_check(ctx): return
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
    """Set your intention, draw one card, and store it for clarification."""
    if not await channel_check(ctx):
        return
    user_id = ctx.author.id

    # If the user didn't specify anything, just show their current one
    if not message:
        current = get_intent_text(user_id)
        await ctx.send(f"{E['light']} Your current intention: *{current}*")
        return

    # Save the user's intention
    user_intentions[user_id] = message

    # Draw a card for that intention
    card, orientation, meaning = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]
    num_text = get_numerology_text(card.get("numerology"))

    # Store reading so !clarify knows what to build on
    last_readings[user_id] = {
        "type": "Intention Reading",
        "intention": message,
        "cards": [(card, orientation, meaning)]
    }

    # Create the reading embed
    embed = discord.Embed(
        title=f"{E['crystal']} Intention Reading — {message.capitalize()} {E['crystal']}",
        description=f"**{suit_emoji(card['suit'])} {card['name']} ({orientation} {tone})**\n\n{meaning}",
        color=suit_color(card["suit"])
    )
    embed.add_field(name="Suit", value=f"{suit_emoji(card['suit'])} {card['suit']}", inline=True)
    embed.add_field(name="Numerology", value=num_text, inline=True)
    embed.add_field(name="Theme", value=card.get("theme", "—"), inline=False)
    embed.add_field(name=f"Guidance {E['light']}", value=card.get("guidance", "—"), inline=False)
    embed.add_field(name=f"Call to Action {E['crystal']}", value=card.get("call_to_action", "—"), inline=False)
    embed.set_footer(text=f"{E['spark']} Intention set: {message.capitalize()} • Trust what arises")

    await ctx.send(embed=embed)

@bot.command(name="cardoftheday")
async def card_of_the_day(ctx):
    if not await channel_check(ctx): return
    user_id = ctx.author.id
    card, orientation, meaning = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]
    num_text = get_numerology_text(card.get("numerology"))
    intention = get_intent_text(user_id)

    embed = discord.Embed(
        title=f"{E['crystal']} Card of the Day {E['crystal']}",
        description=f"**{suit_emoji(card['suit'])} {card['name']} ({orientation} {tone})**\n\n{meaning}",
        color=suit_color(card["suit"])
    )
    embed.add_field(name="Numerology", value=num_text, inline=False)
    embed.add_field(name="Theme", value=card.get("theme", "—"), inline=False)
    embed.add_field(name=f"Guidance {E['light']}", value=card.get("guidance", "—"), inline=False)
    embed.add_field(name=f"Call to Action {E['crystal']}", value=card.get("call_to_action", "—"), inline=False)
    embed.set_footer(text=f"{E['spark']} Intention: {intention}")
    await ctx.send(embed=embed)

@bot.command(name="threecard")
async def three_card(ctx):
    if not await channel_check(ctx): return
    user_id = ctx.author.id
    intention = get_intent_text(user_id)
    positions = [f"Past {E['clock']}", f"Present {E['moon']}", f"Future {E['star']}"]
    cards = [draw_card() for _ in range(3)]
    embed = discord.Embed(
        title=f"{E['crystal']} Three Card Spread",
        description="Past • Present • Future",
        color=0xA020F0
    )
    for pos, (card, orientation, meaning) in zip(positions, cards):
        embed.add_field(
            name=f"{pos}: {suit_emoji(card['suit'])} {card['name']} ({orientation})",
            value=meaning, inline=False
        )
    embed.set_footer(text=f"{E['spark']} Intention: {intention}")
    await ctx.send(embed=embed)

@bot.command(name="read")
async def read(ctx, *, question: str):
    if not await channel_check(ctx): return
    user_id = ctx.author.id
    intention = get_intent_text(user_id)
    positions = ["Situation", "Challenge", "Advice"]
    cards = [draw_card() for _ in positions]
    embed = discord.Embed(
        title=f"{E['crystal']} Guided Reading",
        description=f"**Your question:** {question}",
        color=0xA020F0
    )
    for pos, (card, orientation, meaning) in zip(positions, cards):
        embed.add_field(
            name=f"{pos}: {suit_emoji(card['suit'])} {card['name']} ({orientation})",
            value=meaning, inline=False
        )
    embed.set_footer(text=f"{E['spark']} Intention: {intention}")
    await ctx.send(embed=embed)

@bot.command(name="clarify")
async def clarify(ctx):
    """Pull a clarifying card for the most recent reading or intention."""
    if not await channel_check(ctx):
        return

    user_id = ctx.author.id

    # Check if user has a previous reading
    if user_id not in last_readings:
        await ctx.send(f"{E['warn']} You don’t have an active reading to clarify.")
        return

    prev = last_readings[user_id]
    clarifier, orientation, meaning = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]

    # Determine intention label
    intention_text = prev.get("intention", get_intent_text(user_id))

    # Build embed
    embed = discord.Embed(
        title=f"{E['light']} Clarifier for {prev.get('type', 'Reading')}",
        description=f"**{suit_emoji(clarifier['suit'])} {clarifier['name']} ({orientation} {tone})**\n\n{meaning}",
        color=suit_color(clarifier["suit"])
    )

    # Add details
    embed.add_field(name="Suit", value=f"{suit_emoji(clarifier['suit'])} {clarifier['suit']}", inline=True)
    embed.add_field(name="Theme", value=clarifier.get("theme", "—"), inline=False)
    embed.add_field(name=f"Guidance {E['light']}", value=clarifier.get("guidance", "—"), inline=False)
    embed.add_field(name=f"Call to Action {E['crystal']}", value=clarifier.get("call_to_action", "—"), inline=False)

    # Add footer with intention if present
    footer_text = f"{E['spark']} A new layer revealed"
    if intention_text and intention_text != "No specific intention set.":
        footer_text += f" • Intention: {intention_text.capitalize()}"
    embed.set_footer(text=footer_text)

    # Send message
    await ctx.send(embed=embed)

@bot.command(name="meaning")
async def meaning(ctx, *, card_name: str):
    if not await channel_check(ctx): 
        return

    matches = find_cards(card_name)

    # No matches -> show suggestions
    if not matches:
        # suggest the closest 5 names to help the user
        all_names = [c["name"] for c in tarot_cards]
        suggestions = difflib.get_close_matches(card_name, all_names, n=5, cutoff=0.0)
        if suggestions:
            pretty = "\n".join(f"• {s}" for s in suggestions)
            await ctx.send(f"{E['warn']} I couldn’t find **{card_name}**.\nTry one of these:\n{pretty}")
        else:
            await ctx.send(f"{E['warn']} I couldn’t find **{card_name}**.")
        return

    # Multiple matches -> don’t guess; ask for specificity
    if len(matches) > 1:
        options = "\n".join(f"• {c['name']}" for c in matches[:10])
        await ctx.send(
            f"{E['warn']} That’s a bit vague—did you mean one of these?\n{options}\n\n"
            f"Tip: include the suit (e.g., `!meaning five of cups`)."
        )
        return

    # Exactly one match -> show the embed
    card = matches[0]
    num_text = get_numerology_text(card.get("numerology"))
    embed = discord.Embed(
        title=f"{E['book']} {card['name']} Meanings",
        color=suit_color(card["suit"])
    )
    embed.add_field(name="Suit", value=f"{suit_emoji(card['suit'])} {card['suit']}", inline=True)
    embed.add_field(name="Numerology", value=num_text, inline=False)
    embed.add_field(name="Theme", value=card.get("theme", "—"), inline=False)
    embed.add_field(name=f"Upright {E['sun']}", value=card["upright"], inline=False)
    embed.add_field(name=f"Reversed {E['moon']}", value=card["reversed"], inline=False)
    embed.add_field(name=f"Guidance {E['light']}", value=card.get("guidance", "—"), inline=False)
    embed.add_field(name=f"Call to Action {E['crystal']}", value=card.get("call_to_action", "—"), inline=False)
    embed.set_footer(text=f"{E['spark']} Arcanara Tarot Bot")
    await ctx.send(embed=embed)

@bot.command(name="insight")
async def insight(ctx):
    if not await channel_check(ctx): return
    embed = discord.Embed(
        title=f"{E['spark']} Arcanara Tarot Bot Commands",
        color=0x9370DB,
        description="Your magical guide to tarot readings in Discord."
    )
    embed.add_field(name="!shuffle", value="Shuffle and cleanse the deck.", inline=False)
    embed.add_field(name="!intent <message>", value="Set or view your reading intention.", inline=False)
    embed.add_field(name="!cardoftheday", value="Draw a random tarot card.", inline=False)
    embed.add_field(name="!drawcards", value="Draw as many cards as you need.", inline=False)
    embed.add_field(name="!threecard", value="Draw a 3-card spread.", inline=False)
    embed.add_field(name="!celtic <message>", value="Perform the Celtic Cross Spread.", inline=False)
    embed.add_field(name="!read <question>", value="Ask a question for a guided 3-card reading.", inline=False)
    embed.add_field(name="!clarify", value="Pull a clarifier for your last reading.", inline=False)
    embed.add_field(name="!meaning <card>", value="Show meanings, numerology, and guidance for a card.", inline=False)
    embed.set_footer(text=f"{E['light']} Stay intuitive and trust your inner wisdom.")
    await ctx.send(embed=embed)

@bot.command(name="drawcards")
async def draw_many(ctx, number_of_cards: int):
    """Draws a user-specified number of tarot cards (1–10)."""
    if number_of_cards < 1 or number_of_cards > 10:
        await ctx.send(f"{E['warn']} Please choose between **1 and 10 cards.**")
        return

    cards = [draw_card() for _ in range(number_of_cards)]
    embed = discord.Embed(
        title=f"{E['crystal']} {number_of_cards}-Card Tarot Draw {E['crystal']}",
        description=f"You’ve drawn **{number_of_cards} cards** from the deck.\n",
        color=0xA020F0
    )

    for i, (card, orientation, meaning) in enumerate(cards, start=1):
        tone = E["sun"] if orientation == "Upright" else E["moon"]
        embed.add_field(
            name=f"Card {i}: {suit_emoji(card.get('suit', 'Major Arcana'))} {card['name']} ({orientation} {tone})",
            value=meaning,
            inline=False
        )

    embed.set_footer(text=f"{E['spark']} Trust your intuition • Arcanara Tarot Bot")
    await ctx.send(embed=embed)

@bot.command(name="celtic")
async def celtic_cross(ctx):
    """Performs a traditional 10-card Celtic Cross reading."""
    user_id = ctx.author.id
    intention = user_intentions.get(user_id, "self-discovery")

    # Celtic Cross card positions and their meanings
    positions = [
        "1️⃣ Present Situation",
        "2️⃣ Challenge / Crossing Influence",
        "3️⃣ Foundation / Root Cause",
        "4️⃣ Past Influence",
        "5️⃣ Conscious Goal",
        "6️⃣ Near Future",
        "7️⃣ Self / Inner State",
        "8️⃣ External Influence",
        "9️⃣ Hopes & Fears",
        "10 Outcome / Potential Future"
    ]

    # Draw the 10 cards
    cards = [draw_card() for _ in range(10)]

    embed = discord.Embed(
        title=f"{E['crystal']} Celtic Cross Spread {E['crystal']}",
        description=(
            f"A deep and intuitive 10-card spread exploring all facets of your journey.\n"
            f"**Current Intention:** *{intention}*\n"
        ),
        color=0xA020F0
    )

    for pos, (card, orientation, meaning) in zip(positions, cards):
        tone = E["sun"] if orientation == "Upright" else E["moon"]
        embed.add_field(
            name=f"{pos}: {suit_emoji(card.get('suit', 'Major Arcana'))} {card['name']} ({orientation} {tone})",
            value=meaning,
            inline=False
        )

    embed.set_footer(text=f"{E['spark']} Trust the flow of insight • Arcanara Tarot Bot")
    await ctx.send(embed=embed)

# ==============================
# RUN BOT
# ==============================
bot.run(BOT_TOKEN)
