"""Draw card.svg: an RPG status screen with live GitHub stats.

Runs daily via GitHub Actions. Needs Pillow (reads sprite.gif) and a
GITHUB_TOKEN env var. `python profile.py --demo` renders sample stats offline.
"""
import base64
import html
import io
import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timezone

from PIL import Image, ImageSequence

USER = "nncast"
SPRITE_PX = 64  # sprite.gif is pixelated to this many pixels wide
FRAME_STEP = 2  # keep every 2nd GIF frame; the card stays small
FONT = "KenneyMiniSquare"  # CC0, kenney.nl

C = {"bg": "#14122b", "panel": "#1d1a3d", "edge": "#3d3778", "gold": "#f2b632",
     "text": "#ecebff", "muted": "#8e89c4", "xp": "#5fd18b", "track": "#2b2754"}

PROFILE = [
    ("CLASS", "Designer & Developer"),
    ("HOME", "Santiago City, Isabela"),
    ("GUILD", "University of La Salette"),
    ("JOBS", "Game Artist · Digital Artist"),
    ("TOOLS", "Aseprite, Flutter, Laravel, Python"),
]
LINK = "nncast.github.io/janelle-portfolio"


def graphql(query):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"},
    )
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
    if resp.get("errors"):
        raise RuntimeError(resp["errors"])
    return resp["data"]["user"]


