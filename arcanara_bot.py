# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import re
import random, time
import json
from pathlib import Path
import os
import psycopg
import traceback
from psycopg.types.json import Json
from discord.errors import HTTPException
from psycopg.rows import dict_row
from typing import Dict, Any, List, Optional
from card_images import make_image_attachment # uses assets/cards/rws_stx/ etc.

MYSTERY_STATE: Dict[int, Dict[str, Any]] = {}
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
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=10,
    )

def ensure_tables():
    """Create tables if they don't exist (safe to run on startup)."""
    with db_connect() as conn:
        with conn.cursor() as cur:
            # Existing table: user mode preference
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tarot_user_prefs (
                    user_id BIGINT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            # New table: user settings (opt-in history + images toggle)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tarot_user_settings (
                    user_id BIGINT PRIMARY KEY,
                    history_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
                    images_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            # New table: reading history (only used if opt-in)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tarot_reading_history (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    command TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_tarot_history_user_time
                ON tarot_reading_history (user_id, created_at DESC);
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
# Human-friendly mode names (reader voice)
MODE_LABELS = {
    "full":   "Full Spectrum (deep + practical)",
    "direct": "Direct (straight talk, no fluff)",
    "shadow": "Shadow Work (truth + integration)",
    "poetic": "Poetic (symbolic, soft edges)",
    "quick":  "Quick Hit (one clear message)",
    "love":   "Love Lens (people + patterns)",
    "work":   "Work Lens (purpose + friction)",
    "money":  "Money Lens (resources + decisions)",
}

def mode_label(mode: str) -> str:
    """Return a reader-style label for a mode value."""
    m = normalize_mode(mode)
    return MODE_LABELS.get(m, MODE_LABELS[DEFAULT_MODE])

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
# USER SETTINGS + HISTORY (DB-backed)
# ==============================
def get_user_settings(user_id: int) -> dict:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT history_opt_in, images_enabled
                FROM tarot_user_settings
                WHERE user_id=%s
            """, (user_id,))
            row = cur.fetchone()
    return row or {"history_opt_in": False, "images_enabled": True}

def set_user_settings(
    user_id: int,
    *,
    history_opt_in: Optional[bool] = None,
    images_enabled: Optional[bool] = None
) -> dict:
    current = get_user_settings(user_id)
    if history_opt_in is None:
        history_opt_in = current["history_opt_in"]
    if images_enabled is None:
        images_enabled = current["images_enabled"]

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tarot_user_settings (user_id, history_opt_in, images_enabled)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    history_opt_in = EXCLUDED.history_opt_in,
                    images_enabled = EXCLUDED.images_enabled,
                    updated_at = NOW()
            """, (user_id, history_opt_in, images_enabled))
        conn.commit()

    return {"history_opt_in": history_opt_in, "images_enabled": images_enabled}

def log_history_if_opted_in(
    user_id: int,
    command: str,
    mode: str,
    payload: dict,
    *,
    settings: Optional[Dict[str, Any]] = None,
) -> None:
    """
    If settings are provided, uses them (no extra DB read).
    If not provided, fetches settings from DB.
    Never crashes a command if logging fails.
    """
    try:
        if settings is None:
            settings = get_user_settings(user_id)

        if not settings.get("history_opt_in", False):
            return

        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO tarot_reading_history (user_id, command, mode, payload)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, command, mode, Json(payload)))
            conn.commit()

    except Exception as e:
        print(f"⚠️ history log failed: {type(e).__name__}: {e}")

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
BASE_DIR = Path(__file__).resolve().parent
KNOWN_SEEKERS_FILE = BASE_DIR / "known_seekers.json"

def load_known_seekers() -> Dict[str, Any]:
    if KNOWN_SEEKERS_FILE.exists():
        try:
            with KNOWN_SEEKERS_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ could not load known_seekers: {type(e).__name__}: {e}")
            return {}
    return {}

def save_known_seekers(data: Dict[str, Any]) -> None:
    try:
        with KNOWN_SEEKERS_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ could not save known_seekers: {type(e).__name__}: {e}")

