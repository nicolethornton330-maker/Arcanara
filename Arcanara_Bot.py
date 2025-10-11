# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import random
import json
import asyncio
from pathlib import Path
import os
import re
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
    meaning_block = card["upright"] if orientation == "Upright" else card["reversed"]

    numerology_info = card.get("numerology", {})
    numerology_text = ""
    if isinstance(numerology_info, dict):
        num = numerology_info.get("number")
        meaning = numerology_info.get("meaning")
        if num and meaning:
            numerology_text = f"**Numerology {num}:** {meaning}\n\n"

    # Handle new nested meaning format
    if isinstance(meaning_block, dict):
        description = meaning_block.get("description", "")
        guidance = meaning_block.get("guidance", "")
        call = meaning_block.get("call_to_action", "")
        theme = meaning_block.get("theme", "")

        parts = []
        if theme:
            parts.append(f"**Theme:** {theme}")
        if numerology_text:
            parts.append(numerology_text.strip())
        if description:
            parts.append(description)
        if guidance:
            parts.append(f"\n{E['light']} **Guidance:** {guidance}")
        if call:
            parts.append(f"{E['spark']} **Call to Action:** {call}")

        meaning_text = "\n\n".join(parts)
    else:
        meaning_text = str(meaning_block)

    return card, orientation, meaning_text

def draw_unique_cards(num_cards: int):
    deck = tarot_cards.copy()
    random.shuffle(deck)
    drawn = []
    for _ in range(min(num_cards, len(deck))):
        card = deck.pop()
        orientation = random.choice(["Upright", "Reversed"])
        meaning_block = card["upright"] if orientation == "Upright" else card["reversed"]

        numerology_info = card.get("numerology", {})
        numerology_text = ""
        if isinstance(numerology_info, dict):
            num = numerology_info.get("number")
            meaning = numerology_info.get("meaning")
            if num and meaning:
                numerology_text = f"**Numerology {num}:** {meaning}\n\n"

        if isinstance(meaning_block, dict):
            description = meaning_block.get("description", "")
            guidance = meaning_block.get("guidance", "")
            call = meaning_block.get("call_to_action", "")
            theme = meaning_block.get("theme", "")

            parts = []
            if theme:
                parts.append(f"**Theme:** {theme}")
            if numerology_text:
                parts.append(numerology_text.strip())
            if description:
                parts.append(description)
            if guidance:
                parts.append(f"\n{E['light']} **Guidance:** {guidance}")
            if call:
                parts.append(f"{E['spark']} **Call to Action:** {call}")

            meaning_text = "\n\n".join(parts)
        else:
            meaning_text = str(meaning_block)

        drawn.append((card, orientation, meaning_text))
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

def format_card_meaning(card, orientation):
    """Formats a tarot card meaning, including numerology and extra guidance."""
    meaning_block = card["upright"] if orientation == "Upright" else card["reversed"]

    # Pull numerology info
    num_info = card.get("numerology")
    numerology_section = ""
    if isinstance(num_info, dict):
        num = num_info.get("number")
        meaning = num_info.get("meaning")
        if num and meaning:
            numerology_section = f"**Numerology {num}:** {meaning}\n\n"

    # Handle dictionary-style meaning blocks
    if isinstance(meaning_block, dict):
        theme = meaning_block.get("theme")
        desc = meaning_block.get("description")
        guide = meaning_block.get("guidance")
        call = meaning_block.get("call_to_action")

        parts = []
        if theme:
            parts.append(f"**Theme:** {theme}")
        if numerology_section:
            parts.append(numerology_section.strip())
        if desc:
            # Bold the card name at the start of the description,
            # even if it begins with "The <Card Name> ..."
            card_name = card.get("name", "")
            if card_name:
                pat = re.compile(rf"^(\s*)(?:([Tt]he)\s+)?({re.escape(card_name)})\b")
                desc = pat.sub(
                    lambda m: f"{m.group(1)}{(m.group(2) + ' ') if m.group(2) else ''}**{card_name}**",
                    desc,
                    count=1
                )
            parts.append(desc)
        if guide:
            parts.append(f"{E['light']} **Guidance:** {guide}")
        if call:
            parts.append(f"{E['spark']} **Call to Action:** {call}")

        return "\n\n".join(parts)

    # Handle legacy string meanings
    text = str(meaning_block)
    if numerology_section:
        text = numerology_section + text
    return text

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
    card, orientation, _ = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]
    intent_text = user_intentions.get(ctx.author.id)

    meaning_text = format_card_meaning(card, orientation)

    desc = f"**{card['name']} ({orientation} {tone})**\n\n{meaning_text}"
    if intent_text:
        desc += f"\n\n{E['light']} **Focus:** *{intent_text}*"

    embed = discord.Embed(
        title=f"{E['crystal']} Card of the Day",
        description=desc,
        color=suit_color(card["suit"])
    )

    await send_with_typing(ctx, embed, delay_range=(1.5, 2.5), mood="daily")

