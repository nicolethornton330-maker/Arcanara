# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import random
import json
from pathlib import Path
import asyncio
import os

# ==============================
# CONFIGURATION
# ==============================
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError(
        "❌ BOT_TOKEN environment variable not found.\n"
        "Please set it in your Render/host environment settings."
    )

RESTRICT_TO_CHANNEL = False  # set True to restrict commands to one channel
CHANNEL_ID = 000000000000000000  # optional: replace with your channel ID if restricting

# ==============================
# LOAD TAROT JSON
# ==============================
def load_tarot_json():
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
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

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
    if num_cards > len(tarot_cards):
        raise ValueError("Requested more cards than available in the deck.")
    deck_copy = tarot_cards.copy()
    random.shuffle(deck_copy)
    drawn = []
    for _ in range(num_cards):
        card = deck_copy.pop()
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


async def channel_check(ctx):
    if RESTRICT_TO_CHANNEL and ctx.channel.id != CHANNEL_ID:
        await ctx.send(f"{E['warn']} This command only works in <#{CHANNEL_ID}>.")
        return False
    return True


def get_intent_text(user_id):
    return user_intentions.get(user_id, "No specific intention set.")


# ==============================
# EVENTS
# ==============================
@bot.event
async def on_ready():
    print(f"{E['crystal']} Arcanara is online as {bot.user}")


# ==============================
# COMMANDS WITH ALIASES & THINKING EFFECT
# ==============================
@bot.command(name="shuffle", aliases=["reset", "cleanse"])
async def shuffle(ctx):
    if not await channel_check(ctx): return
    async with ctx.typing():
        await asyncio.sleep(2)
        random.shuffle(tarot_cards)
        embed = discord.Embed(
            title=f"{E['shuffle']} The deck has been cleansed and shuffled!",
            description="Energy reset complete. The cards are ready to speak again.",
            color=0x9370DB
        )
        embed.set_footer(text=f"{E['spark']} Intention renewed • !arcanara")
    await ctx.send(embed=embed)


@bot.command(name="intent", aliases=["focus", "setintent", "intention"])
async def intent(ctx, *, message: str = None):
    if not await channel_check(ctx): return
    user_id = ctx.author.id
    if not message:
        current = get_intent_text(user_id)
        await ctx.send(f"{E['light']} Your current intention: *{current}*")
        return

    async with ctx.typing():
        await asyncio.sleep(2)
        user_intentions[user_id] = message
        card, orientation, meaning = draw_card()
        tone = E["sun"] if orientation == "Upright" else E["moon"]
        num_text = get_numerology_text(card.get("numerology"))

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


@bot.command(name="draw", aliases=["pull", "single", "card"])
async def draw(ctx):
    if not await channel_check(ctx): return
    user_id = ctx.author.id
    shuffle_msg = await ctx.send(f"{E['shuffle']} Shuffling the cards... focusing on your energy.")
    await asyncio.sleep(2.5)

    async with ctx.typing():
        await shuffle_msg.edit(content=f"{E['crystal']} The cards are ready...")
        await asyncio.sleep(1.5)
        card, orientation, meaning = draw_card()
        tone = E["sun"] if orientation == "Upright" else E["moon"]
        num_text = get_numerology_text(card.get("numerology"))
        intention = get_intent_text(user_id)

        embed = discord.Embed(
            title=f"{E['crystal']} Single Card Draw {E['crystal']}",
            description=f"**{suit_emoji(card['suit'])} {card['name']} ({orientation} {tone})**\n\n{meaning}",
            color=suit_color(card["suit"])
        )
        embed.add_field(name="Numerology", value=num_text, inline=False)
        embed.add_field(name="Theme", value=card.get("theme", "—"), inline=False)
        embed.add_field(name=f"Guidance {E['light']}", value=card.get("guidance", "—"), inline=False)
        embed.add_field(name=f"Call to Action {E['crystal']}", value=card.get("call_to_action", "—"), inline=False)
        embed.set_footer(text=f"{E['spark']} Intention: {intention}")

    await ctx.send(embed=embed)


@bot.command(name="insight", aliases=["spread", "reading", "three"])
async def insight(ctx, *, question: str = "What insight do I need right now?"):
    if not await channel_check(ctx): return
    user_id = ctx.author.id
    intention = get_intent_text(user_id)
    shuffle_msg = await ctx.send(f"{E['shuffle']} Drawing insight cards for your question...")
    await asyncio.sleep(2)

    async with ctx.typing():
        await shuffle_msg.edit(content=f"{E['crystal']} The insight is forming...")
        await asyncio.sleep(2)
        positions = ["Situation", "Obstacle", "Advice"]
        cards = draw_unique_cards(3)

        embed = discord.Embed(
            title=f"{E['crystal']} Insight Spread {E['crystal']}",
            description=f"**Question:** {question}\n\nExploring your current energy and growth.",
            color=0xA020F0
        )
        for pos, (card, orientation, meaning) in zip(positions, cards):
            tone = E["sun"] if orientation == "Upright" else E["moon"]
            embed.add_field(
                name=f"{pos}: {suit_emoji(card['suit'])} {card['name']} ({orientation} {tone})",
                value=meaning, inline=False
            )

        embed.set_footer(text=f"{E['spark']} Intention: {intention}")
        last_readings[user_id] = {"type": "Insight", "cards": cards, "question": question}

    await ctx.send(embed=embed)


