"""Draw card-dark.svg and card-light.svg: a tmux-style terminal with live GitHub stats.

Runs daily via GitHub Actions. Needs Pillow (reads sprite.gif) and a
GITHUB_TOKEN env var. `python profile.py --demo` renders sample stats offline.
"""
import base64
import html
import io
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

from PIL import Image, ImageSequence

USER = "nncast"
SPRITE_PX = 64  # sprite.gif is pixelated to this many pixels wide
FRAME_STEP = 2  # keep every 2nd GIF frame; the card stays small

# backgrounds are transparent, so these sit on GitHub's own page colour
PALETTES = {
    "dark": {"user": "#ff7eb6", "path": "#78dce8", "cmd": "#f0f6fc", "key": "#a9a1d1",
             "out": "#c9d1d9", "dim": "#6e7681", "edge": "#30363d", "track": "#21262d",
             "accent": "#a6e22e"},
    "light": {"user": "#c4256e", "path": "#0e7490", "cmd": "#1f2328", "key": "#6639ba",
              "out": "#31363c", "dim": "#6e7781", "edge": "#d0d7de", "track": "#eaeef2",
              "accent": "#1a7f37"},
}

PROMPT = [("janelle", "user"), ("@", "dim"), (USER, "user"), (":", "dim"), ("~", "path"), ("$ ", "dim")]
WHOAMI = "Janelle Ann Castillo, designer & developer"
ABOUT = [
    ("role", "Designer & Developer"),
    ("jobs", "Game Artist, Digital Artist"),
    ("tools", "Aseprite, Flutter, Laravel, Python"),
]

W, H = 840, 430
SPLIT = 560  # x of the tmux pane divider
TOP = 30  # title bar height
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
        " { totalCommitContributions restrictedContributionsCount }"
        for y in range(first, datetime.now(timezone.utc).year + 1)
    )
    c = graphql(f'query {{ user(login: "{USER}") {{ {years} }} }}')
    langs = {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            name = e["node"]["name"]
            size = langs.get(name, (0,))[0]
            langs[name] = (size + e["size"], e["node"]["color"] or "#8b949e")
    return {
        # restricted = private-repo activity, counted only if the profile shows it
        "commits": sum(v["totalCommitContributions"] + v["restrictedContributionsCount"] for v in c.values()),
        "since": first,
        "langs": sorted(langs.items(), key=lambda kv: -kv[1][0]),
    }


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


def render(s, sprite, today, C):
    png, fw, fh, n, ms = sprite

    def line(x, y, segs, anchor="start"):
        spans = "".join(f'<tspan fill="{C[k]}">{html.escape(t)}</tspan>' for t, k in segs)
        return f'<text x="{x}" y="{y}" text-anchor="{anchor}" xml:space="preserve">{spans}</text>'

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        'font-family="ui-monospace, SFMono-Regular, Consolas, Menlo, monospace" font-size="14">',
        "<style>.blink{animation:a 1s steps(1) infinite}@keyframes a{50%{opacity:0}}"
        f"@keyframes cat{{to{{transform:translateX(-{fw * n}px)}}}}</style>",
        # window outline, title bar with linux-style controls, pane divider, tmux status line
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="8" fill="none" stroke="{C["edge"]}"/>',
        line(W // 2, 19, [(f"janelle@{USER}: ~ (tmux)", "dim")], "middle"),
        f'<g stroke="{C["dim"]}" stroke-width="1.5" fill="none">'
        f'<path d="M{W - 82} 19h10"/><rect x="{W - 57}" y="10" width="9" height="9"/>'
        f'<path d="M{W - 32} 10l9 9m0-9l-9 9"/></g>',
        f'<line x1="0" y1="{TOP}" x2="{W}" y2="{TOP}" stroke="{C["edge"]}"/>',
        f'<line x1="{SPLIT}" y1="{TOP}" x2="{SPLIT}" y2="{H - 28}" stroke="{C["edge"]}"/>',
        f'<line x1="0" y1="{H - 28}" x2="{W}" y2="{H - 28}" stroke="{C["edge"]}"/>',
        line(16, H - 9, [(f"[{USER}] ", "user"), ("0:zsh* ", "cmd"), ("1:cat", "dim")]),
        line(W - 16, H - 9, [(f"updated {today}", "dim")], "end"),
    ]

    # left pane: a short shell session
    x, y = 16, TOP + 24
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
        bw = round(280 * size / top[0][1][0])
        out.append(line(x, y, [(name, "out")]))
        out.append(f'<rect x="{x + 170}" y="{y - 9}" width="280" height="9" fill="{C["track"]}"/>')
        out.append(f'<rect x="{x + 170}" y="{y - 9}" width="{bw}" height="9" fill="{color}"/>')
        out.append(line(SPLIT - 20, y, [(f"{pct:.0%}", "dim")], "end"))
        y += LH
    y += LH

    cmd("git log --all --oneline | wc -l")
    out.append(line(x, y, [(f"{s['commits']:,}", "accent"), (f"  commits since {s['since']}", "dim")]))
    y += LH * 2

    out.append(line(x, y, PROMPT))
    cx = x + 8.4 * sum(len(t) for t, _ in PROMPT)  # ponytail: assumes ~0.6em glyphs; off by a char in odd fonts
    out.append(f'<rect class="blink" x="{cx}" y="{y - 12}" width="8" height="15" fill="{C["cmd"]}"/>')

    # right pane: `cat cat.gif` "prints" the cat
    out.append(line(SPLIT + 16, TOP + 24, PROMPT[-1:] + [("cat cat.gif", "cmd")]))
    pw, ph = W - SPLIT - 32, H - TOP - 80
    scale = min(pw // fw, ph // fh)
    sw, sh = fw * scale, fh * scale
    sx, sy = SPLIT + (W - SPLIT - sw) // 2, TOP + 40 + (ph - sh) // 2
    # one strip of frames, slid left a frame at a time inside a clipped viewport
    out.append(
        f'<svg x="{sx}" y="{sy}" width="{sw}" height="{sh}" viewBox="0 0 {fw} {fh}">'
        f'<image width="{fw * n}" height="{fh}" image-rendering="pixelated" '
        f'style="image-rendering:pixelated;animation:cat {n * ms}ms steps({n}) infinite" '
        f'href="data:image/png;base64,{png}"/></svg>'
    )
    out.append("</svg>")
    return "\n".join(out)


DEMO = {"commits": 1234, "since": 2022,
        "langs": [("HTML", (900, "#e34c26")), ("Dart", (600, "#00B4AB")),
                  ("PHP", (400, "#4F5D95")), ("Python", (300, "#3572A5"))]}

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    stats = DEMO if "--demo" in sys.argv else fetch_stats()
    print("commits:", stats["commits"], [n for n, _ in stats["langs"][:5]])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sprite = sprite_sheet(os.path.join(here, "sprite.gif"))
    for mode, palette in PALETTES.items():
        with open(os.path.join(here, f"card-{mode}.svg"), "w", encoding="utf-8") as f:
            f.write(render(stats, sprite, today, palette))
    print("wrote card-dark.svg, card-light.svg")
