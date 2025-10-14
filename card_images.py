# card_images.py
import os, re, json, io
import discord

# Optional rotate/resize for reversed & large images
try:
    from PIL import Image
    PIL_OK = True
except Exception:
    PIL_OK = False

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, "assets", "cards")
_ALLOWED_EXTS = (".png", ".jpg", ".jpeg", ".webp")

def card_slug(name: str) -> str:
    s = name.lower()
    s = s.replace("—","-").replace("’","").replace("'","")
    s = re.sub(r"[^a-z0-9]+","_", s)
    return re.sub(r"_+","_", s).strip("_")

def _load_manifest(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

TEST_MANIFEST    = _load_manifest(os.path.join(IMAGE_DIR, "test",    "manifest.json"))
RWS_STX_MANIFEST = _load_manifest(os.path.join(IMAGE_DIR, "rws_stx", "manifest.json"))
RWS_MANIFEST     = _load_manifest(os.path.join(IMAGE_DIR, "rws",     "manifest.json"))  # if you later add a different RWS set

def _resolve_in_folder(folder: str, name_or_base: str) -> str | None:
    """Return a real path if it exists. Supports names with or without extension."""
    base, ext = os.path.splitext(name_or_base)
    # If user passed something with extension, try it directly
    if ext:
        p = os.path.join(IMAGE_DIR, folder, name_or_base)
        return p if os.path.exists(p) else None
    # Try each allowed extension
    for e in _ALLOWED_EXTS:
        p = os.path.join(IMAGE_DIR, folder, base + e)
        if os.path.exists(p):
            return p
    return None

def _manifest_lookup(manifest: dict, card_name: str, folder: str) -> str | None:
    for key in (card_name, card_name.title(), card_name.upper()):
        v = manifest.get(key)
        if v:
            p = _resolve_in_folder(folder, v)
            if p:
                return p
    return None

def local_card_path(card_name: str) -> str | None:
    """Find the best local image path for a given card (your test art > Sacred-Texts set > other)."""
    slug = card_slug(card_name)

    # 1) Your test images (highest priority)
    p = (
        _manifest_lookup(TEST_MANIFEST, card_name, "test")
        or _resolve_in_folder("test", f"{slug}")  # extension-flexible
    )
    if p: return p

    # 2) Sacred Texts RWS set
    p = (
        _manifest_lookup(RWS_STX_MANIFEST, card_name, "rws_stx")
        or _resolve_in_folder("rws_stx", f"{slug}")
    )
    if p: return p

    # 3) Any other RWS set you might add later
    p = (
        _manifest_lookup(RWS_MANIFEST, card_name, "rws")
        or _resolve_in_folder("rws", f"{slug}")
    )
    if p: return p

    # 4) Last-ditch: look directly in assets/cards/
    for e in _ALLOWED_EXTS:
        q = os.path.join(IMAGE_DIR, f"{slug}{e}")
        if os.path.exists(q):
            return q
    return None

def make_image_attachment(card_name: str, reversed_flag: bool = False, max_width: int = 900):
    """
    Returns (discord.File or None, 'attachment://...' or None).
    If Pillow is available, rotates for reversed and gently downsizes very large images.
    """
    path = local_card_path(card_name)
    if not path:
        return None, None

    # No PIL fallback: attach as-is
    if not PIL_OK:
        fn = os.path.basename(path)
        return discord.File(path, filename=fn), f"attachment://{fn}"

    # PIL flow: open → optional rotate → optional downscale → PNG buffer
    with Image.open(path) as im:
        im = im.convert("RGBA")
        if reversed_flag:
            im = im.rotate(180, expand=True)

        if max_width and im.width > max_width:
            ratio = max_width / im.width
            im = im.resize((max_width, int(im.height * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        im.save(buf, format="PNG")  # embeds love PNG
        buf.seek(0)
        out_name = f"{card_slug(card_name)}{'_rev' if reversed_flag else ''}.png"
        return discord.File(buf, filename=out_name), f"attachment://{out_name}"