@bot.command(name="clarify", aliases=["clarifier", "followup"])
async def clarify(ctx):
    if not await channel_check(ctx): return
    user_id = ctx.author.id
    last = last_readings.get(user_id)
    if not last:
        await ctx.send(f"{E['warn']} You don’t have a recent reading to clarify.")
        return

    shuffle_msg = await ctx.send(f"{E['shuffle']} Seeking clarification from the deck...")
    await asyncio.sleep(2.5)

    async with ctx.typing():
        await shuffle_msg.edit(content=f"{E['crystal']} The clarifying energy is emerging...")
        await asyncio.sleep(1.5)
        card, orientation, meaning = draw_card()
        tone = E["sun"] if orientation == "Upright" else E["moon"]

        embed = discord.Embed(
            title=f"{E['crystal']} Clarifying Card {E['crystal']}",
            description=(
                f"For your previous **{last['type']}** reading:\n\n"
                f"**{suit_emoji(card['suit'])} {card['name']} ({orientation} {tone})**\n\n{meaning}"
            ),
            color=suit_color(card["suit"])
        )
        embed.set_footer(text=f"{E['spark']} Seek the subtle thread of connection • Arcanara Tarot Bot")

    await ctx.send(embed=embed)


@bot.command(name="wisdom", aliases=["collective", "message", "daily"])
async def wisdom(ctx):
    if not await channel_check(ctx): return
    shuffle_msg = await ctx.send(f"{E['shuffle']} Reaching into the Major Arcana for collective wisdom...")
    await asyncio.sleep(2.5)

    async with ctx.typing():
        await shuffle_msg.edit(content=f"{E['crystal']} The collective energy gathers...")
        await asyncio.sleep(1.5)
        majors = [c for c in tarot_cards if c.get("suit") == "Major Arcana"]
        card = random.choice(majors)
        orientation = random.choice(["Upright", "Reversed"])
        meaning = card["upright"] if orientation == "Upright" else card["reversed"]
        tone = E["sun"] if orientation == "Upright" else E["moon"]

        embed = discord.Embed(
            title=f"{E['arcana']} Collective Wisdom {E['arcana']}",
            description=f"**{card['name']} ({orientation} {tone})**\n\n{meaning}",
            color=0x9370DB
        )
        embed.set_footer(text=f"{E['spark']} The collective speaks through archetype • Arcanara Tarot Bot")

    await ctx.send(embed=embed)


# ==============================
# CUSTOM HELP COMMAND: !arcanara
# ==============================
@bot.command(name="arcanara")
async def arcanara(ctx):
    """Custom mystical help command with user’s intention shown."""
    user_id = ctx.author.id
    current_intent = get_intent_text(user_id)

    embed = discord.Embed(
        title=f"{E['crystal']} Arcanara’s Grimoire of Commands {E['crystal']}",
        description=(
            f"{E['spark']} *Your current intention:* **{current_intent}**\n\n"
            "Invoke my magic using these commands. Each begins with `!`"
        ),
        color=0xA020F0
    )
    embed.add_field(name=f"{E['shuffle']} `!shuffle`, `!reset`, `!cleanse`",
                    value="Cleanse and reshuffle the deck’s energy.", inline=False)
    embed.add_field(name=f"{E['light']} `!intent`, `!focus`, `!intention`",
                    value="Set your focus or view your current intention.", inline=False)
    embed.add_field(name=f"{E['crystal']} `!draw`, `!pull`, `!card`",
                    value="Draw a single card for a message of the moment.", inline=False)
    embed.add_field(name=f"{E['star']} `!insight`, `!spread`, `!reading`",
                    value="Three-card spread: Situation, Obstacle, and Advice.", inline=False)
    embed.add_field(name=f"{E['moon']} `!clarify`, `!clarifier`, `!followup`",
                    value="Pull one clarifying card for your last reading.", inline=False)
    embed.add_field(name=f"{E['arcana']} `!wisdom`, `!collective`, `!daily`",
                    value="Draw from the Major Arcana for a collective message.", inline=False)
    embed.set_footer(text=f"{E['spark']} Trust your intuition • Arcanara Tarot Bot")
    await ctx.send(embed=embed)


# ==============================
# RUN BOT
# ==============================
if __name__ == "__main__":
    import sys
    if sys.stdin.isatty():
        input("\nPress Enter to exit...")

bot.run(BOT_TOKEN)