known_seekers: Dict[str, Any] = load_known_seekers()
user_intentions: Dict[int, str] = {}

# ==============================
# BOT SETUP
# ==============================
intents = discord.Intents.default()
intents.guilds = True
intents.message_content = False
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

def _chunk_lines(lines: List[str], max_len: int = 950) -> List[str]:
    """Chunk lines into strings that fit comfortably in an embed field."""
    chunks: List[str] = []
    buf: List[str] = []
    size = 0
    for line in lines:
        add = len(line) + 1
        if buf and size + add > max_len:
            chunks.append("\n".join(buf))
            buf = [line]
            size = add
        else:
            buf.append(line)
            size += add
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def build_onboarding_embeds(guild: discord.Guild) -> List[discord.Embed]:
    # --- 1) Mystical + confident welcome ---
    intro = discord.Embed(
        title="🔮 Arcanara has crossed the threshold",
        description=(
            f"I have anchored to **{guild.name}**.\n\n"
            "I don’t snoop in messages. I don’t read DMs.\n"
            "I *do* translate symbols into decisions — clean, sharp, and a little enchanted.\n\n"
            "Use me for:\n"
            "• **Daily clarity** when your mind is loud\n"
            "• **Decision support** (not destiny) when choices stack up\n"
            "• **Relationship & work lenses** when you need a different angle\n"
            "• **Deep dives** when you’re ready to face the real story\n\n"
            "**Fast start:** try `/insight` (it shows everything you can do)."
        ),
        color=0xB28DFF,
    )
    intro.set_footer(text="✨ Ephemeral by default — most readings are private to the requester.")

    # --- 2) Practical “how to use” guide (short + punchy) ---
    howto = discord.Embed(
        title="🕯️ How to work with the deck",
        description=(
            "**Suggested rituals (no robes required):**\n"
            "• Set a focus with `/intent` (example: “my next career move”)\n"
            "• Choose your voice with `/mode` (quick, poetic, direct, shadow, love, work, money)\n"
            "• Pull a spread:\n"
            "  – `/cardoftheday` for a single thread\n"
            "  – `/read` for Situation • Obstacle • Guidance\n"
            "  – `/threecard` for Past • Present • Future\n"
            "  – `/celtic` when you want the *whole map*\n\n"
            "**Mystery mode:** `/mystery` shows the card image only… then `/reveal` when you’re ready."
        ),
        color=0x9370DB,
    )

    # --- 3) Auto-generated command index ---
    cmds = [c for c in bot.tree.get_commands() if isinstance(c, app_commands.Command)]
    cmds = sorted(cmds, key=lambda c: c.name)

    lines: List[str] = []
    for c in cmds:
        desc = (c.description or "").strip()
        if desc:
            lines.append(f"• `/{c.name}` — {desc}")
        else:
            lines.append(f"• `/{c.name}`")

    chunks = _chunk_lines(lines, max_len=950)

    index = discord.Embed(
        title="📜 Command Index",
        description="Every door I can open, listed plainly:",
        color=0x6A5ACD,
    )
    index.add_field(name="Commands", value=chunks[0] if chunks else "—", inline=False)
    for i, part in enumerate(chunks[1:], start=2):
        index.add_field(name=f"Commands (cont. {i})", value=part, inline=False)

    # --- 4) Privacy + control (short, confident) ---
    privacy = discord.Embed(
        title="🔒 Privacy & Control",
        description=(
            "You hold the keys.\n\n"
            "• `/privacy` — what I store (minimal, optional)\n"
            "• `/settings` — toggle **images** and **history opt-in**\n"
            "• `/forgetme` — delete your stored data\n\n"
            "Default behavior is cautious: history is **off** unless a user opts in."
        ),
        color=0x2E8B57,
    )

    return [intro, howto, index, privacy]