@bot.command(name="read")
async def read(ctx, *, message: str = None):
    """Performs a focused three-card reading based on the user's question or theme."""
    if not message:
        await ctx.send(f"{E['warn']} Please include a question or focus after the command. Example: `!read my career path`")
        return

    # Store or reuse user's focus
    user_intentions[ctx.author.id] = message

    cards = draw_unique_cards(3)
    positions = [
        f"Situation {E['sun']}",
        f"Obstacle {E['sword']}",
        f"Guidance {E['star']}"
    ]

    desc = f"{E['light']} **Focus:** *{message}*\n\nThree cards emerge to illuminate your path:"

    embed = discord.Embed(
        title=f"{E['crystal']} Intuitive Reading {E['crystal']}",
        description=desc,
        color=0x9370DB
    )

    for pos, (card, orientation, _) in zip(positions, cards):
        meaning_text = format_card_meaning(card, orientation)
        embed.add_field(
            name=f"{pos}: {card['name']} ({orientation})",
            value=meaning_text,
            inline=False
    )

    embed.set_footer(
        text=f"{E['spark']} Let these cards guide your awareness, not dictate your choices."
    )

    await send_with_typing(ctx, embed, delay_range=(2.5, 4.0), mood="spread")

@bot.command(name="threecard")
async def three_card(ctx):
    positions = [f"Past {E['clock']}", f"Present {E['moon']}", f"Future {E['star']}"]
    cards = draw_unique_cards(3)
    intent_text = user_intentions.get(ctx.author.id)

    desc = "Past • Present • Future"
    if intent_text:
        desc += f"\n\n{E['light']} **Focus:** *{intent_text}*"

    embed = discord.Embed(
        title=f"{E['crystal']} Three-Card Spread",
        description=desc,
        color=0xA020F0
        )

    for pos, (card, orientation, _) in zip(positions, cards):
        meaning_text = format_card_meaning(card, orientation)
        embed.add_field(
            name=f"{pos}: {card['name']} ({orientation})",
            value=meaning_text,
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
    embed = discord.Embed(
        title=f"{E['crystal']} Celtic Cross Spread {E['crystal']}",
        description="A deep, archetypal exploration of your path.",
        color=0xA020F0
    )

    total_length = len(embed.title) + len(embed.description)
    fields_buffer = []

    for pos, (card, orientation, meaning) in zip(positions, cards):
        field_name = f"{pos}: {card['name']} ({orientation})"
        meaning_text = format_card_meaning(card, orientation)
        field_value = meaning_text if len(meaning_text) < 1000 else meaning_text[:997] + "..."
        field_length = len(field_name) + len(field_value)

        # Check if adding this field would exceed Discord's limit
        if total_length + field_length > 5800:
            # Send current embed and start a new one
            await send_with_typing(ctx, embed, delay_range=(3.0, 4.0), mood="deep")
            embed = discord.Embed(
                title=f"{E['crystal']} Celtic Cross Spread (Continued)",
                color=0xA020F0
            )
            total_length = len(embed.title)

        embed.add_field(name=field_name, value=field_value, inline=False)
        total_length += field_length

    await send_with_typing(ctx, embed, delay_range=(3.0, 4.0), mood="deep")

@bot.command(name="meaning")
async def meaning(ctx, *, query: str):
    """Displays a detailed meaning for a specific Tarot card, including numerology and guidance."""
    norm_query = normalize_card_name(query)

    # Find card match
    matches = [
        c for c in tarot_cards
        if normalize_card_name(c["name"]) == norm_query
        or norm_query in normalize_card_name(c["name"])
    ]

    if not matches:
        await ctx.send(f"{E['warn']} I searched the deck but found no card named **{query}**.")
        return

    card = matches[0]
    numerology_info = card.get("numerology", {})
    numerology_text = ""
    if isinstance(numerology_info, dict):
        num = numerology_info.get("number")
        meaning = numerology_info.get("meaning")
        if num and meaning:
            numerology_text = f"**Numerology {num}:** {meaning}"

    # Function to format upright/reversed text cleanly
    def format_meaning(block):
        if isinstance(block, dict):
            parts = []
            theme = block.get("theme")
            desc = block.get("description")
            guide = block.get("guidance")
            call = block.get("call_to_action")

            if theme:
                parts.append(f"**Theme:** {theme}")
            if desc:
                parts.append(desc)
            if guide:
                parts.append(f"{E['light']} **Guidance:** {guide}")
            if call:
                parts.append(f"{E['spark']} **Call to Action:** {call}")
            return "\n\n".join(parts)
        return str(block)

    upright_text = format_card_meaning(card, "Upright")
    reversed_text = format_card_meaning(card, "Reversed")

    embed = discord.Embed(
        title=f"{E['book']} {card['name']}",
        description=f"**Suit:** {card.get('suit', 'Unknown')}\n**Theme:** {card.get('theme', '—')}",
        color=suit_color(card["suit"])
    )
    embed.add_field(name=f"Upright {E['sun']}", value=upright_text, inline=False)
    embed.add_field(name=f"Reversed {E['moon']}", value=reversed_text, inline=False)
    embed.set_footer(text=f"{E['light']} Interpreting symbols through Arcanara's Wisdom")

    async with ctx.typing():
        await asyncio.sleep(random.uniform(1.0, 2.0))

    await ctx.send(embed=embed)
    
@bot.command(name="clarify")
async def clarify(ctx):
    """Draws a clarifying card related to your most recent reading or focus, with full numerology and guidance."""
    card, orientation, meaning_block = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]
    intent_text = user_intentions.get(ctx.author.id)

    # Numerology section
    numerology_info = card.get("numerology", {})
    numerology_text = ""
    if isinstance(numerology_info, dict):
        num = numerology_info.get("number")
        meaning = numerology_info.get("meaning")
        if num and meaning:
            numerology_text = f"**Numerology {num}:** {meaning}\n\n"

    # Format meaning structure
    def format_block(block):
        if isinstance(block, dict):
            parts = []
            theme = block.get("theme")
            desc = block.get("description")
            guide = block.get("guidance")
            call = block.get("call_to_action")
            if theme:
                parts.append(f"**Theme:** {theme}")
            if desc:
                parts.append(desc)
            if guide:
                parts.append(f"{E['light']} **Guidance:** {guide}")
            if call:
                parts.append(f"{E['spark']} **Call to Action:** {call}")
            return "\n\n".join(parts)
        return str(block)

    meaning_text = format_block(meaning_block)

    desc = f"**{card['name']} ({orientation} {tone})**\n\n{numerology_text}{meaning_text}"

    if intent_text:
        desc += f"\n\n{E['light']} **Clarifying Focus:** *{intent_text}*"

    embed = discord.Embed(
        title=f"{E['light']} Clarifier Card {E['light']}",
        description=desc,
        color=suit_color(card["suit"])
    )

    embed.set_footer(
        text=f"{E['spark']} A clarifier shines a smaller light within your larger spread."
    )

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