def fetch_stats():
    u = graphql(f"""query {{ user(login: "{USER}") {{
      createdAt
      repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false) {{
        nodes {{ languages(first: 10) {{ edges {{ size node {{ name color }} }} }} }}
      }}
    }} }}""")
    first = int(u["createdAt"][:4])
    years = "\n".join(
        f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y}-12-31T23:59:59Z")'
        " { contributionCalendar { totalContributions } }"
        for y in range(first, datetime.now(timezone.utc).year + 1)
    )
    c = graphql(f'query {{ user(login: "{USER}") {{ {years} }} }}')
    langs = {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            name = e["node"]["name"]
            size = langs.get(name, (0,))[0]
            langs[name] = (size + e["size"], e["node"]["color"] or C["muted"])
    return {
        "xp": sum(v["contributionCalendar"]["totalContributions"] for v in c.values()),
        "langs": sorted(langs.items(), key=lambda kv: -kv[1][0]),
    }


def level(xp):
    # level n starts at 10*n^2 XP, so each level takes a little longer
    n = math.isqrt(xp // 10)
    lo, hi = 10 * n * n, 10 * (n + 1) ** 2
    return n, (xp - lo) / (hi - lo), hi - xp


def sprite_sheet(path):
    """Pixelate a transparent GIF into one PNG strip; returns (base64, w, h, frames, ms per frame)."""
    gif = Image.open(path)
    frames = [f.convert("RGBA") for f in ImageSequence.Iterator(gif)][::FRAME_STEP]
    ms = gif.info.get("duration", 100) * FRAME_STEP
    box = frames[0].getbbox()
    for f in frames:  # crop to the area the animation ever touches
        b = f.getbbox() or box
        box = (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    w = SPRITE_PX
    h = round(w * (box[3] - box[1]) / (box[2] - box[0]))
    strip = Image.new("RGBA", (w * len(frames), h))
    for i, f in enumerate(frames):
        small = f.crop(box).resize((w, h), Image.BOX)
        a = small.getchannel("A").point(lambda v: 255 if v > 110 else 0)  # hard pixel edges
        small.putalpha(a)
        strip.paste(small, (i * w, 0))
    buf = io.BytesIO()
    strip.quantize(64, method=Image.Quantize.FASTOCTREE).save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode(), w, h, len(frames), ms


def text(x, y, s, fill, size=16, anchor="start", cls=""):
    c = f' class="{cls}"' if cls else ""
    return (f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" text-anchor="{anchor}"{c}>'
            f"{html.escape(s)}</text>")


def box(x, y, w, h, fill, edge):
    # pixel-style frame: notched corners instead of rounded ones
    s = 4
    return (f'<path d="M{x+s} {y}h{w-2*s}v{s}h{s}v{h-2*s}h{-s}v{s}h{-(w-2*s)}v{-s}h{-s}'
            f'v{-(h-2*s)}h{s}z" fill="{fill}" stroke="{edge}" stroke-width="2"/>')


def bar(x, y, w, frac, color, h=10):
    seg = 6
    n = w // seg
    on = round(frac * n)
    return "".join(
        f'<rect x="{x + i * seg}" y="{y}" width="{seg - 2}" height="{h}" fill="{color if i < on else C["track"]}"/>'
        for i in range(n)
    )


def render(s, sprite, font_b64):
    W, H = 840, 470
    lv, frac, need = level(s["xp"])
    png, fw, fh, n, ms = sprite
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="{FONT}, monospace" shape-rendering="crispEdges">',
        "<style>"
        f'@font-face{{font-family:"{FONT}";src:url(data:font/ttf;base64,{font_b64})}}'
        ".blink{animation:a 1.2s steps(1) infinite}@keyframes a{50%{opacity:0}}"
        f"@keyframes cat{{to{{transform:translateX(-{fw * n}px)}}}}"
        "</style>",
        f'<rect width="{W}" height="{H}" fill="{C["bg"]}"/>',
        box(4, 4, W - 8, H - 8, "none", C["edge"]),
    ]

    # left: the character
    out.append(box(24, 24, 240, 422, C["panel"], C["edge"]))
    out.append(text(144, 56, "PLAYER 1", C["gold"], 18, "middle"))
    scale = min(200 // fw, 200 // fh)
    sw, sh = fw * scale, fh * scale
    sx, sy = 144 - sw // 2, 70 + (200 - sh) // 2
    # one strip of frames, slid left a frame at a time inside a clipped viewport
    out.append(
        f'<svg x="{sx}" y="{sy}" width="{sw}" height="{sh}" viewBox="0 0 {fw} {fh}">'
        f'<image class="cat" width="{fw * n}" height="{fh}" image-rendering="pixelated" '
        f'style="image-rendering:pixelated;animation:cat {n * ms}ms steps({n}) infinite" '
        f'href="data:image/png;base64,{png}"/></svg>'
    )
    out.append(text(144, 310, "JANELLE", C["text"], 26, "middle"))
    out.append(text(144, 334, "@" + USER, C["muted"], 16, "middle"))
    out.append(text(44, 376, f"LV {lv}", C["gold"], 20))
    out.append(text(244, 376, f"{s['xp']:,} XP", C["text"], 16, "end"))
    out.append(bar(44, 388, 200, frac, C["xp"]))
    out.append(text(144, 424, f"{need:,} XP to LV {lv + 1}", C["muted"], 14, "middle"))

    # right: profile and skills
    x0, x1 = 288, 816
    out.append(text(x0, 52, "STATUS", C["gold"], 18))
    for i, (k, v) in enumerate(PROFILE):
        y = 80 + i * 24
        out.append(text(x0, y, k, C["muted"], 16))
        out.append(text(x0 + 92, y, v, C["text"], 16))

    out.append(text(x0, 222, "SKILLS", C["gold"], 18))
    top = s["langs"][:6]
    total = sum(size for _, (size, _) in s["langs"]) or 1
    for i, (name, (size, color)) in enumerate(top):
        y = 252 + i * 30
        pct = size / total
        out.append(text(x0, y, name, C["text"], 16))
        out.append(bar(x0 + 170, y - 10, 270, pct / (top[0][1][0] / total), color))
        out.append(text(x1, y, f"{pct:.0%}", C["muted"], 16, "end"))

    out.append(text(x1, 456, "> " + LINK, C["muted"], 13, "end", "blink"))
    out.append("</svg>")
    return "\n".join(out)


def selfcheck():
    assert level(0) == (0, 0.0, 10)
    assert level(10)[:2] == (1, 0.0)
    assert level(39) == (1, 29 / 30, 1)
    assert level(40)[0] == 2


DEMO = {"xp": 1234,
        "langs": [("HTML", (900, "#e34c26")), ("Dart", (600, "#00B4AB")),
                  ("PHP", (400, "#4F5D95")), ("Python", (300, "#3572A5"))]}

if __name__ == "__main__":
    selfcheck()
    here = os.path.dirname(os.path.abspath(__file__))
    stats = DEMO if "--demo" in sys.argv else fetch_stats()
    print("xp:", stats["xp"], [n for n, _ in stats["langs"][:6]])
    with open(os.path.join(here, f"{FONT}.ttf"), "rb") as f:
        font = base64.b64encode(f.read()).decode()
    svg = render(stats, sprite_sheet(os.path.join(here, "sprite.gif")), font)
    with open(os.path.join(here, "card.svg"), "w", encoding="utf-8") as f:
        f.write(svg)
    print("wrote card.svg")