async def find_bot_inviter(guild: discord.Guild, bot_user: discord.ClientUser) -> Optional[discord.User]:
    """
    Attempts to find who added the bot by checking the guild audit log.
    Requires 'View Audit Log' permission.
    """
    try:
        async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.bot_add):
            target = getattr(entry, "target", None)
            if target and target.id == bot_user.id:
                return entry.user
    except (discord.Forbidden, discord.HTTPException):
        return None
    return None


async def send_onboarding_message(guild: discord.Guild):
    embeds = build_onboarding_embeds(guild)

    # 1) Prefer inviter (audit log), else owner
    recipient = await find_bot_inviter(guild, bot.user)
    if recipient is None:
        recipient = guild.owner

    # Try DM recipient
    if recipient:
        try:
            await recipient.send(embeds=embeds)
            return
        except (discord.Forbidden, discord.HTTPException):
            pass

    # Fallback: post in system channel / first available text channel
    me = guild.me
    channel = guild.system_channel
    if channel and me and channel.permissions_for(me).send_messages:
        try:
            await channel.send(embeds=embeds)
            return
        except discord.HTTPException:
            pass

    for ch in guild.text_channels:
        if me and ch.permissions_for(me).send_messages:
            try:
                await ch.send(embeds=embeds)
                return
            except discord.HTTPException:
                continue


@bot.event
async def on_guild_join(guild: discord.Guild):
    try:
        await send_onboarding_message(guild)
        print(f"✅ Onboarding sent for guild: {guild.name} ({guild.id})")
    except Exception as e:
        print(f"⚠️ Onboarding failed for guild {guild.id}: {type(e).__name__}: {e}")


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
# EPHEMERAL SENDER (in-character, no thinking lines)
# ==============================
def _prepend_in_character(embed: discord.Embed, mood: str) -> discord.Embed:
    line = random.choice(in_character_lines.get(mood, in_character_lines["general"]))
    if embed.description:
        embed.description = f"*{line}*\n\n{embed.description}"
    else:
        embed.description = f"*{line}*"
    return embed

async def send_ephemeral(
    interaction: discord.Interaction,
    *,
    embed: Optional[discord.Embed] = None,
    embeds: Optional[List[discord.Embed]] = None,
    content: Optional[str] = None,
    mood: str = "general",
    file_obj: Optional[discord.File] = None,
):
    # Choose response channel (first response vs followup)
    send_fn = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message

    # Build payload WITHOUT file unless it's real
    payload: Dict[str, Any] = {"ephemeral": True}

    if content is not None:
        payload["content"] = content

    if embed is not None:
        payload["embed"] = _prepend_in_character(embed, mood)
    elif embeds:
        embeds = list(embeds)
        embeds[0] = _prepend_in_character(embeds[0], mood)
        payload["embeds"] = embeds
    elif content is None:
        payload["content"] = "—"

    if file_obj is not None:
        payload["file"] = file_obj

    try:
        await send_fn(**payload)
        return

    except HTTPException as e:
        # 40060 = already acknowledged (use followup)
        if getattr(e, "code", None) == 40060:
            try:
                payload.pop("ephemeral", None)  # followup still supports ephemeral, but keep clean
                payload["ephemeral"] = True
                await interaction.followup.send(**payload)
                return
            except Exception as e2:
                print(f"⚠️ followup.send failed after 40060: {type(e2).__name__}: {e2}")
                return

        raise

    except NotFound as e:
        # 10062 = unknown interaction (usually responded too late)
        if getattr(e, "code", None) == 10062:
            print("⚠️ Interaction expired (10062). Could not respond.")
            return
        raise