# ==============================
# MYSTERY + REVEAL COMMANDS
# ==============================
mystery_draws = {}  # Temporary storage of mystery cards per user

@bot.command(name="mystery")
async def mystery(ctx):
    """Draws a silent card for intuitive reflection."""
    card, orientation, meaning = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]
    suit_symbol = suit_emoji(card["suit"])

    # Store the hidden card for later reveal
    mystery_draws[ctx.author.id] = {
        "card": card,
        "orientation": orientation,
        "meaning": meaning
    }

    embed = discord.Embed(
        title=f"{E['moon']} The Mystery Card {E['moon']}",
        description=(
            f"**{card['name']} ({orientation} {tone})**\n\n"
            f"{suit_symbol} *The meaning of this card is hidden.*\n"
            "Close your eyes, breathe deeply, and let your intuition speak before seeking its written meaning."
        ),
        color=suit_color(card["suit"])
    )

    embed.set_footer(
        text=f"{E['crystal']} When you're ready, whisper `!reveal` to learn what the card truly meant."
    )

    await send_with_typing(ctx, embed, delay_range=(2.0, 3.5), mood="deep")


@bot.command(name="reveal")
async def reveal(ctx):
    """Reveals the meaning of the last mystery card drawn, including numerology and guidance."""
    data = mystery_draws.get(ctx.author.id)
    if not data:
        await ctx.send(f"{E['warn']} You have no mystery card waiting to be revealed. Use `!mystery` first.")
        return

    card = data["card"]
    orientation = data["orientation"]
    meaning_block = data["meaning"]
    tone = E["sun"] if orientation == "Upright" else E["moon"]

    # Numerology
    numerology_info = card.get("numerology", {})
    numerology_text = ""
    if isinstance(numerology_info, dict):
        num = numerology_info.get("number")
        meaning = numerology_info.get("meaning")
        if num and meaning:
            numerology_text = f"**Numerology {num}:** {meaning}\n\n"

    # Format meaning section
    def format_block(block):
        if isinstance(block, dict):
            parts = []
            theme = block.get("theme")
            desc = block.get("description")
            guide = block.get("guidance")
            call = block.get("call_to_action")
            if theme:
                parts.append(f"**Theme:** {theme}")
            if desc:
                parts.append(desc)
            if guide:
                parts.append(f"{E['light']} **Guidance:** {guide}")
            if call:
                parts.append(f"{E['spark']} **Call to Action:** {call}")
            return "\n\n".join(parts)
        return str(block)

    meaning_text = format_block(meaning_block)

    desc = (
        f"**{card['name']} ({orientation} {tone})**\n\n"
        f"{numerology_text}{meaning_text}"
    )

    embed = discord.Embed(
        title=f"{E['light']} The Mystery Revealed {E['light']}",
        description=desc,
        color=suit_color(card["suit"])
    )

    embed.set_footer(
        text=f"{E['crystal']} The veil lifts — may the message settle where it’s meant to."
    )

    # Clear stored card after reveal
    del mystery_draws[ctx.author.id]

    await send_with_typing(ctx, embed, delay_range=(1.5, 2.5), mood="deep")

    
# ==============================
# RUN BOT
# ==============================
bot.run(BOT_TOKEN)