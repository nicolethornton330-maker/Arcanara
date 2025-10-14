#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download Rider–Waite 'Pictorial Key' images from Sacred Texts (stdlib only).
Fixes: reads <img src=...> on each card page, normalizes titles.

Output:
  assets/cards/rws_stx/ (images + manifest.json + report.csv)
"""

import os, re, csv, json, time, unicodedata
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen, Request

INDEX_URL     = "https://www.sacred-texts.com/tarot/xr/index.htm"
RWS_IMG_ROOT  = "/tarot/pkt/"          # accept anything under /tarot/pkt/ (color plates)
OUT_DIR       = os.path.join("assets", "cards", "rws_stx")
USER_AGENT    = "ArcanaraTarotFetcher/2.0 (+personal use)"
PAUSE         = 0.12
IMG_EXTS      = (".jpg",".jpeg",".png",".webp")

MAJORS = [
    "The Fool","The Magician","The High Priestess","The Empress","The Emperor","The Hierophant",
    "The Lovers","The Chariot","Strength","The Hermit","Wheel of Fortune","Justice","The Hanged Man",
    "Death","Temperance","The Devil","The Tower","The Star","The Moon","The Sun","Judgement","The World",
]
RANKS_NUM   = ["Ace","Two","Three","Four","Five","Six","Seven","Eight","Nine","Ten"]
RANKS_COURT = ["Page","Knight","Queen","King"]
SUITS = ["Cups","Pentacles","Swords","Wands"]

EXPECTED = set(MAJORS +
               [f"{r} of {s}" for s in SUITS for r in RANKS_NUM] +
               [f"{r} of {s}" for s in SUITS for r in RANKS_COURT])

def norm_ws(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", " ", s.strip())

def slug(s: str) -> str:
    s = s.lower().replace("—","-").replace("’","").replace("'","")
    s = re.sub(r"[^a-z0-9]+","_", s)
    return re.sub(r"_+","_", s).strip("_")

def http_get_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="ignore")

def http_get_bytes(url: str) -> bytes | None:
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=120) as r:
            return r.read()
    except Exception:
        return None

class AAndIMGCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.a = []      # (href, text)
        self.img = []    # (src, alt)
        self._in_a = False
        self._cur_href = None
        self._cur_text = []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag.lower() == "a":
            self._in_a = True
            self._cur_href = d.get("href")
            self._cur_text = []
        elif tag.lower() == "img":
            src = d.get("src")
            alt = d.get("alt") or ""
            if src:
                self.img.append((src, alt))
    def handle_data(self, data):
        if self._in_a:
            self._cur_text.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._in_a:
            text = norm_ws("".join(self._cur_text))
            self.a.append((self._cur_href, text))
            self._in_a = False
            self._cur_href = None
            self._cur_text = []

def parse_assets(html: str):
    p = AAndIMGCollector()
    p.feed(html)
    return p.a, p.img

def canonical_card_name(s: str) -> str | None:
    """Normalize titles from index (removes Next/Previous, numbering, fixes Judgment spelling, maps 'The Wheel...'→'Wheel...' etc.)."""
    if not s:
        return None
    t = norm_ws(s)
    # strip "Next:" / "Previous:" boilerplate that sometimes appears on link text
    t = re.sub(r"^(?:«\s*)?(?:next|previous):\s*tarot card cross-reference--", "", t, flags=re.I)
    t = t.replace("Â»","").strip("«» ").strip()
    # drop leading "NN. "
    t = re.sub(r"^\d+\.\s*", "", t)
    # Judgment spelling
    t = t.replace("Judgment", "Judgement")
    # 'The Wheel of Fortune' → 'Wheel of Fortune' (canonical in our list)
    if t.lower().startswith("the wheel of fortune"):
        t = "Wheel of Fortune"
    return t

def get_card_pages_from_index() -> list[tuple[str,str]]:
    html = http_get_text(INDEX_URL)
    anchors, _imgs = parse_assets(html)
    cards = []
    for href, text in anchors:
        if not href or not text:
            continue
        # ignore table-of-contents and boilerplate
        if text.lower().startswith(("next:", "previous:")):
            continue
        name = canonical_card_name(text)
        if not name:
            continue
        # keep only likely card names
        if (" of " in name) or (name in MAJORS):
            cards.append((name, urljoin(INDEX_URL, href)))
    # de-dupe by name (last wins)
    seen = {}
    for name, url in cards:
        seen[name] = url
    return sorted(seen.items(), key=lambda kv: kv[0])

def find_rws_image_on_card_page(card_page_url: str) -> str | None:
    """Return absolute URL of the Pictorial Key card image found via <img src> (preferred) or <a href> fallback."""
    html = http_get_text(card_page_url)
    anchors, images = parse_assets(html)

    # 1) look at <img src>
    for src, alt in images:
        absu = urljoin(card_page_url, src)
        path = urlparse(absu).path
        if path.startswith(RWS_IMG_ROOT) and path.lower().endswith(IMG_EXTS):
            return absu

    # 2) fallback: look at <a href> that point directly to images
    for href, _txt in anchors:
        absu = urljoin(card_page_url, href or "")
        path = urlparse(absu).path
        if path.startswith(RWS_IMG_ROOT) and path.lower().endswith(IMG_EXTS):
            return absu

    return None

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    cards = get_card_pages_from_index()
    print(f"Found {len(cards)} card entries on index.")

    manifest = {}
    extras = []
    for i, (name_raw, page_url) in enumerate(cards, 1):
        name = canonical_card_name(name_raw) or name_raw
        print(f"[{i:02d}/{len(cards)}] {name}")

        img_url = find_rws_image_on_card_page(page_url)
        if not img_url:
            extras.append((name, page_url))
            time.sleep(PAUSE); continue

        ext = os.path.splitext(urlparse(img_url).path)[1].lower()
        if ext not in IMG_EXTS:
            ext = ".jpg"
        filename = slug(name) + ext
        dest = os.path.join(OUT_DIR, filename)

        data = http_get_bytes(img_url)
        if not data:
            extras.append((name + " (download failed) ", img_url))
            time.sleep(PAUSE); continue

        tmp = dest + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        if os.path.exists(dest):
            os.remove(dest)
        os.replace(tmp, dest)

        manifest[name] = filename
        time.sleep(PAUSE)

    got = set(manifest.keys())
    missing = sorted(list(EXPECTED - got))

    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    with open(os.path.join(OUT_DIR, "report.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["status","card_or_file","source"])
        for m in missing: w.writerow(["missing", m, ""])
        for (t,u) in extras: w.writerow(["no_rws_image_link_found", t, u])

    print("\nDone.")
    print(f"Cards saved: {len(manifest)}/78")
    print(f"Missing: {len(missing)} (see {OUT_DIR}\\report.csv)")
    print(f"Output: {OUT_DIR}")

if __name__ == "__main__":
    main()