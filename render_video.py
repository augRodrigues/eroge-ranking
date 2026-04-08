#!/usr/bin/env python3
"""
EMQ Ranking Builder — Video Renderer (with authenticated download support)
=========================================================================
Downloads audio/video files from protected endpoints using session cookies.
Media files are stored persistently in a 'media' folder and never deleted.

Usage:
    python render_video.py                    # Uses playlist.json, cookies.json, crf=18, preset=slow
    python render_video.py my_playlist.json   # Specify custom playlist
    python render_video.py --force-render     # Force re-render all clips
    python render_video.py --out custom.mp4   # Custom output name
"""

import argparse
import base64
import io
import json
import math
import os
import shutil
import subprocess
import sys
import hashlib
from collections import defaultdict
from pathlib import Path
from datetime import datetime

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance
except ImportError:
    sys.exit("ERROR: Pillow not installed.  Run:  pip install Pillow requests")

try:
    import requests
except ImportError:
    sys.exit("ERROR: requests not installed.  Run:  pip install Pillow requests")


# ─── CONSTANTS ────────────────────────────────────────────────────────────────
TYPE_COLOR = {1: "#e8c547", 2: "#3ecfac", 3: "#6ba4f5", 4: "#a48ef8", 0: "#7a7a98"}
TYPE_ABBR = {1: "OP", 2: "ED", 3: "INS", 4: "BGM", 0: "OTHER"}

# ── Glassmorphism palette ─────────────────────────────────────────────────────
BG_BASE        = (18, 18, 18, 255)          # #121212
PANEL_BG       = (30, 30, 46, 191)          # rgba(30,30,46,0.75) per spec
PANEL_BORDER   = (255, 255, 255, 20)        # rgba(255,255,255,0.08) per spec
PANEL_RADIUS   = 12
ACCENT_VIOLET  = (139, 92, 246, 255)        # #8B5CF6
ACCENT_PINK    = (236, 72, 153, 255)        # #EC4899
TEXT_PRIMARY   = (226, 232, 240, 255)       # #E2E8F0
TEXT_SECONDARY = (148, 163, 184, 200)       # #94A3B8
FALLBACK_HUE   = (139, 92, 246)             # violet fallback if art is dark

CAL_C = (255, 82, 98, 255)
CAL_A = (52, 210, 198, 255)
CAL_L = (255, 152, 58, 255)
FRAME_PAD = 3
VIDEO_EXT = {".webm", ".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".flv"}
AUDIO_EXT = {".mp3", ".ogg", ".opus", ".m4a", ".aac", ".flac", ".wav"}

LATIN_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
]
JP_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/System/Library/Fonts/\u30d2\u30e9\u30ae\u30ce\u89d2\u30b4 ProN W3.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]


def hex_rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def hex_rgba(h, a=255):
    return (*hex_rgb(h), a)


def find_font(paths, size):
    for p in paths:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size), p
            except Exception:
                continue
    return ImageFont.load_default(), None