# ==============================
# EVENTS
# ==============================
@bot.event
async def on_ready():
    global _DB_READY
    if not _DB_READY:
        try:
            ensure_tables()
            _DB_READY = True
            print("✅ DB ready.")
        except Exception as e:
            print(f"❌ DB init failed: {type(e).__name__}: {e}")
            return

    try:
        await bot.tree.sync()
        print("✅ Slash commands synced.")
    except Exception as e:
        print(f"⚠️ Slash sync failed: {type(e).__name__}: {e}")

    print(f"{E['crystal']} Arcanara is awake and shimmering as {bot.user}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Always log the real underlying exception + traceback
    orig = getattr(error, "original", error)
    print(f"⚠️ Slash command error: {type(error).__name__}: {error}")
    print(f"⚠️ Original: {type(orig).__name__}: {orig}")
    traceback.print_exception(type(orig), orig, orig.__traceback__)

    # Try to tell the user (but don't crash if interaction expired/ack'd)
    try:
        await send_ephemeral(
            interaction,
            content="⚠️ A thread snagged in the weave. Try again in a moment.",
            mood="general",
        )
    except Exception as e:
        print(f"⚠️ Failed to send error message: {type(e).__name__}: {e}")


# ==============================
# SLASH COMMANDS (EPHEMERAL)
# ==============================

@bot.tree.command(name="shuffle", description="Cleanse and reset the deck’s energy.")
@app_commands.checks.cooldown(3, 60.0)  # 3 per minute
async def shuffle_slash(interaction: discord.Interaction):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    random.shuffle(tarot_cards)
    embed = discord.Embed(
        title=f"{E['shuffle']} The Deck Has Been Cleansed {E['shuffle']}",
        description="Energy reset complete. The cards are ready to speak again.",
        color=0x9370DB
    )
    await send_ephemeral(interaction, embed=embed, mood="shuffle")

@bot.tree.command(name="cardoftheday", description="Reveal the card that guides your day.")
@app_commands.checks.cooldown(1, 60.0)  # 1 per minute
async def cardoftheday_slash(interaction: discord.Interaction):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    card, orientation = draw_card()
    mode = get_effective_mode(interaction.user.id)
    meaning = render_card_text(card, orientation, mode)

    settings = get_user_settings(interaction.user.id)

    is_reversed = (orientation == "Reversed")
    file_obj, attach_url = None, None

    if settings.get("images_enabled", True):
        file_obj, attach_url = make_image_attachment(card["name"], is_reversed)
        if not attach_url and file_obj is not None:
            attach_url = f"attachment://{file_obj.filename}"

    tone = E["sun"] if orientation == "Upright" else E["moon"]
    intent_text = user_intentions.get(interaction.user.id)

    desc = f"**{card['name']} ({orientation} {tone}) • {mode_label(mode)}**\n\n{meaning}"
    if intent_text:
        desc += f"\n\n{E['light']} **Focus:** *{intent_text}*"

    # ✅ STEP 5: log history (ONLY logs if user opted in)
    log_history_if_opted_in(
        interaction.user.id,
        command="cardoftheday",
        mode=mode,
        payload={
            "card": card["name"],
            "orientation": orientation,
            "focus": intent_text,
            "images_enabled": bool(settings.get("images_enabled", True)),
        },
        settings=settings,
    )

    embed = discord.Embed(
        title=f"{E['crystal']} Card of the Day",
        description=desc,
        color=suit_color(card["suit"])
    )

    if attach_url:
        embed.set_image(url=attach_url)

    await send_ephemeral(interaction, embed=embed, mood="daily", file_obj=file_obj)


@bot.tree.command(name="read", description="Three-card reading: Situation • Obstacle • Guidance.")
@app_commands.checks.cooldown(3, 60.0)  # 3 per minute
@app_commands.describe(focus="Your question or focus (example: my career path)")
async def read_slash(interaction: discord.Interaction, focus: str):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    user_intentions[interaction.user.id] = focus
    mode = get_effective_mode(interaction.user.id)

    cards = draw_unique_cards(3)
    positions = ["Situation", "Obstacle", "Guidance"]

    # ---- history (opt-in) ----
    log_history_if_opted_in(
        interaction.user.id,
        command="read",
        mode=mode,
        payload={
            "focus": focus,
            "spread": "situation_obstacle_guidance",
            "cards": [
                {"position": pos, "name": card["name"], "orientation": orientation}
                for pos, (card, orientation) in zip(positions, cards)
            ],
        },
    )

    embed = discord.Embed(
        title=f"{E['crystal']} Intuitive Reading {E['crystal']}",
        description=f"{E['light']} **Focus:** *{focus}*\n\n**How I’ll read this:** {mode_label(mode)}",
        color=0x9370DB
    )

    pretty_positions = [f"Situation {E['sun']}", f"Obstacle {E['sword']}", f"Guidance {E['star']}"]
    for pos, (card, orientation) in zip(pretty_positions, cards):
        meaning = render_card_text(card, orientation, mode)
        embed.add_field(
            name=f"{pos}: {card['name']} ({orientation})",
            value=meaning if len(meaning) < 1000 else meaning[:997] + "...",
            inline=False
        )

    embed.set_footer(text=f"{E['spark']} Let these cards guide your awareness, not dictate your choices.")
    await send_ephemeral(interaction, embed=embed, mood="spread")


@bot.tree.command(name="threecard", description="Past • Present • Future spread.")
@app_commands.checks.cooldown(3, 60.0)  # 3 per minute
async def threecard_slash(interaction: discord.Interaction):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    positions = ["Past", "Present", "Future"]
    cards = draw_unique_cards(3)

    mode = get_effective_mode(interaction.user.id)
    intent_text = user_intentions.get(interaction.user.id)

    # ---- history (opt-in) ----
    log_history_if_opted_in(
        interaction.user.id,
        command="threecard",
        mode=mode,
        payload={
            "focus": intent_text,
            "spread": "past_present_future",
            "cards": [
                {"position": pos, "name": card["name"], "orientation": orientation}
                for pos, (card, orientation) in zip(positions, cards)
            ],
        },
    )

    desc = "Past • Present • Future"
    if intent_text:
        desc += f"\n\n{E['light']} **Focus:** *{intent_text}*"
    desc += f"\n\n**How I’ll read this:** {mode_label(mode)}"

    embed = discord.Embed(
        title=f"{E['crystal']} Three-Card Spread",
        description=desc,
        color=0xA020F0
    )

    pretty_positions = [f"Past {E['clock']}", f"Present {E['moon']}", f"Future {E['star']}"]
    for pos, (card, orientation) in zip(pretty_positions, cards):
        meaning = render_card_text(card, orientation, mode)
        embed.add_field(
            name=f"{pos}: {card['name']} ({orientation})",
            value=meaning if len(meaning) < 1000 else meaning[:997] + "...",
            inline=False
        )

    await send_ephemeral(interaction, embed=embed, mood="spread")


@bot.tree.command(name="celtic", description="Full 10-card Celtic Cross spread.")
@app_commands.checks.cooldown(1, 120.0)  # 1 use per 120s per user
async def celtic_slash(interaction: discord.Interaction):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    positions = [
        "Present Situation", "Challenge", "Root Cause", "Past",
        "Conscious Goal", "Near Future", "Self", "External Influence",
        "Hopes & Fears", "Outcome"
    ]
    cards = draw_unique_cards(10)
    mode = get_effective_mode(interaction.user.id)

    # ---- history (opt-in) ----
    log_history_if_opted_in(
        interaction.user.id,
        command="celtic",
        mode=mode,
        payload={
            "spread": "celtic_cross",
            "cards": [
                {"position": pos, "name": card["name"], "orientation": orientation}
                for pos, (card, orientation) in zip(positions, cards)
            ],
        },
    )

    embeds_to_send: List[discord.Embed] = []
    embed = discord.Embed(
        title=f"{E['crystal']} Celtic Cross Spread {E['crystal']}",
        description=f"A deep, archetypal exploration of your path.\n\n**How I’ll read this:** {mode_label(mode)}",
        color=0xA020F0
    )

    total_length = len(embed.title) + len(embed.description)

    pretty_positions = [
        "1️⃣ Present Situation", "2️⃣ Challenge", "3️⃣ Root Cause", "4️⃣ Past",
        "5️⃣ Conscious Goal", "6️⃣ Near Future", "7️⃣ Self", "8️⃣ External Influence",
        "9️⃣ Hopes & Fears", "🔟 Outcome"
    ]

    for pos, (card, orientation) in zip(pretty_positions, cards):
        meaning = render_card_text(card, orientation, mode)
        field_name = f"{pos}: {card['name']} ({orientation})"
        field_value = meaning if len(meaning) < 1000 else meaning[:997] + "..."
        field_length = len(field_name) + len(field_value)

        if total_length + field_length > 5800:
            embeds_to_send.append(embed)
            embed = discord.Embed(
                title=f"{E['crystal']} Celtic Cross (Continued)",
                description=f"**How I’ll read this:** {mode_label(mode)}",
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
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    norm_query = normalize_card_name(card)

    matches = [
        c for c in tarot_cards
        if normalize_card_name(c.get("name", "")) == norm_query
        or norm_query in normalize_card_name(c.get("name", ""))
    ]

    if not matches:
        await send_ephemeral(
            interaction,
            content=f"{E['warn']} I searched the deck but found no card named **{card}**.",
            mood="general"
        )
        return

    chosen = matches[0]
    mode = get_effective_mode(interaction.user.id)
    settings = get_user_settings(interaction.user.id)

    # Safe suit handling (prevents KeyError)
    suit = chosen.get("suit") or "Major Arcana"
    color = suit_color(suit)

    # History (opt-in)
    log_history_if_opted_in(
        interaction.user.id,
        command="meaning",
        mode=mode,
        payload={"query": card, "matched": chosen.get("name", ""), "shown": ["Upright", "Reversed"]},
        settings=settings,
    )

    file_obj, attach_url = None, None
    if settings.get("images_enabled", True):
        try:
            file_obj, attach_url = make_image_attachment(chosen.get("name", ""), is_reversed=False)
            if not attach_url and file_obj is not None:
                attach_url = f"attachment://{file_obj.filename}"
        except Exception as e:
            print(f"⚠️ make_image_attachment failed: {type(e).__name__}: {e}")
            file_obj, attach_url = None, None

    embed_top = discord.Embed(
        title=f"{E['book']} {chosen.get('name','(unknown)')} • {mode_label(mode)}",
        description="",
        color=color
    )
    if attach_url:
        embed_top.set_image(url=attach_url)

    upright_text = clip_field(render_card_text(chosen, "Upright", mode), 1024)
    reversed_text = clip_field(render_card_text(chosen, "Reversed", mode), 1024)

    embed_body = discord.Embed(
        description=f"**{chosen.get('name','(unknown)')}** reveals both sides of its nature:",
        color=color
    )
    embed_body.add_field(name=f"Upright {E['sun']} • {mode}", value=upright_text or "—", inline=False)
    embed_body.add_field(name=f"Reversed {E['moon']} • {mode}", value=reversed_text or "—", inline=False)
    embed_body.set_footer(text=f"{E['light']} Interpreting symbols through Arcanara • Tarot Bot")

    await send_ephemeral(interaction, embeds=[embed_top, embed_body], mood="general", file_obj=file_obj)

@bot.tree.command(name="clarify", description="Draw a clarifier card for your current focus.")
async def clarify_slash(interaction: discord.Interaction):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    card, orientation = draw_card()
    tone = E["sun"] if orientation == "Upright" else E["moon"]
    intent_text = user_intentions.get(interaction.user.id)

    mode = get_effective_mode(interaction.user.id)
    meaning = render_card_text(card, orientation, mode)

    # ---- history (opt-in) ----
    log_history_if_opted_in(
        interaction.user.id,
        command="clarify",
        mode=mode,
        payload={
            "focus": intent_text,
            "card": {"name": card["name"], "orientation": orientation},
        },
    )

    desc = f"**{card['name']} ({orientation} {tone}) • {mode_label(mode)}**\n\n{meaning}"

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
    await interaction.response.send_message(
    f"✅ Reset. We’re back to **{mode_label(DEFAULT_MODE)}**.",
    ephemeral=True
)

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

    settings = get_user_settings(interaction.user.id)

    embed_top = discord.Embed(
        title=f"{E['crystal']} {card['name']}" + (" — Reversed" if is_reversed else ""),
        description="Type **/reveal** to see the meaning.",
        color=suit_color(card["suit"])
    )

    file_obj, attach_url = None, None
    if settings.get("images_enabled", True):
        file_obj, attach_url = make_image_attachment(card["name"], is_reversed)
        if not attach_url and file_obj is not None:
            attach_url = f"attachment://{file_obj.filename}"
        if attach_url:
            embed_top.set_image(url=attach_url)
    else:
        # Optional: make it clear why there's no image
        embed_top.description = (
            "Images are currently **off**.\n"
            "Turn them on with `/settings images:on`, or type **/reveal** to see the meaning."
        )

    await send_ephemeral(interaction, embed=embed_top, mood="general", file_obj=file_obj)

@bot.tree.command(name="reveal", description="Reveal the meaning of your last mystery card.")
async def reveal_slash(interaction: discord.Interaction):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    state = MYSTERY_STATE.get(interaction.user.id)
    if not state:
        await interaction.response.send_message(
            f"{E['warn']} No mystery card on file. Use **/mystery** first.",
            ephemeral=True
        )
        return

    try:
        name = state["name"]
        is_reversed = state["is_reversed"]

        card = next((c for c in tarot_cards if c["name"] == name), None)
        if not card:
            await interaction.response.send_message(
                f"{E['warn']} I lost track of that card. Try **/mystery** again.",
                ephemeral=True
            )
            return

        mode = get_effective_mode(interaction.user.id)
        orientation = "Reversed" if is_reversed else "Upright"
        meaning = render_card_text(card, orientation, mode)

        # ---- history (opt-in) ----
        settings = get_user_settings(interaction.user.id)
        
        log_history_if_opted_in(
            interaction.user.id,
            command="reveal",
            mode=mode,
            payload={
                "source": "mystery",
                "card": {"name": card["name"], "orientation": orientation},
            },
            settings=settings
        )

        embed = discord.Embed(
            title=f"{E['book']} Reveal: {card['name']} ({orientation}) • {mode_label(mode)}",
            description=meaning,
            color=suit_color(card["suit"])
        )
        embed.set_footer(text=f"{E['light']} Interpreting symbols through Arcanara • Tarot Bot")

        await send_ephemeral(interaction, embed=embed, mood="general")

    finally:
        # Always clear, even if an exception happens mid-way
        MYSTERY_STATE.pop(interaction.user.id, None)

@bot.tree.command(name="insight", description="A guided intro to Arcanara (and a full list of commands).")
async def insight_slash(interaction: discord.Interaction):
    # Defer so we never lose the interaction if Discord is slow
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    user_id_str = str(interaction.user.id)
    user_name = interaction.user.display_name

    first_time = user_id_str not in known_seekers
    if first_time:
        known_seekers[user_id_str] = {"name": user_name}
        save_known_seekers(known_seekers)

    current_mode = get_effective_mode(interaction.user.id)
    current_intent = user_intentions.get(interaction.user.id, None)

    # --- A more human, reader-style voice ---
    greetings_first = [
        f"Come closer, {user_name} — let’s see what wants to be known.",
        f"{user_name}… I felt you arrive before you spoke.",
        f"Alright, {user_name}. No theatrics — just clarity.",
        f"Welcome, {user_name}. The deck likes honest questions.",
    ]
    greetings_returning = [
        f"Back again, {user_name}? Good. The story didn’t end without you.",
        f"There you are, {user_name}. Same you — new chapter.",
        f"Welcome back, {user_name}. Let’s pick up the thread.",
        f"{user_name}… the deck remembers your rhythm.",
    ]

    opener = random.choice(greetings_first if first_time else greetings_returning)

    # Gentle, confident guidance paths
    intent_line = f"**Your focus:** *{current_intent}*" if current_intent else "**Your focus:** *unspoken… for now.*"
    mode_line = f"**How I’ll speak:** {mode_label(current_mode)}"

    guided = (
        f"{intent_line}\n"
        f"{mode_line}\n\n"
        "Here’s how we do this:\n"
        f"• Want a single clean message for today? Try **/cardoftheday**.\n"
        f"• Got a situation with teeth? Use **/read** and give me your focus.\n"
        f"• Want the timeline vibe? **/threecard** (past • present • future).\n"
        f"• Need the *deep* dive? **/celtic** — it pulls the whole pattern.\n"
        f"• Not sure what a card means in *your* mode? Ask **/meaning**.\n"
        f"• Feeling uncertain? **/clarify** will pull one more lantern from the dark.\n\n"
        "And if you’re in the mood for a little mischief:\n"
        f"• **/mystery** (image only) … then **/reveal** when you’re ready."
    )

    # --- Build all slash commands dynamically ---
    cmds = [c for c in bot.tree.get_commands() if isinstance(c, app_commands.Command)]
    cmds = sorted(cmds, key=lambda c: c.name)

    # Reader-style phrasing for commands list
    lines = []
    for c in cmds:
        desc = (c.description or "").strip()
        if desc:
            lines.append(f"• `/{c.name}` — {desc}")
        else:
            lines.append(f"• `/{c.name}`")

    # Chunk to respect embed field limits
    chunks: List[str] = []
    buf: List[str] = []
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

    embed = discord.Embed(
        title=f"{E['crystal']} Arcanara",
        description=f"*{opener}*\n\n{guided}",
        color=0xB28DFF
    )

    embed.add_field(
        name="What I can do for you",
        value=chunks[0] if chunks else "—",
        inline=False
    )
    for i, part in enumerate(chunks[1:], start=2):
        embed.add_field(name=f"What I can do for you (cont. {i})", value=part, inline=False)

    embed.set_footer(text="A tarot reading is a mirror, not a cage. You steer.")
    await send_ephemeral(interaction, embed=embed, mood="general")


@bot.tree.command(name="privacy", description="What Arcanara stores and how to delete it.")
async def privacy_slash(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔒 Arcanara Privacy",
        description=(
            "**Stored data (optional / minimal):**\n"
            "• Your chosen `/mode`\n"
            "• Your `/settings` (images on/off, history opt-in)\n"
            "• Reading history **only if you opt in**\n\n"
            "**Delete everything:** use `/forgetme`.\n"
            "Arcanara does not need message content intent and does not read your DMs."
        ),
        color=0x6A5ACD
    )
    await send_ephemeral(interaction, embed=embed, mood="general")

@bot.tree.command(name="forgetme", description="Delete your stored Arcanara data.")
async def forgetme_slash(interaction: discord.Interaction):
    uid = interaction.user.id

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tarot_user_prefs WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM tarot_user_settings WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM tarot_reading_history WHERE user_id=%s", (uid,))
        conn.commit()

    user_intentions.pop(uid, None)
    MYSTERY_STATE.pop(uid, None)

    await send_ephemeral(interaction, content="✅ Your thread has been cut clean. Stored data deleted.", mood="general")
    
@bot.tree.command(name="settings", description="Control history + images for your readings.")
@app_commands.choices(
    history=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")],
    images=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")],
)
async def settings_slash(
    interaction: discord.Interaction,
    history: Optional[app_commands.Choice[str]] = None,
    images: Optional[app_commands.Choice[str]] = None,
):
    h = None if history is None else (history.value == "on")
    i = None if images is None else (images.value == "on")
    set_user_settings(interaction.user.id, history_opt_in=h, images_enabled=i)

    s = get_user_settings(interaction.user.id)
    await send_ephemeral(
        interaction,
        content=f"✅ Settings saved.\n• History: **{'on' if s['history_opt_in'] else 'off'}**\n• Images: **{'on' if s['images_enabled'] else 'off'}**",
        mood="general",
    )

# ==============================
# RUN BOT
# ==============================
bot.run(BOT_TOKEN)
