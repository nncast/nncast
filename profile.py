"""Draw card.svg: a tmux-style terminal session with live GitHub stats.

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

C = {"bg": "#15131f", "bar": "#211e30", "edge": "#3a3550", "user": "#ff7eb6",
     "path": "#78dce8", "cmd": "#f4f1ff", "key": "#a9a1d1", "out": "#d6d2ea",
     "dim": "#6c6688", "xp": "#a6e22e", "track": "#2c2840", "status": "#ff7eb6"}

PROMPT = [("janelle", "user"), ("@", "dim"), (USER, "user"), (":", "dim"), ("~", "path"), ("$ ", "dim")]
WHOAMI = "Janelle Ann Castillo, designer & developer"
ABOUT = [
    ("role", "Designer & Developer"),
    ("home", "Santiago City, Isabela"),
    ("school", "University of La Salette"),
    ("jobs", "Game Artist, Digital Artist"),
    ("tools", "Aseprite, Flutter, Laravel, Python"),
]

W, H = 840, 470
SPLIT = 560  # x of the tmux pane divider
LH = 18  # line height


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
            langs[name] = (size + e["size"], e["node"]["color"] or C["key"])
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


def line(x, y, segs, anchor="start", cls=""):
    """One text line from (text, colour key) segments."""
    c = f' class="{cls}"' if cls else ""
    spans = "".join(f'<tspan fill="{C[k]}">{html.escape(t)}</tspan>' for t, k in segs)
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}" xml:space="preserve"{c}>{spans}</text>'


def bar(x, y, w, frac, color):
    return (f'<rect x="{x}" y="{y - 9}" width="{w}" height="9" fill="{C["track"]}"/>'
            f'<rect x="{x}" y="{y - 9}" width="{round(w * frac)}" height="9" fill="{color}"/>')


def render(s, sprite, today):
    lv, frac, need = level(s["xp"])
    png, fw, fh, n, ms = sprite
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        'font-family="ui-monospace, SFMono-Regular, Consolas, Menlo, monospace" font-size="14">',
        "<style>.blink{animation:a 1s steps(1) infinite}@keyframes a{50%{opacity:0}}"
        f"@keyframes cat{{to{{transform:translateX(-{fw * n}px)}}}}</style>",
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="10" fill="{C["bg"]}" stroke="{C["edge"]}"/>',
        # title bar
        f'<path d="M1 30V11a10 10 0 0 1 10-10h{W - 22}a10 10 0 0 1 10 10v19z" fill="{C["bar"]}"/>',
        *(f'<circle cx="{20 + i * 20}" cy="15.5" r="6" fill="{c}"/>' for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840"))),
        line(W // 2, 20, [(f"janelle@{USER}: ~ (tmux)", "dim")], "middle"),
        # pane divider and status bar
        f'<line x1="{SPLIT}" y1="30" x2="{SPLIT}" y2="{H - 26}" stroke="{C["edge"]}"/>',
        f'<path d="M1 {H - 26}h{W - 2}v15a10 10 0 0 1-10 10H11a10 10 0 0 1-10-10z" fill="{C["bar"]}"/>',
        line(14, H - 9, [(f"[{USER}] ", "status"), ("0:zsh* ", "cmd"), ("1:cat", "dim")]),
        line(W - 14, H - 9, [(f"updated {today}", "dim")], "end"),
    ]

    # left pane: a short shell session
    x, y = 20, 56
    k2 = x + 72  # value column

    def cmd(c):
        nonlocal y
        out.append(line(x, y, PROMPT + [(c, "cmd")]))
        y += LH

    cmd("whoami")
    out.append(line(x, y, [(WHOAMI, "out")]))
    y += LH * 2

    cmd("cat about.txt")
    for k, v in ABOUT:
        out.append(line(x, y, [(k, "key")]))
        out.append(line(k2, y, [(v, "out")]))
        y += LH
    y += LH

    cmd("gh langs --top 5")
    top = s["langs"][:5]
    total = sum(size for _, (size, _) in s["langs"]) or 1
    for name, (size, color) in top:
        pct = size / total
        out.append(line(x, y, [(name, "out")]))
        out.append(bar(x + 170, y, 280, pct / (top[0][1][0] / total), color))
        out.append(line(SPLIT - 20, y, [(f"{pct:.0%}", "dim")], "end"))
        y += LH
    y += LH

    cmd("gh xp")
    out.append(line(x, y, [(f"lv {lv}", "xp")]))
    out.append(bar(x + 60, y, 160, frac, C["xp"]))
    out.append(line(x + 236, y, [(f"{s['xp']:,} xp", "out"), (f"  {need:,} to lv {lv + 1}", "dim")]))
    y += LH * 2

    out.append(line(x, y, PROMPT))
    cx = x + 8.4 * sum(len(t) for t, _ in PROMPT)  # ponytail: assumes ~0.6em glyphs; off by a char in odd fonts
    out.append(f'<rect class="blink" x="{cx}" y="{y - 12}" width="8" height="15" fill="{C["cmd"]}"/>')

    # right pane: `cat cat.gif` "prints" the cat
    out.append(line(SPLIT + 16, 56, PROMPT[-1:] + [("cat cat.gif", "cmd")]))
    pw, ph = W - SPLIT - 32, 340
    scale = min(pw // fw, ph // fh)
    sw, sh = fw * scale, fh * scale
    sx, sy = SPLIT + (W - SPLIT - sw) // 2, 76 + (ph - sh) // 2
    # one strip of frames, slid left a frame at a time inside a clipped viewport
    out.append(
        f'<svg x="{sx}" y="{sy}" width="{sw}" height="{sh}" viewBox="0 0 {fw} {fh}">'
        f'<image width="{fw * n}" height="{fh}" image-rendering="pixelated" '
        f'style="image-rendering:pixelated;animation:cat {n * ms}ms steps({n}) infinite" '
        f'href="data:image/png;base64,{png}"/></svg>'
    )
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
    print("xp:", stats["xp"], [n for n, _ in stats["langs"][:5]])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    svg = render(stats, sprite_sheet(os.path.join(here, "sprite.gif")), today)
    with open(os.path.join(here, "card.svg"), "w", encoding="utf-8") as f:
        f.write(svg)
    print("wrote card.svg")
