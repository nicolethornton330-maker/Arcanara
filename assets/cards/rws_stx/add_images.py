# card_images.py
import os, re, json, io, discord
try:
    from PIL import Image
    PIL_OK = True
except Exception:
    PIL_OK = False

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, "assets", "cards")
_EXTS = (".png",".jpg",".jpeg",".webp")

def card_slug(name: str) -> str:
    s = name.lower().replace("—","-").replace("’","").replace("'","")
    s = re.sub(r"[^a-z0-9]+","_", s)
    return re.sub(r"_+","_", s).strip("_")

def _resolve(folder: str, base: str) -> str | None:
    # base can be with or without extension
    p = os.path.join(IMAGE_DIR, folder, base)
    if os.path.exists(p): return p
    root, ext = os.path.splitext(base)
    if ext: return None
    for e in _EXTS:
        q = os.path.join(IMAGE_DIR, folder, root + e)
        if os.path.exists(q): return q
    return None

def local_card_path(card_name: str) -> str | None:
    slug = card_slug(card_name)
    # 1) user test overrides (if you ever add them)
    p = _resolve("test", slug)
    if p: return p
    # 2) sacred-texts set fetched at build
    p = _resolve("rws_stx", slug)
    if p: return p
    # 3) fallback: directly under assets/cards/
    for e in _EXTS:
        q = os.path.join(IMAGE_DIR, slug + e)
        if os.path.exists(q): return q
    return None

def make_image_attachment(card_name: str, reversed_flag: bool=False, max_width: int=900):
    path = local_card_path(card_name)
    if not path:
        return None, None
    if not PIL_OK:
        fn = os.path.basename(path)
        return discord.File(path, filename=fn), f"attachment://{fn}"
    with Image.open(path) as im:
        im = im.convert("RGBA")
        if reversed_flag:
            im = im.rotate(180, expand=True)
        if max_width and im.width > max_width:
            ratio = max_width / im.width
            im = im.resize((max_width, int(im.height * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        buf.seek(0)
        out_name = f"{card_slug(card_name)}{'_rev' if reversed_flag else ''}.png"
        return discord.File(buf, filename=out_name), f"attachment://{out_name}"