def load_fonts(args, W, H):
    user_lat = [args.font] if args.font else []
    user_jp = [args.font_jp] if args.font_jp else []

    lat_font, lat_path = find_font(user_lat + LATIN_FONTS, max(28, H // 20))
    jp_font, jp_path = find_font(user_jp + JP_FONTS, max(16, H // 48))

    print(f"  Latin font:    {lat_path or 'PIL default'}")
    print(f"  Japanese font: {jp_path or 'not found'}")

    def lf(sz):
        f, _ = find_font(user_lat + LATIN_FONTS, sz)
        return f

    def jf(sz):
        f, _ = find_font(user_jp + JP_FONTS, sz)
        return f

    return dict(
        title=lf(max(32, min(72, int(H / 14)))),
        jp=jf(max(18, int(H / 36))),
        badge=lf(max(12, int(H / 64))),
        game=lf(max(15, int(H / 46))),
        role_lbl=lf(max(11, int(H / 72))),
        role_nm=lf(max(13, int(H / 64))),
        rank_big=lf(max(40, int(H / 20))),
        bar_title=lf(max(24, int(H / 20))),
        bar_cal=lf(max(15, int(H / 54))),
        sound=lf(max(34, int(H / 14))),
        type_badge=lf(max(20, int(H / 34))),
        lat_path=lat_path,
        jp_path=jp_path,
    )


def _is_cjk(ch):
    cp = ord(ch)
    return (
        0x3000 <= cp <= 0x9FFF or   # CJK unified, hiragana, katakana, punctuation
        0xF900 <= cp <= 0xFAFF or   # CJK compatibility ideographs
        0x20000 <= cp <= 0x2FA1F    # CJK extensions B-F
    )


def _wrap_cjk(font, text, max_w):
    """Wrap text that may contain CJK characters (break at any char boundary)."""
    lines = []
    line = ""
    for ch in text:
        test = line + ch
        if _text_width(font, test) > max_w and line:
            lines.append(line)
            line = ch
        else:
            line = test
    if line:
        lines.append(line)
    return lines


def wrap_text_centered(draw, text, font, cx, y, max_w, line_h, fill, max_lines=3):
    if not text:
        return 0
    # Use CJK character-level wrapping if text contains CJK characters
    if any(_is_cjk(c) for c in text):
        lines = _wrap_cjk(font, text, max_w)[:max_lines]
    else:
        words = text.split(" ")
        line, lines = "", []
        for w in words:
            test = (line + " " + w).strip()
            bb = font.getbbox(test)
            if bb[2] - bb[0] > max_w and line:
                lines.append(line)
                line = w
                if len(lines) >= max_lines:
                    break
            else:
                line = test
        if line and len(lines) < max_lines:
            lines.append(line)
    h = 0
    for i, ln in enumerate(lines):
        w = _text_width(font, ln)
        draw.text((cx - w // 2, y + i * line_h), ln, font=font, fill=fill)
        h += line_h
    return h


def wrap_text(draw, text, font, x, y, max_w, line_h, fill, max_lines=3):
    if not text:
        return 0
    if any(_is_cjk(c) for c in text):
        lines = _wrap_cjk(font, text, max_w)[:max_lines]
    else:
        words = text.split(" ")
        line, lines = "", []
        for w in words:
            test = (line + " " + w).strip()
            bb = font.getbbox(test)
            if bb[2] - bb[0] > max_w and line:
                lines.append(line)
                line = w
                if len(lines) >= max_lines:
                    break
            else:
                line = test
        if line and len(lines) < max_lines:
            lines.append(line)
    for i, ln in enumerate(lines):
        draw.text((x, y + i * line_h), ln, font=font, fill=fill)
    return len(lines) * line_h


def layout_rects(W, H):
    margin = max(12, int(W * 0.018))
    rw = int(W * 0.18)
    left_w = W - rw - margin
    left_x0 = margin
    bh = max(int(H * 0.145), 118)
    top_m = max(10, int(H * 0.02))
    prog_h = max(4, int(H * 0.0055))
    gap_after_vid = max(4, int(H * 0.007))
    gap_prog_bar = max(3, int(H * 0.002))

    bottom_reserved = gap_after_vid + prog_h + gap_prog_bar + bh + margin
    avail_h = H - top_m - bottom_reserved
    avail_w = left_w - margin
    ar = avail_w / max(avail_h, 1)
    if ar > 16 / 9:
        vh = avail_h
        vw = int(vh * 16 / 9)
    else:
        vw = avail_w
        vh = int(vw * 9 / 16)

    vx = left_x0 + (avail_w - vw) // 2
    vy = top_m
    prog_y = vy + vh + gap_after_vid
    bar_y = prog_y + prog_h + gap_prog_bar
    bar_h = bh

    # Credits bar: left edge and right edge match the video frame exactly
    bar_x0 = vx - FRAME_PAD
    bar_x1 = vx + vw + FRAME_PAD
    bar_w = bar_x1 - bar_x0

    rx0 = W - rw - margin + max(4, int(rw * 0.05))
    rx1 = W - margin - max(4, int(rw * 0.05))
    panel_w = rx1 - rx0

    prog_x = vx - FRAME_PAD
    prog_w = vw + 2 * FRAME_PAD

    return dict(
        W=W,
        H=H,
        vx=vx,
        vy=vy,
        vw=vw,
        vh=vh,
        left_x0=left_x0,
        left_w=left_w,
        bar_x0=bar_x0,
        bar_x1=bar_x1,
        bar_y=bar_y,
        bar_w=bar_w,
        bar_h=bar_h,
        rw=rw,
        rx0=rx0,
        rx1=rx1,
        panel_w=panel_w,
        margin=margin,
        top_m=top_m,
        prog_x=prog_x,
        prog_y=prog_y,
        prog_w=prog_w,
        prog_h=prog_h,
    )


def _text_width(font, text):
    try:
        return int(font.getlength(text))
    except Exception:
        bb = font.getbbox(text)
        return bb[2] - bb[0]


def draw_text_segments(draw, x, y, segments, font):
    cx = x
    for text, fill in segments:
        if not text:
            continue
        draw.text((cx, y), text, font=font, fill=fill)
        cx += _text_width(font, text)


def segments_width(font, segments):
    return sum(_text_width(font, t) for t, _ in segments if t)


def draw_hcentered_line(draw, text, font, cx, y, fill):
    if not text:
        return
    w = _text_width(font, text)
    draw.text((cx - w // 2, y), text, font=font, fill=fill)


def fit_text_width(font, text, max_w):
    if _text_width(font, text) <= max_w:
        return text
    ell = "…"
    t = text
    while t and _text_width(font, t + ell) > max_w:
        t = t[:-1]
    return (t + ell) if t else ell


def build_cal_segments(artists):
    role_letter = {2: "C", 5: "A", 6: "L"}
    colors = {"C": CAL_C, "A": CAL_A, "L": CAL_L}
    order = {"C": 0, "A": 1, "L": 2}
    nm_roles = defaultdict(set)
    for a in artists or []:
        rid = a.get("role_id")
        if rid not in role_letter:
            continue
        nm = (a.get("name") or "").strip()
        if nm:
            nm_roles[nm].add(role_letter[rid])

    def name_key(n):
        return (min(order[r] for r in nm_roles[n]), n.lower())

    blocks = []
    for nm in sorted(nm_roles.keys(), key=name_key):
        letters = sorted(nm_roles[nm], key=lambda r: order[r])
        segs = []
        for i, letter in enumerate(letters):
            if i:
                segs.append((", ", TEXT_PRIMARY))
            segs.append((letter, colors[letter]))
        segs.append((" " + nm, TEXT_PRIMARY))
        blocks.append(segs)
    flat = []
    sep = (180, 188, 210, 255)
    for bi, block in enumerate(blocks):
        if bi:
            flat.append((" / ", sep))
        flat.extend(block)
    return flat


def sample_dominant_color(img):
    """Sample an aesthetic highlight color from the cover art."""
    if img is None:
        return FALLBACK_HUE
    try:
        small = img.resize((32, 32), Image.LANCZOS).convert("RGB")
        pixels = list(small.getdata())
        # Filter out absolute greys and pure black/white
        colored = [p for p in pixels if max(p) - min(p) > 20 and max(p) > 40]
        if not colored:
            colored = pixels # fallback to average if monochromatic

        r = sum(p[0] for p in colored) // len(colored)
        g = sum(p[1] for p in colored) // len(colored)
        b = sum(p[2] for p in colored) // len(colored)
        
        # Boost saturation slightly
        mx, mn = max(r,g,b), min(r,g,b)
        if mx > 0 and mx - mn > 0:
            scale = 255 / mx
            r, g, b = int(r*scale*0.7 + r*0.3), int(g*scale*0.7 + g*0.3), int(b*scale*0.7 + b*0.3)
        return (r, g, b)
    except Exception:
        return FALLBACK_HUE


def draw_frosted_panel(canvas, box, radius=PANEL_RADIUS, tint=PANEL_BG, border=PANEL_BORDER, blur_r=16):
    """
    Frosted-glass panel: crop canvas region → blur → tint overlay → rounded mask → paste back.
    """
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(canvas.width, x1), min(canvas.height, y1)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return

    region = canvas.crop((x0, y0, x1, y1)).convert("RGBA")
    
    scale_factor = 4 if blur_r >= 8 else 1
    if scale_factor > 1:
        sw, sh = max(1, w // scale_factor), max(1, h // scale_factor)
        sr = max(1, blur_r // scale_factor)
        blurred = region.resize((sw, sh), Image.BILINEAR).filter(ImageFilter.GaussianBlur(radius=sr)).resize((w, h), Image.LANCZOS)
    else:
        blurred = region.filter(ImageFilter.GaussianBlur(radius=blur_r))

    tint_layer = Image.new("RGBA", (w, h), tint)
    frosted = Image.alpha_composite(blurred, tint_layer)

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)

    result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    result.paste(frosted, mask=mask)
    canvas.alpha_composite(result, (x0, y0))

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, outline=border, width=1)


def draw_glow(canvas, cx, cy, radius, color_rgb, opacity=0.12):
    """Soft radial glow blob."""
    r, g, b = color_rgb
    a = int(255 * opacity)
    sz = int(radius * 2)
    blur_r = int(radius * 0.8)
    cw = sz + blur_r * 4
    
    glow = Image.new("RGBA", (cw, cw), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    
    pad = blur_r * 2
    gd.ellipse([pad, pad, pad + sz, pad + sz], fill=(r, g, b, a))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=blur_r))
    
    canvas.alpha_composite(glow, (int(cx - cw / 2), int(cy - cw / 2)))


def draw_bokeh(canvas, W, H, hero_rgb, count=18, max_opacity=0.08, seed=42):
    """Scatter very subtle soft bokeh dots — small, heavily blurred, low opacity."""
    import random
    rng = random.Random(seed)
    r, g, b = hero_rgb
    for _ in range(count):
        x = rng.randint(0, W)
        y = rng.randint(0, H)
        # Small dots: 4–12px radius
        sz = rng.randint(max(2, W // 240), max(4, W // 120))
        a = int(255 * rng.uniform(0.01, max_opacity * 0.6))
        blob_sz = sz * 4  # render larger for blur headroom
        blob = Image.new("RGBA", (blob_sz, blob_sz), (0, 0, 0, 0))
        pad = blob_sz // 4
        ImageDraw.Draw(blob).ellipse([pad, pad, blob_sz - pad, blob_sz - pad],
                                     fill=(r, g, b, a))
        blob = blob.filter(ImageFilter.GaussianBlur(radius=blob_sz // 3))
        ox, oy = max(0, x - blob_sz // 2), max(0, y - blob_sz // 2)
        # Clip to canvas bounds
        if ox + blob_sz > W or oy + blob_sz > H:
            blob = blob.crop((0, 0, min(blob_sz, W - ox), min(blob_sz, H - oy)))
        canvas.alpha_composite(blob, (ox, oy))


def draw_edge_vignette(canvas, W, H, strength=80):
    """Dark vignette only at the edges, center stays clear."""
    vign = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cx, cy = W / 2, H / 2
    max_d = math.hypot(cx, cy)
    pxw, pxh = max(32, W // 8), max(32, H // 8)
    small = Image.new("L", (pxw, pxh), 0)
    for y in range(pxh):
        for x in range(pxw):
            d = math.hypot((x / pxw - 0.5) * W, (y / pxh - 0.5) * H) / max_d
            v = int(strength * max(0, d - 0.45) / 0.55)
            small.putpixel((x, y), min(255, v))
    mask = small.resize((W, H), Image.LANCZOS)
    dark = Image.new("RGBA", (W, H), (8, 8, 12, 0))
    dark.putalpha(mask)
    canvas.alpha_composite(dark)


def draw_sound_panel(canvas, vx, vy, vw, vh, cover_img, accent_rgb, fonts):
    inner = Image.new("RGBA", (vw, vh), (8, 10, 20, 255))
    has_cover = cover_img is not None

    if has_cover:
        sc = max(vw / cover_img.width, vh / cover_img.height) * 1.05
        bw, bh = int(cover_img.width * sc), int(cover_img.height * sc)
        bg = cover_img.resize((bw, bh), Image.LANCZOS)
        bg = bg.crop(((bw - vw) // 2, (bh - vh) // 2, (bw - vw) // 2 + vw, (bh - vh) // 2 + vh))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=max(4, vw // 35)))
        bg = ImageEnhance.Brightness(bg).enhance(0.32)
        bg = ImageEnhance.Color(bg).enhance(0.75)
        inner = bg.convert("RGBA")

    pxw, pxh = max(32, vw // 6), max(32, vh // 6)
    vig_small = Image.new("L", (pxw, pxh), 0)
    mx, my = pxw / 2.0, pxh / 2.0
    max_d = math.hypot(mx, my) + 0.001
    for y in range(pxh):
        for x in range(pxw):
            d = math.hypot(x - mx, y - my) / max_d
            v = int(min(255, 210 * (d**1.2)))
            vig_small.putpixel((x, y), v)
    vig = vig_small.resize((vw, vh), Image.LANCZOS)
    black = Image.new("RGBA", (vw, vh), (0, 0, 0, 0))
    black.putalpha(vig)
    inner = Image.alpha_composite(inner, black)

    d = ImageDraw.Draw(inner)
    cx, cy = vw // 2, vh // 2
    max_r = int(math.hypot(vw / 2, vh / 2)) - 6
    for k in range(4):
        ri = int(max_r * (0.28 + k * 0.18))
        if ri < 8:
            continue
        a = 90 + k * 35
        d.ellipse(
            [cx - ri, cy - ri, cx + ri, cy + ri],
            outline=(*accent_rgb, min(255, a)),
            width=2,
        )

    R1, R2 = max_r - 20, max_r - 6
    n_ticks = 56
    for i in range(n_ticks):
        ang = 2 * math.pi * i / n_ticks - math.pi / 2
        x1 = cx + R1 * math.cos(ang)
        y1 = cy + R1 * math.sin(ang)
        x2 = cx + R2 * math.cos(ang)
        y2 = cy + R2 * math.sin(ang)
        d.line([(x1, y1), (x2, y2)], fill=(*accent_rgb, 140), width=1)

    msg = "SOUND ONLY"
    f = fonts["sound"]
    bb = f.getbbox(msg)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    tx = (vw - tw) // 2
    ty = (vh - th) // 2
    for ox, oy in ((3, 3), (2, 2), (1, 1)):
        d.text((tx + ox, ty + oy), msg, font=f, fill=(0, 0, 0, 160))
    d.text((tx, ty), msg, font=f, fill=(*accent_rgb[:3], 255))

    canvas.paste(inner, (vx, vy))


def _draw_corner_brackets(draw, box, color, w=2, arm=18):
    x0, y0, x1, y1 = box
    arm = min(arm, (x1 - x0) // 4, (y1 - y0) // 4)
    c = color
    draw.line([(x0, y0 + arm), (x0, y0), (x0 + arm, y0)], fill=c, width=w)
    draw.line([(x1 - arm, y0), (x1, y0), (x1, y0 + arm)], fill=c, width=w)
    draw.line([(x0, y1 - arm), (x0, y1), (x0 + arm, y1)], fill=c, width=w)
    draw.line([(x1 - arm, y1), (x1, y1), (x1, y1 - arm)], fill=c, width=w)


def _glow_line(draw, p0, p1, color, width=2):
    r, g, b, a = color
    for i, alpha in enumerate([40, 90, 180, 255][:width + 2]):
        da = alpha // (i + 1) if i else alpha
        draw.line([p0, p1], fill=(r, g, b, min(255, da)), width=width + (width > 1))


import base64
import io


def _make_circle_avatar(img_rgba, size):
    """Crop image to a circle of given diameter at 2× for AA, return RGBA Image at `size`."""
    s2 = size * 2
    img = img_rgba.resize((s2, s2), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (s2, s2), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, s2 - 1, s2 - 1], fill=255)
    out2 = Image.new("RGBA", (s2, s2), (0, 0, 0, 0))
    out2.paste(img, mask=mask)
    return out2.resize((size, size), Image.LANCZOS)


def _draw_circle_ring_aa(canvas, cx, cy, diameter, ring_color, ring_width):
    """Draw an anti-aliased thick ring by rendering at 2× and downscaling."""
    s2 = diameter * 2
    ring2 = Image.new("RGBA", (s2, s2), (0, 0, 0, 0))
    rw2 = max(2, ring_width * 2)
    ImageDraw.Draw(ring2).ellipse([rw2 // 2, rw2 // 2, s2 - rw2 // 2 - 1, s2 - rw2 // 2 - 1],
                                   outline=ring_color, width=rw2)
    ring = ring2.resize((diameter, diameter), Image.LANCZOS)
    ox = cx - diameter // 2
    oy = cy - diameter // 2
    canvas.alpha_composite(ring, (ox, oy))


def _load_avatar_b64(b64_str, size):
    """Decode a base64 data-URL avatar and return a circular RGBA image, or None."""
    if not b64_str:
        return None
    try:
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        data = base64.b64decode(b64_str)
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        return _make_circle_avatar(img, size)
    except Exception:
        return None


avatar_img_cache = {}

def _load_avatar_cached(b64_str, size):
    if not b64_str:
        return None
    key = (hash(b64_str), size)
    if key in avatar_img_cache:
        return avatar_img_cache[key]
    img = _load_avatar_b64(b64_str, size)
    if img:
        avatar_img_cache[key] = img
    return img


def render_overlay_party(entry, cover_img, fonts, W, H, out_path, has_video_window, participants_data):
    """
    Party-rank overlay. Right panel shows round profile pics + individual scores.
    Credits bar shows song title + CAL line only (no JP title / developer).
    participants_data: list of {name, score, avatar_b64}
    """
    L = layout_rects(W, H)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Background
    draw.rectangle([0, 0, W, H], fill=BG_BASE)
    hero = sample_dominant_color(cover_img)

    if cover_img:
        sw, sh = W // 8, H // 8
        sc = max(sw / cover_img.width, sh / cover_img.height) * 1.06
        dw, dh = int(cover_img.width * sc), int(cover_img.height * sc)
        bg = cover_img.resize((dw, dh), Image.BILINEAR)
        bg = bg.crop(((dw - sw) // 2, (dh - sh) // 2, (dw - sw) // 2 + sw, (dh - sh) // 2 + sh))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=(W // 14) // 8))
        bg = bg.resize((W, H), Image.LANCZOS)
        bg = ImageEnhance.Brightness(bg).enhance(0.50)
        bg = ImageEnhance.Color(bg).enhance(1.0)
        canvas.paste(bg.convert("RGBA"), (0, 0))

    draw_edge_vignette(canvas, W, H)

    draw_bokeh(canvas, W, H, hero, count=18, max_opacity=0.08)

    draw = ImageDraw.Draw(canvas)
    tp_id = entry.get("song_type_id", 0)
    type_color = hex_rgb(TYPE_COLOR.get(tp_id, "#6ba4f5"))

    # ── Hero glow ─────────────────────────────────────────────────────────────
    vx, vy, vw, vh = L["vx"], L["vy"], L["vw"], L["vh"]
    draw_glow(canvas, vx + vw // 2, vy + vh // 2, min(vw, vh) // 2, hero, opacity=0.12)
    draw = ImageDraw.Draw(canvas)

    # ── Video frame — hero-tinted border with inner glow ─────────────────────
    fx0v = vx - FRAME_PAD; fy0v = vy - FRAME_PAD
    fx1v = vx + vw + FRAME_PAD; fy1v = vy + vh + FRAME_PAD
    # Outer glow ring
    draw.rounded_rectangle([fx0v, fy0v, fx1v, fy1v], radius=6,
                            outline=(*hero, int(255 * 0.35)), width=2)

    if has_video_window:
        canvas.paste(Image.new("RGBA", (vw, vh), (0, 0, 0, 0)), (vx, vy))
    else:
        draw_sound_panel(canvas, vx, vy, vw, vh, cover_img, type_color, fonts)

    draw = ImageDraw.Draw(canvas)

    # ── Progress bar ──────────────────────────────────────────────────────────
    px, py, pww, ph = L["prog_x"], L["prog_y"], L["prog_w"], L["prog_h"]
    draw.rounded_rectangle([px, py, px + pww, py + ph], radius=2,
                            fill=(30, 30, 46, 200))
    draw.rounded_rectangle([px, py, px + pww, py + ph], radius=2,
                            outline=(*hero, 60), width=1)

    # ── Credits bar — glass panel ─────────────────────────────────────────────
    bx, by = L["bar_x0"], L["bar_y"]
    bx1, bh = L["bar_x1"], L["bar_h"]
    draw_frosted_panel(canvas, (bx, by, bx1, by + bh), radius=PANEL_RADIUS)
    draw = ImageDraw.Draw(canvas)
    draw.line([(bx + PANEL_RADIUS, by), (bx1 - PANEL_RADIUS, by)],
              fill=(*hero, int(255 * 0.75)), width=2)

    # Type badge (OP/ED/etc) — colored accent pill
    type_font = fonts["type_badge"]
    st_abbr = TYPE_ABBR.get(tp_id, "OTHER")
    type_w = max(60, _text_width(type_font, st_abbr) + 24)
    type_h = max(34, int(bh * 0.45))
    
    # Text block centers exactly on the bottom bar
    credits_cx = (bx + bx1) // 2
    credits_max_w = max(80, (bx1 - bx) - 64 - type_w)

    song_t = entry.get("title", "")
    artists = entry.get("artists", [])
    voc = ", ".join(a["name"] for a in artists if a.get("role_id") == 1)
    
    fs_title = max(18, min(36, int(850 / max(len(song_t), 12))))
    try:
        if fonts.get("lat_path") and not any(_is_cjk(c) for c in song_t):
            tf = ImageFont.truetype(fonts["lat_path"], fs_title)
        elif fonts.get("jp_path"):
            tf = ImageFont.truetype(fonts["jp_path"], fs_title)
        else:
            tf = fonts["bar_title"]
    except Exception:
        tf = fonts["bar_title"]
    
    fs_voc = max(14, int(fs_title * 0.75))
    try:
        if fonts.get("lat_path") and not any(_is_cjk(c) for c in voc):
            vf = ImageFont.truetype(fonts["lat_path"], fs_voc)
        elif fonts.get("jp_path"):
            vf = ImageFont.truetype(fonts["jp_path"], fs_voc)
        else:
            vf = fonts["badge"]
    except Exception:
        vf = fonts["badge"]

    title_clean = fit_text_width(tf, song_t, credits_max_w - (_text_width(vf, " — " + voc) if voc else 0))
    tw = _text_width(tf, title_clean)
    vw = _text_width(vf, " — " + voc) if voc else 0
    tbb = tf.getbbox(title_clean)
    title_h = tbb[3] - tbb[1]

    cal_font = fonts["bar_cal"]
    cal_segs = build_cal_segments(artists)
    w_cal = segments_width(cal_font, cal_segs) if cal_segs else 0
    gap_title_cal = max(10, int(title_h * 0.38)) if cal_segs else 0
    try:
        cal_bb = cal_font.getbbox("Ag")
        cal_h = (cal_bb[3] - cal_bb[1] + 3) if cal_segs else 0
    except Exception:
        cal_h = 20 if cal_segs else 0

    # Game title below CAL
    game_t = (entry.get("game") or "").strip()
    game_font = fonts["game"]
    try:
        game_bb = game_font.getbbox("Ag")
        game_h = (game_bb[3] - game_bb[1] + 4) if game_t else 0
    except Exception:
        game_h = 20 if game_t else 0
    gap_cal_game = 8 if game_t and cal_segs else 0

    block_h = title_h + gap_title_cal + cal_h + gap_cal_game + game_h
    y_block_top = by + max(0, (bh - block_h) // 2)

    cx_line1 = credits_cx - (tw + vw) // 2
    
    group_left = cx_line1
    if cal_segs:
        group_left = min(group_left, credits_cx - w_cal // 2)
    if game_t:
        game_w = _text_width(game_font, game_t)
        group_left = min(group_left, credits_cx - game_w // 2)
    
    # Draw badge flanking the title text group (prevent overlap)
    badge_x = max(bx + 16, group_left - type_w - 24)
    badge_y = by + (bh - type_h) // 2
    sf = 3
    pill = Image.new("RGBA", (type_w * sf, type_h * sf), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pill)
    pd.rounded_rectangle([0, 0, (type_w * sf) - 1, (type_h * sf) - 1],
                         radius=(type_h * sf) // 2,
                         outline=(*type_color, 210), width=2 * sf,
                         fill=(*type_color, 30))
    pill = pill.resize((type_w, type_h), Image.LANCZOS)
    canvas.alpha_composite(pill, (badge_x, badge_y))
    draw = ImageDraw.Draw(canvas)
    draw.text((badge_x + type_w // 2, badge_y + type_h // 2), st_abbr,
              font=type_font, fill=type_color, anchor="mm")

    draw.text((cx_line1, y_block_top), title_clean, font=tf, fill=(255, 255, 255, 255))
    if voc:
        vbb = vf.getbbox(" — " + voc)
        y_voc = y_block_top + (tbb[1] + tbb[3] - vbb[1] - vbb[3]) / 2
        draw.text((cx_line1 + tw, y_voc), " — " + voc, font=vf, fill=(180, 188, 200, 255))

    if cal_segs:
        y_cal = y_block_top + title_h + gap_title_cal
        draw_text_segments(draw, credits_cx - w_cal // 2, y_cal, cal_segs, cal_font)
    if game_t:
        y_game = y_block_top + title_h + gap_title_cal + cal_h + gap_cal_game
        game_str = fit_text_width(game_font, game_t, credits_max_w)
        draw_hcentered_line(draw, game_str, game_font, credits_cx, y_game, TEXT_PRIMARY)

    # ── Right panel: rank + participant grid ─────────────────────────────────
    rx0, rx1 = L["rx0"], L["rx1"]
    pw = rx1 - rx0
    pcx = (rx0 + rx1) // 2
    py0 = L["top_m"]
    panel_bottom = L["bar_y"] + L["bar_h"]
    draw_glow(canvas, pcx, (py0 + panel_bottom) // 2, pw, hero, opacity=0.12)
    draw = ImageDraw.Draw(canvas)
    draw_frosted_panel(canvas, (rx0 - 4, py0, rx1 + 4, panel_bottom), radius=PANEL_RADIUS)
    draw = ImageDraw.Draw(canvas)
    draw.line([(rx0 - 4, py0 + PANEL_RADIUS), (rx0 - 4, panel_bottom - PANEL_RADIUS)],
              fill=(*hero, int(255 * 0.75)), width=2)

    # Rank number — pink accent
    rank = entry.get("rank", 0)
    rh = int(pw * 0.26)
    rank_str = f"#{rank}"
    draw_glow(canvas, pcx, py0 + rh // 2, rh // 2, hero, opacity=0.15)
    draw = ImageDraw.Draw(canvas)
    draw.text((pcx, py0 + rh // 2), rank_str, font=fonts["rank_big"],
              fill=(*hero, 255), anchor="mm")

    # ── Participant grid layout ───────────────────────────────────────────────
    n = len(participants_data)
    grid_top = py0 + rh + 6
    grid_bottom = panel_bottom - 28   # leave room for avg score at bottom
    grid_h = max(1, grid_bottom - grid_top)
    grid_w = pw - 4

    # Decide columns: try 2 cols first, fall back to 1 if avatars would be too small
    MIN_AV = max(36, H // 22)
    for cols in (2, 1):
        rows = math.ceil(n / cols)
        cell_w = grid_w // cols
        name_sz = max(10, min(H // 62, cell_w // 5))
        name_font, _ = find_font(LATIN_FONTS, name_sz)
        name_line_h = name_sz + 4
        av_d = cell_w - 8   # avatar fills cell width
        # Use 2 cols only if we have enough participants AND avatars stay readable
        # Minimum: 5+ participants for 2 cols, or avatar would be too small
        if av_d >= MIN_AV or cols == 1:
            av_d = max(MIN_AV, av_d)
            break

    # Score font: bold and readable at a glance
    score_sz = max(14, min(32, av_d // 4))
    score_font, _ = find_font(LATIN_FONTS, score_sz)

    # Cell height = name + avatar + gap
    cell_h = name_line_h + av_d + 8

    # Grid starts at top, no vertical centering
    grid_offset = 0

    print(f"    Party grid: n={n} cols={cols} rows={rows} pw={pw} av_d={av_d} cell_h={cell_h} grid_h={grid_h} offset={grid_offset}")

    # Score extremes for coloring
    scored = [p["score"] for p in participants_data if p["score"] > 0]
    max_sc = max(scored) if scored else -1
    min_sc = min(scored) if scored else -1

    for idx_p, p in enumerate(participants_data):
        col = idx_p % cols
        row = idx_p // cols
        # cell center x
        cx_cell = rx0 + 2 + col * cell_w + cell_w // 2
        # cell top y — offset to vertically center the grid
        cy_cell = grid_top + grid_offset + row * cell_h

        # ── Name label — sized to fit within avatar width ─────────────────
        # ── Name label — above avatar ─────────────────────────────────────
        name_str = p["name"]
        while name_str and _text_width(name_font, name_str) > av_d:
            name_str = name_str[:-1]
        if name_str != p["name"]:
            name_str = name_str[:-1] + "…"
        nw = _text_width(name_font, name_str)
        draw.text((cx_cell - nw // 2, cy_cell + 2), name_str,
                  font=name_font, fill=(255, 255, 255, 255))

        # ── Avatar circle ─────────────────────────────────────────────────
        av_cx = cx_cell
        av_cy = cy_cell + name_line_h + av_d // 2

        avatar_img = _load_avatar_cached(p.get("avatar_b64", ""), av_d)
        if avatar_img:
            canvas.alpha_composite(avatar_img, (av_cx - av_d // 2, av_cy - av_d // 2))
        else:
            draw.ellipse([av_cx - av_d // 2, av_cy - av_d // 2,
                          av_cx + av_d // 2, av_cy + av_d // 2],
                         fill=(20, 26, 44, 255))
            draw.text((av_cx, av_cy), "?", font=name_font,
                      fill=(100, 110, 140, 200), anchor="mm")

        # ── Score — large bold number overlapping bottom of avatar ──────────
        sc = p["score"]
        sc_str = str(int(sc)) if sc == int(sc) and sc > 0 else (str(sc) if sc > 0 else "–")
        if sc > 0 and sc == max_sc and sc != min_sc:
            sc_color = (*ACCENT_PINK[:3], 255)
        elif sc > 0 and sc == min_sc and sc != max_sc:
            sc_color = (*ACCENT_VIOLET[:3], 255)
        else:
            sc_color = (255, 255, 255, 240)

        sc_y = av_cy + av_d // 2 - score_sz // 2 - 2
        for ox, oy in ((-1, -1), (1, -1), (-1, 1), (1, 1), (0, 2), (0, -2)):
            draw.text((av_cx + ox, sc_y + oy), sc_str, font=score_font,
                      fill=(0, 0, 0, 200), anchor="mm")
        draw.text((av_cx, sc_y), sc_str, font=score_font, fill=sc_color, anchor="mm")

    # Average score at bottom of panel — more prominent
    avg = entry.get("party_avg_score", 0)
    if avg:
        avg_font, _ = find_font(LATIN_FONTS, max(15, H // 54))
        avg_str = f"avg  {avg:.1f}"
        aw = _text_width(avg_font, avg_str)
        pad_x, pad_y = 10, 4
        ax0 = pcx - aw // 2 - pad_x
        ay0 = panel_bottom - 26
        ax1 = pcx + aw // 2 + pad_x
        ay1 = panel_bottom - 6
        draw.rounded_rectangle([ax0, ay0, ax1, ay1], radius=6,
                                fill=(*hero, 30))
        draw.rounded_rectangle([ax0, ay0, ax1, ay1], radius=6,
                                outline=(*hero, 80), width=1)
        draw.text((pcx, (ay0 + ay1) // 2), avg_str, font=avg_font,
                  fill=(*hero, 230), anchor="mm")

    canvas.save(out_path, "PNG")


def render_overlay(entry, cover_img, fonts, W, H, out_path, has_video_window, participants_data=None):
    if participants_data is not None:
        return render_overlay_party(entry, cover_img, fonts, W, H, out_path, has_video_window, participants_data)
    L = layout_rects(W, H)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # ── Background: #121212 base + blurred cover art ──────────────────────────
    draw.rectangle([0, 0, W, H], fill=BG_BASE)
    hero = sample_dominant_color(cover_img)

    if cover_img:
        sw, sh = W // 8, H // 8
        sc = max(sw / cover_img.width, sh / cover_img.height) * 1.06
        dw, dh = int(cover_img.width * sc), int(cover_img.height * sc)
        bg = cover_img.resize((dw, dh), Image.BILINEAR)
        bg = bg.crop(((dw - sw) // 2, (dh - sh) // 2, (dw - sw) // 2 + sw, (dh - sh) // 2 + sh))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=(W // 14) // 8))
        bg = bg.resize((W, H), Image.LANCZOS)
        bg = ImageEnhance.Brightness(bg).enhance(0.50)
        bg = ImageEnhance.Color(bg).enhance(1.0)
        canvas.paste(bg.convert("RGBA"), (0, 0))

    # Vignette
    draw_edge_vignette(canvas, W, H)

    # Bokeh atmosphere
    draw_bokeh(canvas, W, H, hero, count=18, max_opacity=0.08)

    draw = ImageDraw.Draw(canvas)
    tp_id = entry.get("song_type_id", 0)
    type_color = hex_rgb(TYPE_COLOR.get(tp_id, "#6ba4f5"))

    # ── Hero glow behind panels ───────────────────────────────────────────────
    vx, vy, vw, vh = L["vx"], L["vy"], L["vw"], L["vh"]
    draw_glow(canvas, vx + vw // 2, vy + vh // 2, min(vw, vh) // 2, hero, opacity=0.12)
    draw = ImageDraw.Draw(canvas)

    # ── Video frame — hero-tinted border with glow ───────────────────────────
    fx0 = vx - FRAME_PAD; fy0 = vy - FRAME_PAD
    fx1 = vx + vw + FRAME_PAD; fy1 = vy + vh + FRAME_PAD
    draw.rounded_rectangle([fx0, fy0, fx1, fy1], radius=6,
                            outline=(*hero, int(255 * 0.35)), width=2)

    if has_video_window:
        canvas.paste(Image.new("RGBA", (vw, vh), (0, 0, 0, 0)), (vx, vy))
    else:
        draw_sound_panel(canvas, vx, vy, vw, vh, cover_img, type_color, fonts)

    draw = ImageDraw.Draw(canvas)

    # ── Progress bar ──────────────────────────────────────────────────────────
    px, py, pww, ph = L["prog_x"], L["prog_y"], L["prog_w"], L["prog_h"]
    draw.rounded_rectangle([px, py, px + pww, py + ph], radius=2,
                            fill=(30, 30, 46, 200))
    draw.rounded_rectangle([px, py, px + pww, py + ph], radius=2,
                            outline=(*hero, 60), width=1)

    # ── Credits bar — glass panel ─────────────────────────────────────────────
    bx, by = L["bar_x0"], L["bar_y"]
    bx1, bh = L["bar_x1"], L["bar_h"]
    draw_frosted_panel(canvas, (bx, by, bx1, by + bh), radius=PANEL_RADIUS)
    draw = ImageDraw.Draw(canvas)
    # Hero-tinted top edge highlight
    draw.line([(bx + PANEL_RADIUS, by), (bx1 - PANEL_RADIUS, by)],
              fill=(*hero, int(255 * 0.75)), width=2)

    # Type badge (OP/ED/etc) — colored accent pill
    type_font = fonts["type_badge"]
    st_abbr = TYPE_ABBR.get(tp_id, "OTHER")
    type_w = max(60, _text_width(type_font, st_abbr) + 24)
    type_h = max(34, int(bh * 0.45))
    
    # Text block centers exactly on the bottom bar
    credits_cx = (bx + bx1) // 2
    credits_max_w = max(80, (bx1 - bx) - 64 - type_w)

    song_t = entry.get("title", "")
    artists = entry.get("artists", [])
    voc = ", ".join(a["name"] for a in artists if a.get("role_id") == 1)
    
    fs_title = max(18, min(36, int(850 / max(len(song_t), 12))))
    try:
        if fonts.get("lat_path") and not any(_is_cjk(c) for c in song_t):
            tf = ImageFont.truetype(fonts["lat_path"], fs_title)
        elif fonts.get("jp_path"):
            tf = ImageFont.truetype(fonts["jp_path"], fs_title)
        else:
            tf = fonts["bar_title"]
    except Exception:
        tf = fonts["bar_title"]
    
    fs_voc = max(14, int(fs_title * 0.75))
    try:
        if fonts.get("lat_path") and not any(_is_cjk(c) for c in voc):
            vf = ImageFont.truetype(fonts["lat_path"], fs_voc)
        elif fonts.get("jp_path"):
            vf = ImageFont.truetype(fonts["jp_path"], fs_voc)
        else:
            vf = fonts["badge"]
    except Exception:
        vf = fonts["badge"]

    title_clean = fit_text_width(tf, song_t, credits_max_w - (_text_width(vf, " — " + voc) if voc else 0))
    tw = _text_width(tf, title_clean)
    vw = _text_width(vf, " — " + voc) if voc else 0
    tbb = tf.getbbox(title_clean)
    title_h = tbb[3] - tbb[1]

    cal_font = fonts["bar_cal"]
    cal_segs = build_cal_segments(artists)
    w_cal = segments_width(cal_font, cal_segs) if cal_segs else 0
    gap_title_cal = max(10, int(title_h * 0.38)) if cal_segs else 0
    try:
        cal_bb = cal_font.getbbox("Ag")
        cal_h = (cal_bb[3] - cal_bb[1] + 3) if cal_segs else 0
    except Exception:
        cal_h = 20 if cal_segs else 0

    # Credits bar: song title + CAL only — VN title is shown in the sidebar
    block_h = title_h + gap_title_cal + cal_h
    y_block_top = by + max(0, (bh - block_h) // 2)

    cx_line1 = credits_cx - (tw + vw) // 2
    
    group_left = cx_line1
    if cal_segs:
        group_left = min(group_left, credits_cx - w_cal // 2)
        
    # Draw badge flanking the title text group (prevent overlap)
    badge_x = max(bx + 16, group_left - type_w - 24)
    badge_y = by + (bh - type_h) // 2
    sf = 3
    pill = Image.new("RGBA", (type_w * sf, type_h * sf), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pill)
    pd.rounded_rectangle([0, 0, (type_w * sf) - 1, (type_h * sf) - 1],
                         radius=(type_h * sf) // 2,
                         outline=(*type_color, 210), width=2 * sf,
                         fill=(*type_color, 30))
    pill = pill.resize((type_w, type_h), Image.LANCZOS)
    canvas.alpha_composite(pill, (badge_x, badge_y))
    draw = ImageDraw.Draw(canvas)
    draw.text((badge_x + type_w // 2, badge_y + type_h // 2), st_abbr,
              font=type_font, fill=type_color, anchor="mm")

    draw.text((cx_line1, y_block_top), title_clean, font=tf, fill=(255, 255, 255, 255))
    if voc:
        vbb = vf.getbbox(" — " + voc)
        y_voc = y_block_top + (tbb[1] + tbb[3] - vbb[1] - vbb[3]) / 2
        draw.text((cx_line1 + tw, y_voc), " — " + voc, font=vf, fill=(180, 188, 200, 255))

    if cal_segs:
        y_cal = y_block_top + title_h + gap_title_cal
        draw_text_segments(draw, credits_cx - w_cal // 2, y_cal, cal_segs, cal_font)

    # ── Right sidebar — glass panel ───────────────────────────────────────────
    rx0, rx1 = L["rx0"], L["rx1"]
    pw = rx1 - rx0
    pcx = (rx0 + rx1) // 2
    py0 = L["top_m"]
    panel_bottom = L["bar_y"] + L["bar_h"]

    # Glow behind sidebar
    draw_glow(canvas, pcx, (py0 + panel_bottom) // 2, pw, hero, opacity=0.12)
    draw = ImageDraw.Draw(canvas)
    draw_frosted_panel(canvas, (rx0 - 4, py0, rx1 + 4, panel_bottom), radius=PANEL_RADIUS)
    draw = ImageDraw.Draw(canvas)
    # Hero-tinted left edge
    draw.line([(rx0 - 4, py0 + PANEL_RADIUS), (rx0 - 4, panel_bottom - PANEL_RADIUS)],
              fill=(*hero, int(255 * 0.75)), width=2)

    # Rank number — pink accent with subtle glow
    rank = entry.get("rank", 0)
    rh = int(pw * 0.30)
    rank_str = f"#{rank}"
    # Soft glow behind rank text
    draw_glow(canvas, pcx, py0 + rh // 2, rh // 2, hero, opacity=0.15)
    draw = ImageDraw.Draw(canvas)
    draw.text((pcx, py0 + rh // 2), rank_str, font=fonts["rank_big"],
              fill=(*hero, 255), anchor="mm")

    # Cover art — no explicit separator line; gap provides the breathing room
    cov_top = py0 + rh + 14
    cov_max_h = int((panel_bottom - cov_top) * 0.46)
    cov_w, cov_h = pw - 8, cov_max_h
    cx0 = pcx - cov_w // 2
    if cover_img:
        sc2 = min(cov_w / cover_img.width, cov_h / cover_img.height)
        dw, dh = int(cover_img.width * sc2), int(cover_img.height * sc2)
        fit = cover_img.resize((dw, dh), Image.LANCZOS).convert("RGBA")
        
        # Draw on canvas
        px = cx0 + (cov_w - dw) // 2
        py = cov_top + (cov_h - dh) // 2
        
        # Paste image
        canvas.alpha_composite(fit, (px, py))
        
        # Tight subtle outline EXACTLY on image
        draw.rectangle([px, py, px + dw - 1, py + dh - 1],
                       outline=(*hero, int(255 * 0.4)), width=1)
    else:
        draw_frosted_panel(canvas, (cx0, cov_top, cx0 + cov_w, cov_top + cov_h), radius=8)
        draw = ImageDraw.Draw(canvas)
        draw.text((cx0 + cov_w // 2, cov_top + cov_h // 2), "No cover",
                  font=fonts["badge"], fill=TEXT_SECONDARY, anchor="mm")

    draw = ImageDraw.Draw(canvas)
    meta_y = cov_top + cov_h + 16
    vn_ro = (entry.get("vn_romaji") or entry.get("game") or "").strip()
    vn_jp = (entry.get("vn_title_jp") or entry.get("game_jp") or "").strip()
    pw_inner = pw - 32
    meta_x = rx0 + 16
    lbl_font = fonts["badge"]
    lbl_gap = max(20, H // 44)
    sect_gap = max(18, H // 34)

    def draw_label(d, txt, f, x, y, c):
        sp = " ".join(list(txt.upper()))
        d.text((x, y), sp, font=f, fill=c)

    def _lh(f):
        bb = f.getbbox("Agシ")
        return (bb[3] - bb[1]) + max(6, H // 120)

    dev = (entry.get("vn_developers") or "").strip()
    rel = (entry.get("vn_released") or "").strip()
    show_jp = bool(vn_jp and vn_jp != vn_ro)
    lh_jp  = _lh(fonts["jp"])
    lh_dev = _lh(fonts["role_nm"])

    # Pre-measure cost of the sections below the romaji title
    jp_lines_n  = min(3, len(_wrap_cjk(fonts["jp"], vn_jp, pw_inner))) if show_jp else 0
    jp_cost  = jp_lines_n * lh_jp + sect_gap if jp_lines_n else sect_gap
    dev_cost = (lbl_gap + min(2, max(1, len(dev.split()))) * lh_dev + sect_gap) if dev else 0
    rel_cost = (lbl_gap + lh_dev) if rel else 0

    meta_budget = panel_bottom - meta_y - 8
    ro_budget = meta_budget - lbl_gap - jp_cost - dev_cost - rel_cost - max(4, H // 180)

    # Find the largest font that shows the FULL romaji title within ro_budget height.
    # The simulation counts ALL lines needed (no artificial cap).
    ro_font = fonts["game"]
    ro_actual_lines = 20  # will be computed below
    min_sz = max(9, int(H / 46) // 2)
    if vn_ro and ro_budget > 0 and fonts.get("lat_path"):
        default_sz = int(H / 46)
        for sz in range(default_sz, min_sz - 1, -1):
            try:
                f_try = ImageFont.truetype(fonts["lat_path"], sz)
            except Exception:
                break
            # Count every line the title ACTUALLY needs at this size (no cap)
            words = vn_ro.split(" ")
            line, sim_lines = "", []
            for w in words:
                test = (line + " " + w).strip()
                bb_t = f_try.getbbox(test)
                if (bb_t[2] - bb_t[0]) > pw_inner and line:
                    sim_lines.append(line)
                    line = w
                else:
                    line = test
            if line:
                sim_lines.append(line)
            lh_try = (f_try.getbbox("Ag")[3] - f_try.getbbox("Ag")[1]) + max(6, H // 120)
            if len(sim_lines) * lh_try <= ro_budget:
                ro_font = f_try
                ro_actual_lines = len(sim_lines)
                break
        else:
            # Fallback: minimum font; compute actual lines for wrap_text
            try:
                ro_font = ImageFont.truetype(fonts["lat_path"], min_sz)
            except Exception:
                pass
            words = vn_ro.split(" ")
            line, sim_lines = "", []
            for w in words:
                test = (line + " " + w).strip()
                if _text_width(ro_font, test) > pw_inner and line:
                    sim_lines.append(line)
                    line = w
                else:
                    line = test
            if line:
                sim_lines.append(line)
            ro_actual_lines = len(sim_lines)
    else:
        ro_actual_lines = 3

    draw_label(draw, "TITLE", lbl_font, meta_x, meta_y, TEXT_SECONDARY)
    meta_y += lbl_gap
    if vn_ro:
        meta_y += wrap_text(draw, vn_ro, ro_font, meta_x, meta_y,
                            pw_inner, _lh(ro_font), TEXT_PRIMARY, max_lines=ro_actual_lines)
        meta_y += max(4, H // 180)
    if show_jp:
        meta_y += wrap_text(draw, vn_jp, fonts["jp"], meta_x, meta_y,
                            pw_inner, lh_jp, TEXT_SECONDARY, max_lines=3)
    meta_y += sect_gap

    if dev:
        draw_label(draw, "DEVELOPER", lbl_font, meta_x, meta_y, TEXT_SECONDARY)
        meta_y += lbl_gap
        meta_y += wrap_text(draw, dev, fonts["role_nm"], meta_x, meta_y,
                            pw_inner, lh_dev, TEXT_PRIMARY, max_lines=2)
        meta_y += sect_gap

    if rel:
        draw_label(draw, "RELEASE", lbl_font, meta_x, meta_y, TEXT_SECONDARY)
        meta_y += lbl_gap
        draw.text((meta_x, meta_y), rel, font=fonts["role_nm"], fill=TEXT_PRIMARY)

    canvas.save(out_path, "PNG")


def download_cover(url, dest, session):
    if not url:
        return None
    if os.path.isfile(dest):
        try:
            return Image.open(dest).convert("RGB")
        except Exception:
            pass
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        with open(dest, "wb") as f:
            f.write(r.content)
        return Image.open(dest).convert("RGB")
    except Exception:
        return None


def load_auth_session(cookie_file=None, token=None):
    """Create a requests session with authentication."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 EMQ-Ranking-Builder/5",
        "Accept": "video/webm,video/mp4,audio/webm,audio/ogg,audio/mp3,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://erogemusicquiz.com/",
        "Origin": "https://erogemusicquiz.com",
        "Connection": "keep-alive",
    })
    
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
        print("  Using bearer token authentication")
        return session
    
    if cookie_file and os.path.isfile(cookie_file):
        try:
            with open(cookie_file, "r") as f:
                cookies_data = json.load(f)
            for cookie in cookies_data:
                if isinstance(cookie, dict):
                    session.cookies.set(
                        cookie.get("name", ""),
                        cookie.get("value", ""),
                        domain=cookie.get("domain", "erogemusicquiz.com"),
                        path=cookie.get("path", "/"),
                        secure=cookie.get("secure", False),
                    )
            print(f"  Loaded {len(session.cookies)} cookies from {cookie_file}")
            print(f"  Cookies: {list(session.cookies.keys())}")
        except Exception as e:
            print(f"  Warning: Failed to load cookies: {e}")
    
    return session


def download_media_file(media_url, dest_path, session, media_type="audio"):
    """Download media file (audio or video) from authenticated endpoint."""
    if not media_url:
        return None
    
    # Check if file already exists and is valid
    if dest_path and dest_path.is_file() and dest_path.stat().st_size > 1024:
        print(f"    Using existing file: {dest_path.name}")
        return dest_path
    
    try:
        file_type = "Video" if media_type == "video" else "Audio"
        print(f"    Downloading {file_type}: {media_url.split('/')[-1][:50]}...")
        
        headers = {
            "Range": "bytes=0-",
            "Accept": "video/webm,video/mp4,audio/webm,audio/ogg,audio/mp3,*/*;q=0.8",
            "Referer": "https://erogemusicquiz.com/",
            "Origin": "https://erogemusicquiz.com",
        }
        
        # Download the file with streaming
        resp = session.get(media_url, timeout=120, stream=True, headers=headers)
        
        if resp.status_code == 401:
            print("    ✗ Authentication failed (401). Cookies may be expired.")
            return None
        if resp.status_code == 403:
            print("    ✗ Access forbidden (403). Check your permissions.")
            return None
        if resp.status_code == 404:
            print("    ✗ Media URL not found (404).")
            return None
        
        resp.raise_for_status()
        
        # Get total size if available
        total_size = int(resp.headers.get("content-length", 0))
        
        # Ensure parent directory exists
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Download with progress
        downloaded = 0
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size and total_size > 0:
                        percent = (downloaded / total_size) * 100
                        if int(percent) % 10 == 0:
                            print(f"\r    Downloading: {percent:.1f}%", end="", flush=True)
        
        if total_size:
            print(f"\r    Downloaded {file_type}: {dest_path.name} ({downloaded/1024/1024:.1f} MB)    ")
        else:
            print(f"\r    Downloaded {file_type}: {dest_path.name} ({downloaded/1024/1024:.1f} MB)    ")
        
        return dest_path
        
    except requests.exceptions.RequestException as e:
        print(f"    ✗ Download failed: {e}")
        if dest_path and dest_path.exists():
            dest_path.unlink()
        return None


def get_media_type_from_url(url: str) -> tuple[str, str]:
    """
    Determine media type and folder from URL.
    Returns (folder_name, extension)
    folder: 'video' or 'audio'
    """
    url_lower = url.lower()
    
    # Video extensions (including webm)
    if url_lower.endswith('.webm'):
        return 'video', '.webm'
    if any(url_lower.endswith(ext) for ext in ['.mp4', '.mkv', '.avi', '.mov', '.m4v', '.wmv', '.flv']):
        return 'video', Path(url).suffix.lower()
    
    # Audio extensions (weba = audio webm)
    if url_lower.endswith('.weba'):
        return 'audio', '.weba'
    if any(url_lower.endswith(ext) for ext in ['.mp3', '.ogg', '.opus', '.m4a', '.aac', '.flac', '.wav']):
        return 'audio', Path(url).suffix.lower()
    
    # Default to audio for unknown
    return 'audio', '.mp3'


def resolve_media_path_persistent(entry, playlist_path, audio_session, audio_cache, video_cache):
    """
    Resolve media path with persistent caching.
    Priority: local_file > cached download > download from audio_url
    Returns: (path, source, was_cached)
    source: 'local', 'cached', 'downloaded', or 'missing'
    """
    local_file = entry.get("local_file")
    
    # 1. Check local file first (user-provided path)
    if local_file:
        lf = local_file.strip()
        if lf:
            p = Path(lf)
            if p.is_file():
                return p, "local", False
            script_dir = Path(__file__).resolve().parent
            pl_parent = Path(playlist_path).resolve().parent
            for base in (pl_parent, script_dir, Path.cwd()):
                cand = (base / lf).resolve()
                if cand.is_file():
                    return cand, "local", False
    
    # 2. Try to get from audio URL - check multiple possible field names
    audio_url = entry.get("audio_url") or entry.get("au") or entry.get("url")
    
    if not audio_url:
        audio_url = entry.get("media_url") or entry.get("audio")
    
    if audio_url:
        # Determine media type and correct cache folder
        media_type, ext = get_media_type_from_url(audio_url)
        
        # Choose the correct cache folder
        if media_type == 'video':
            cache_folder = video_cache
        else:
            cache_folder = audio_cache
        
        # Create consistent filename from URL hash
        url_hash = hashlib.md5(audio_url.encode()).hexdigest()[:16]
        cache_path = cache_folder / f"{url_hash}{ext}"
        
        # Also try to find by song ID
        song_id = entry.get("id", "") or entry.get("song_id", "")
        if song_id:
            alt_path = cache_folder / f"song_{song_id}{ext}"
            if alt_path.is_file() and not cache_path.is_file():
                cache_path = alt_path
        
        # If file exists in cache, use it
        if cache_path.is_file() and cache_path.stat().st_size > 1024:
            return cache_path, "cached", True
        
        # Otherwise download if we have a session
        if audio_session:
            downloaded = download_media_file(audio_url, cache_path, audio_session, media_type)
            if downloaded and downloaded.is_file():
                return downloaded, "downloaded", False
        else:
            print(f"    No session available to download {audio_url[:50]}...")
    
    return None, "missing", False


def media_kind(path: Path):
    if not path or not path.is_file():
        return "missing"
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    return "video"


def file_has_audio(path: Path) -> bool:
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return "audio" in (r.stdout or "").lower()
    except Exception:
        return False


def ffmpeg(args, verbose):
    cmd = ["ffmpeg", "-nostdin", "-hide_banner"] + ([] if verbose else ["-loglevel", "error"]) + args
    r = subprocess.run(cmd, capture_output=not verbose)
    if r.returncode != 0 and not verbose:
        print(f"\n  FFmpeg error:\n{r.stderr.decode(errors='replace')}")
    return r.returncode == 0


def check_ffmpeg():
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True)
        if r.returncode == 0:
            print("  FFmpeg: " + r.stdout.decode().split("\n")[0])
            return True
    except FileNotFoundError:
        pass
    print("ERROR: ffmpeg not found.")
    return False


def make_clip_composite(
    media_path,
    overlay_path,
    clip_path,
    dur,
    start,
    fps,
    crf,
    preset,
    verbose,
    W,
    H,
    vx,
    vy,
    vw,
    vh,
    is_video,
    aspect_mode,
    prog_x,
    prog_y,
    prog_w,
    prog_h,
    media_has_audio=True,
    hero_rgb=None,
):
    px, py, pw, ph = int(prog_x), int(prog_y), int(prog_w), max(2, int(prog_h))
    td = float(dur)
    w_expr = f"{pw}-{pw}*t/{td}"

    if is_video:
        if aspect_mode == "stretch":
            scale_chain = f"[0:v]scale={vw}:{vh}:flags=lanczos,setsar=1[vs]"
        else:
            scale_chain = (
                f"[0:v]split=2[vbg_in][vfg_in];"
                f"[vbg_in]scale={vw}:{vh}:force_original_aspect_ratio=increase:flags=fast_bilinear,crop={vw}:{vh},boxblur=20:4,colorchannelmixer=rr=0.85:gg=0.85:bb=0.85[vbg];"
                f"[vfg_in]scale={vw}:{vh}:force_original_aspect_ratio=decrease:flags=lanczos[vfg];"
                f"[vbg][vfg]overlay=(W-w)/2:(H-h)/2,setsar=1[vs]"
            )
        fc = (
            f"color=c=0x0a0d12:s={W}x{H}:d={td}:r={fps},format=rgba[bg];"
            f"{scale_chain};"
            f"[bg][vs]overlay=x={vx}:y={vy}:format=auto[vm];"
            f"[1:v]format=rgba[ov];"
            f"[vm][ov]overlay=0:0:format=auto[v1]"
        )
    else:
        fc = (
            f"color=c=0x0a0d12:s={W}x{H}:d={td}:r={fps},format=rgba[bg];"
            f"[1:v]format=rgba[ov];"
            f"[bg][ov]overlay=0:0:format=auto[v1]"
        )

    # Progress bar color: use hero color if available, else default cyan
    if hero_rgb:
        pb_hex = "0x{:02x}{:02x}{:02x}".format(*hero_rgb)
    else:
        pb_hex = "0x8b5cf6"  # violet fallback

    fc += (
        f";color=c={pb_hex}@0.92:s={pw}x{ph}:d={td}:r={fps},format=rgba[emq_pb0];"
        f"[emq_pb0]scale=w={w_expr}:h={ph}:flags=fast_bilinear:eval=frame[emq_pb1];"
        f"[v1][emq_pb1]overlay=x={px}:y={py}:format=auto[vout]"
    )
    vmap = "[vout]"

    args_ = [
        "-y",
        "-threads",
        "0",
    ]
    args_ += ["-ss", str(start), "-t", str(dur), "-i", str(media_path)]

    args_ += [
        "-loop",
        "1",
        "-framerate",
        str(fps),
        "-i",
        overlay_path,
    ]

    if media_has_audio:
        a_map = ["-map", "0:a"]
    else:
        args_ += [
            "-f",
            "lavfi",
            "-t",
            str(dur),
            "-i",
            "anullsrc=r=44100:cl=stereo",
        ]
        fc += ";[2:a]aresample=44100,aformat=channel_layouts=stereo:sample_fmts=fltp[as]"
        a_map = ["-map", "[as]"]

    args_ += [
        "-filter_complex",
        fc,
        "-map",
        vmap,
        *a_map,
    ]

    args_ += [
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-t",
        str(dur),
        clip_path,
    ]

    return ffmpeg(args_, verbose)


def make_silent_clip_composite(
    overlay_path, clip_path, dur, fps, crf, preset, verbose, W, H, prog_x, prog_y, prog_w, prog_h,
    hero_rgb=None,
):
    px, py, pw, ph = int(prog_x), int(prog_y), int(prog_w), max(2, int(prog_h))
    td = float(dur)
    w_expr = f"{pw}-{pw}*t/{td}"
    pb_hex = "0x{:02x}{:02x}{:02x}".format(*hero_rgb) if hero_rgb else "0x8b5cf6"
    fc = (
        f"color=c=0x0a0d12:s={W}x{H}:d={td}:r={fps},format=rgba[bg];"
        f"[1:v]format=rgba[ov];"
        f"[bg][ov]overlay=0:0:format=auto[v1];"
        f"color=c={pb_hex}@0.92:s={pw}x{ph}:d={td}:r={fps},format=rgba[emq_pb0];"
        f"[emq_pb0]scale=w={w_expr}:h={ph}:flags=fast_bilinear:eval=frame[emq_pb1];"
        f"[v1][emq_pb1]overlay=x={px}:y={py}:format=auto[vout]"
    )
    vmap = "[vout]"

    return ffmpeg(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=44100:cl=stereo:d={dur}",
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-i",
            overlay_path,
            "-filter_complex",
            fc,
            "-map",
            vmap,
            "-map",
            "0:a",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-t",
            str(dur),
            clip_path,
        ],
        verbose,
    )


def concat_cuts(clips, filelist, out, verbose):
    with open(filelist, "w") as f:
        for p in clips:
            f.write(f"file '{os.path.abspath(p)}'\n")
    return ffmpeg(["-y", "-f", "concat", "-safe", "0", "-i", filelist, "-c", "copy", out], verbose)


def concat_xfade(clips, durations, trans, out, verbose):
    if len(clips) == 1:
        shutil.copy2(clips[0], out)
        return True
    inputs = []
    for c in clips:
        inputs += ["-i", c]
    fv, fa, offset = "0:v", "0:a", 0.0
    parts = []
    for i in range(len(clips) - 1):
        offset += durations[i] - trans
        nv, na = f"{i+1}:v", f"{i+1}:a"
        tv, ta = f"v{i+1}", f"a{i+1}"
        parts.append(
            f"[{fv}][{nv}]xfade=transition=fade:duration={trans:.3f}:offset={max(0, offset):.3f}[{tv}]"
        )
        parts.append(f"[{fa}][{na}]acrossfade=d={trans:.3f}[{ta}]")
        fv, fa = tv, ta
    return ffmpeg(
        [
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(parts),
            "-map",
            f"[{fv}]",
            "-map",
            f"[{fa}]",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "24",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            out,
        ],
        verbose,
    )


def default_playlist_path():
    """Return default playlist.json path if it exists"""
    if Path("playlist.json").exists():
        return "playlist.json"
    return None


def default_cookies_path():
    """Return default cookies.json path if it exists"""
    if Path("cookies.json").exists():
        return "cookies.json"
    return None


def merge_party_scores(playlist_path: str, score_files: list[str]) -> dict:
    """
    Merge multiple party scores.json files into a reordered playlist.
    Scores are averaged across participants; ties broken by lowest song ID.
    playlist_path may be a playlist.json or a party_template.json (superset).
    Returns a modified playlist dict ready for rendering.
    """
    with open(playlist_path, encoding="utf-8") as f:
        pl = json.load(f)

    entries = pl.get("entries", [])
    if not entries:
        sys.exit("ERROR: Playlist has no entries")

    # Build id → entry map
    entry_map = {str(e["id"]): e for e in entries}

    # Accumulate scores per song id, also store avatar per participant
    score_acc: dict[str, list[float]] = {sid: [] for sid in entry_map}
    participants = []       # list of {name, avatar_b64}
    participant_scores = [] # list of {sid: score} per participant

    for sf in score_files:
        with open(sf, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("type") != "party_scores":
            print(f"  WARNING: {sf} is not a party_scores file, skipping")
            continue
        name = data.get("participant", Path(sf).stem)
        avatar_b64 = data.get("avatar") or ""
        participants.append({"name": name, "avatar_b64": avatar_b64})
        sc_map = {str(item.get("id", "")): float(item.get("score", 0))
                  for item in data.get("scores", [])}
        participant_scores.append(sc_map)
        for sid, sc in sc_map.items():
            if sid in score_acc:
                score_acc[sid].append(sc)

    if not participants:
        sys.exit("ERROR: No valid party_scores files found")

    print(f"\n  Party merge: {len(participants)} participant(s): {', '.join(p['name'] for p in participants)}")

    # Compute averages and sort descending (highest avg = rank 1)
    def avg_score(sid):
        vals = score_acc[sid]
        return sum(vals) / len(vals) if vals else 0.0

    sorted_ids = sorted(entry_map.keys(), key=lambda sid: (avg_score(sid), int(sid)))

    total = len(sorted_ids)

    # Rebuild entries: array order = playback order (worst first, best last)
    # rank displayed on screen: first clip = #total (worst), last clip = #1 (best)
    ranked_entries = []
    for playback_pos, sid in enumerate(sorted_ids, 1):
        e = dict(entry_map[sid])
        avg = avg_score(sid)
        display_rank = total - playback_pos + 1
        e["rank"] = display_rank
        e["video_rank"] = playback_pos
        e["party_avg_score"] = round(avg, 2)
        # Per-participant scores for this song (used by renderer)
        e["party_participants_data"] = [
            {"name": p["name"], "avatar_b64": p["avatar_b64"],
             "score": sc_map.get(sid, 0)}
            for p, sc_map in zip(participants, participant_scores)
        ]
        ranked_entries.append(e)
        print(f"    video #{playback_pos:>3} (display #{display_rank})  avg={avg:.1f}  {e.get('title','?')}")

    # Party rank always plays rank 1 → rank N (worst to best reveal)
    pl["entries"] = ranked_entries
    pl["settings"]["direction"] = "desc"
    pl["party_participants"] = [p["name"] for p in participants]
    return pl


def main():
    # First, check if no arguments were provided
    no_args = len(sys.argv) == 1
    
    ap = argparse.ArgumentParser(
        description="EMQ Ranking Builder — Video Renderer (with auth)",
        usage="python render_video.py [playlist.json] [options]"
    )
    ap.add_argument("playlist", nargs="?", default=None,
                    help="Playlist JSON file (default: playlist.json if exists)")
    ap.add_argument("--scores", nargs="+", metavar="scores.json",
                    help="Party scores files to merge (e.g. --scores alice.json bob.json)")
    ap.add_argument("--out", default="ranking.mp4",
                    help="Output video file (default: ranking.mp4)")
    ap.add_argument("--transition", default=None, type=float,
                    help="Crossfade duration in seconds")
    ap.add_argument("--fps", default=None, type=int,
                    help="Frames per second (default: from playlist or 30)")
    ap.add_argument("--width", default=None, type=int,
                    help="Output width (default: from playlist or 1920)")
    ap.add_argument("--height", default=None, type=int,
                    help="Output height (default: from playlist or 1080)")
    ap.add_argument("--crf", default=24, type=int,
                    help="CRF quality (default: 18)")
    ap.add_argument("--preset", default="slow",
                    choices=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "veryslow"],
                    help="Encoding preset (default: slow)")
    ap.add_argument("--font", default=None,
                    help="Path to custom Latin font")
    ap.add_argument("--font-jp", default=None,
                    help="Path to custom Japanese font")
    ap.add_argument("--work-dir", default="emq_work",
                    help="Working directory for temporary files (default: emq_work)")
    ap.add_argument("--keep-clips", action="store_true",
                    help="Keep temporary clip files after rendering")
    ap.add_argument("--force-render", action="store_true",
                    help="Force re-rendering of all clips (ignore existing clip files)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Verbose output")
    
    # Authentication arguments
    ap.add_argument("--cookies", default=None,
                    help="Path to cookies.json file (default: cookies.json if exists)")
    ap.add_argument("--token", default=None,
                    help="Bearer token for authentication")
    ap.add_argument("--no-download", action="store_true",
                    help="Skip downloading audio files, use local only")
    
    # If no arguments, set defaults for playlist and cookies
    if no_args:
        sys.argv.append("--cookies")
        sys.argv.append(default_cookies_path() if default_cookies_path() else "")
        # We'll handle missing files gracefully
    
    args = ap.parse_args()
    
    # Set default playlist if not provided and exists
    if not args.playlist and default_playlist_path():
        args.playlist = "playlist.json"
        print(f"  Using default playlist: {args.playlist}")
    
    # Set default cookies if not provided and exists
    if not args.cookies and default_cookies_path() and not args.token:
        args.cookies = "cookies.json"
        print(f"  Using default cookies: {args.cookies}")
    
    # Validate required files
    if not args.playlist:
        sys.exit("ERROR: No playlist file specified and playlist.json not found")
    
    if not Path(args.playlist).exists():
        sys.exit(f"ERROR: Playlist file not found: {args.playlist}")
    
    if not args.no_download and not args.cookies and not args.token:
        print("  WARNING: No authentication provided (--cookies or --token)")
        print("  Audio downloads may fail. Use --cookies cookies.json if needed.")
    
    # skip_existing is True by default, False only if --force-render is specified
    skip_existing = not args.force_render

    print(f"\n{'='*60}\n  EMQ Ranking Builder — Video Renderer\n{'='*60}\n")
    
    if skip_existing:
        print("  Mode: SKIP EXISTING (use --force-render to re-render all clips)")
    else:
        print("  Mode: FORCE RENDER (re-rendering all clips)")
    print()

    if not check_ffmpeg():
        sys.exit(1)

    pl_path = Path(args.playlist)
    with open(pl_path, encoding="utf-8") as f:
        pl = json.load(f)

    # Party scores merge — always force re-render since overlay changes per song
    if args.scores:
        for sf in args.scores:
            if not Path(sf).exists():
                sys.exit(f"ERROR: Scores file not found: {sf}")
        print(f"\n  Party mode: merging {len(args.scores)} score file(s)…")
        pl = merge_party_scores(args.playlist, args.scores)
        skip_existing = False   # always re-render party clips
        print("  Party mode: clip cache disabled (overlays are per-song)")

    entries = pl.get("entries", [])
    if not entries:
        sys.exit("ERROR: Playlist has no entries")

    cfg = pl.get("settings", {})
    W = args.width or cfg.get("width", 1920)
    H = args.height or cfg.get("height", 1080)
    fps = args.fps or cfg.get("fps", 30)
    trans = args.transition if args.transition is not None else cfg.get("transition", 0.5)
    aspect_mode = (cfg.get("video_aspect_mode") or cfg.get("video_43_aspect") or "letterbox").lower()
    if aspect_mode not in ("letterbox", "stretch"):
        aspect_mode = "letterbox"

    L = layout_rects(W, H)

    total = sum(e.get("duration", 30) for e in entries)
    m, s = divmod(int(total), 60)
    print(f"  Playlist:   {pl_path.name}  ({len(entries)} songs)")
    print(f"  Output:     {args.out}")
    print(f"  Size:       {W}x{H} @ {fps}fps")
    print(f"  Non-16:9 video: {aspect_mode}")
    print(f"  Duration:   ~{m}m {s}s")
    print(f"  Transition: {trans}s crossfade" if trans else "  Transition: hard cuts")
    print(f"  CRF:        {args.crf}")
    print(f"  Preset:     {args.preset}")

    print("\n  Fonts:")
    fonts = load_fonts(args, W, H)
    
    # Setup authentication
    audio_session = None
    if not args.no_download:
        print("\n  Authentication:")
        audio_session = load_auth_session(args.cookies, args.token)
        if not audio_session.cookies and not args.token:
            print("    No authentication provided. Audio downloads may fail.")
            print("    Use --cookies cookies.json to enable authenticated downloads.")
    else:
        print("\n  Audio downloads disabled (--no-download)")

    # Create persistent directories (media folder is permanent)
    work = Path(args.work_dir)
    frames = work / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    covers = work / "covers"
    covers.mkdir(exist_ok=True)
    
    # MEDIA folder - persistent, never deleted
    media_folder = Path("media")
    media_folder.mkdir(exist_ok=True)
    
    # Audio cache inside media folder (for downloaded files)
    audio_cache = media_folder / "audio"
    audio_cache.mkdir(exist_ok=True)
    
    # Video cache inside media folder (for any video files we might download)
    video_cache = media_folder / "video"
    video_cache.mkdir(exist_ok=True)
    
    # Temporary work files (can be deleted)
    clips_dir = work / "clips"
    clips_dir.mkdir(exist_ok=True)

    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 EMQ-Ranking-Builder/5"

    print(f"\n{'─'*60}\n  Processing {len(entries)} songs\n{'─'*60}")
    print(f"  Media files will be stored in: {media_folder.absolute()}")
    print(f"  These files are PERSISTENT and will NOT be deleted.")
    print(f"  Clip caching: {'ENABLED (use --force-render to disable)' if skip_existing else 'DISABLED (re-rendering all)'}")
    print(f"{'─'*60}\n")

    clip_paths, durations = [], []
    no_audio = downloaded_count = used_cached_count = skipped_clips_count = 0

    import threading
    import concurrent.futures
    print_lock = threading.Lock()

    def process_song(i, entry):
        rank = entry.get("rank", i + 1)
        title = entry.get("title", "?")
        logs = [f"\n  [{i+1:>3}/{len(entries)}] #{rank} — {title}"]
        clip_path = str(clips_dir / f"{rank:04d}.mp4")
        
        is_party_clip = bool(entry.get("party_participants_data"))
        if skip_existing and not is_party_clip and os.path.isfile(clip_path) and os.path.getsize(clip_path) > 4096:
            logs.append("    ✓ clip exists, skipping (use --force-render to re-render)")
            return (i, clip_path, float(entry.get("duration", 30)), True, logs, "skipped")

        cover_img = None
        cover_url = entry.get("cover_url")
        cv_dest = str(covers / f"{rank:04d}.jpg")
        if cover_url:
            cover_img = download_cover(cover_url, cv_dest, sess)
            status = f"✓ {cover_img.width}x{cover_img.height}" if cover_img else "✗ download failed"
            logs.append(f"    Cover:  {status}")
        else:
            logs.append("    Cover:  none")

        media_path, media_source, _ = resolve_media_path_persistent(
            entry, pl_path, audio_session, audio_cache, video_cache
        )
        
        m_stat = "missing"
        if media_source == "downloaded":
            m_stat = "downloaded"
            logs.append(f"    Media:  ✓ downloaded: {media_path.name}")
        elif media_source == "cached":
            m_stat = "cached"
            logs.append(f"    Media:  ✓ from cache: {media_path.name}")
        elif media_source == "local":
            m_stat = "local"
            logs.append(f"    Media:  ✓ local: {media_path.name}")
        else:
            logs.append(f"    Media:  ✗ not available")

        overlay_path = str(frames / f"{rank:04d}.png")
        is_video = media_path and media_kind(media_path) == "video"
        party_pd = entry.get("party_participants_data") or None
        hero_rgb = sample_dominant_color(cover_img)

        def render_ov(hole, _pd=party_pd):
            render_overlay(entry, cover_img, fonts, W, H, overlay_path,
                           has_video_window=hole, participants_data=_pd)

        logs.append("    Overlay: rendering…")
        try:
            render_ov(is_video)
        except Exception as e:
            logs.append(f"    ✗ overlay error: {e}")
            return (i, clip_path, 0, False, logs, m_stat)

        dur = float(entry.get("duration", 30))
        start = float(entry.get("start_time", 0))

        if media_path and media_path.is_file():
            has_aud = file_has_audio(media_path)
            ok = make_clip_composite(
                str(media_path), overlay_path, clip_path, dur, start, fps,
                args.crf, args.preset, args.verbose, W, H, L["vx"], L["vy"],
                L["vw"], L["vh"], is_video, aspect_mode, L["prog_x"], L["prog_y"],
                L["prog_w"], L["prog_h"], media_has_audio=has_aud, hero_rgb=hero_rgb,
            )
            if not ok and is_video:
                logs.append("    ⚠ Retrying as audio-only (no video decode)…")
                try:
                    render_ov(False)
                    ok = make_clip_composite(
                        str(media_path), overlay_path, clip_path, dur, start, fps,
                        args.crf, args.preset, args.verbose, W, H, L["vx"], L["vy"],
                        L["vw"], L["vh"], False, aspect_mode, L["prog_x"], L["prog_y"],
                        L["prog_w"], L["prog_h"], media_has_audio=has_aud,
                    )
                except Exception:
                    ok = False
        else:
            logs.append("    Media:  ─ no media file → silence")
            ok = make_silent_clip_composite(
                overlay_path, clip_path, dur, fps, args.crf, args.preset, args.verbose, W, H,
                L["prog_x"], L["prog_y"], L["prog_w"], L["prog_h"], hero_rgb=hero_rgb,
            )

        logs.append("    Clip:   ✓" if ok else "    Clip:   ✗ FFmpeg failed")
        return (i, clip_path, dur, ok, logs, m_stat)

    results = [None] * len(entries)
    # Use 3 workers to maintain reasonable system load on FFmpeg encode
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        worker_futures = [executor.submit(process_song, i, e) for i, e in enumerate(entries)]
        for future in worker_futures:
            i, cp, dur, ok, logs, m_stat = future.result()
            print("\n".join(logs))
            if m_stat == "skipped": skipped_clips_count += 1
            elif m_stat == "downloaded": downloaded_count += 1
            elif m_stat == "cached": used_cached_count += 1
            elif m_stat == "missing": no_audio += 1
            results[i] = (cp, dur, ok)

    for res in results:
        if res and res[2]:
            clip_paths.append(res[0])
            durations.append(res[1])

    if not clip_paths:
        sys.exit("\nERROR: No clips generated successfully.")

    # Print statistics
    print(f"\n{'─'*60}")
    print(f"  Statistics:")
    if skipped_clips_count:
        print(f"    Skipped (cached clips): {skipped_clips_count}")
    if downloaded_count:
        print(f"    New downloads: {downloaded_count} to media/")
    if used_cached_count:
        print(f"    Used from cache: {used_cached_count} media file(s)")
    if no_audio:
        print(f"    Missing media: {no_audio} song(s)")
    print(f"    Total clips: {len(clip_paths)}")
    print(f"{'─'*60}\n")

    print(f"\n{'─'*60}\n  Concatenating {len(clip_paths)} clips → {args.out}\n{'─'*60}")

    if trans > 0 and len(clip_paths) > 1:
        ok = concat_xfade(clip_paths, durations, trans, args.out, args.verbose)
    else:
        filelist = str(work / "filelist.txt")
        ok = concat_cuts(clip_paths, filelist, args.out, args.verbose)

    if ok and os.path.isfile(args.out):
        size_mb = os.path.getsize(args.out) / 1024 / 1024
        print(f"\n{'='*60}\n  ✓  {args.out}  ({size_mb:.1f} MB)")
        print(f"\n  Media files are saved in 'media/' folder (persistent).")
        print(f"  Clip cache is in '{work}/clips/'")
        if skip_existing:
            print(f"\n  To re-render all clips from scratch, use: --force-render")
        print(f"{'='*60}\n")
    else:
        sys.exit("\n  ✗ Concatenation failed.")

    if not args.keep_clips:
        shutil.rmtree(str(work), ignore_errors=True)
        print(f"  Removed temporary work folder: {work}")
        print(f"  Media folder 'media/' was preserved.\n")


if __name__ == "__main__":
    main()