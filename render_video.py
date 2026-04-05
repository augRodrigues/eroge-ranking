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
UI_CYAN = (45, 180, 230, 255)
UI_CYAN_DIM = (45, 180, 230, 160)
UI_BLUE_GLOW = (55, 140, 220, 200)
LABEL_GREY = (130, 138, 160, 255)
TITLE_WHITE = (248, 250, 255, 255)
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
        title=lf(max(32, min(64, H // 16))),
        jp=jf(max(18, H // 46)),
        badge=lf(max(12, H // 72)),
        game=lf(max(15, H // 56)),
        role_lbl=lf(max(11, H // 84)),
        role_nm=lf(max(13, H // 72)),
        rank_big=lf(max(40, H // 24)),
        bar_title=lf(max(24, H // 22)),
        bar_cal=lf(max(15, H // 62)),
        sound=lf(max(34, H // 15)),
        type_badge=lf(max(20, H // 38)),
        lat_path=lat_path,
        jp_path=jp_path,
    )


def wrap_text_centered(draw, text, font, cx, y, max_w, line_h, fill, max_lines=3):
    if not text:
        return 0
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
    gap_prog_bar = max(7, int(H * 0.012))

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
    bar_x0 = left_x0

    rx0 = W - rw - margin + max(4, int(rw * 0.05))
    rx1 = W - margin - max(4, int(rw * 0.05))
    panel_w = rx1 - rx0
    bar_w = max(120, rx0 - bar_x0 - 12)

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
                segs.append((", ", TITLE_WHITE))
            segs.append((letter, colors[letter]))
        segs.append((" " + nm, TITLE_WHITE))
        blocks.append(segs)
    flat = []
    sep = (180, 188, 210, 255)
    for bi, block in enumerate(blocks):
        if bi:
            flat.append((" / ", sep))
        flat.extend(block)
    return flat


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


def render_overlay(entry, cover_img, fonts, W, H, out_path, has_video_window):
    L = layout_rects(W, H)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    base_bg = (8, 11, 22, 255)
    draw.rectangle([0, 0, W, H], fill=base_bg)

    if cover_img:
        sc = max(W / cover_img.width, H / cover_img.height) * 1.06
        bw, bh = int(cover_img.width * sc), int(cover_img.height * sc)
        bg = cover_img.resize((bw, bh), Image.LANCZOS)
        bg = bg.crop(((bw - W) // 2, (bh - H) // 2, (bw - W) // 2 + W, (bh - H) // 2 + H))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=W // 48))
        bg = ImageEnhance.Brightness(bg).enhance(0.12)
        bg = ImageEnhance.Color(bg).enhance(1.15)
        canvas.paste(bg.convert("RGBA"), (0, 0))

    vign = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vign)
    for y in range(H):
        t = y / max(H - 1, 1)
        a = int(100 * (0.2 + 0.8 * t))
        vd.line([(0, y), (W, y)], fill=(6, 18, 40, a))
    canvas = Image.alpha_composite(canvas, vign)

    draw = ImageDraw.Draw(canvas)
    tp_id = entry.get("song_type_id", 0)
    accent = hex_rgb(TYPE_COLOR.get(tp_id, "#6ba4f5"))
    bar_outline = (*UI_BLUE_GLOW[:3], 195)

    inset = max(6, L["margin"] // 2)
    _draw_corner_brackets(draw, (inset, inset, W - inset, H - inset), (200, 215, 235, 85), 2, 22)
    dsz = 3
    for mx in (inset + 36, W // 2, W - inset - 36):
        draw.polygon(
            [(mx - dsz, inset), (mx + dsz, inset), (mx, inset + dsz + 2)],
            fill=(120, 180, 220, 70),
        )

    vx, vy, vw, vh = L["vx"], L["vy"], L["vw"], L["vh"]
    fx0 = vx - FRAME_PAD
    fy0 = vy - FRAME_PAD
    fx1 = vx + vw + FRAME_PAD
    fy1 = vy + vh + FRAME_PAD
    draw.rounded_rectangle([fx0, fy0, fx1, fy1], radius=6, outline=bar_outline, width=2)
    _draw_corner_brackets(draw, (fx0, fy0, fx1, fy1), (*bar_outline[:3], 130), 2, 18)
    for i in range(0, vh, max(26, vh // 14)):
        draw.ellipse([fx0 - 7, vy + i, fx0 - 3, vy + i + 3], fill=(*bar_outline[:3], 95))

    if has_video_window:
        hole = Image.new("RGBA", (vw, vh), (0, 0, 0, 0))
        canvas.paste(hole, (vx, vy))
    else:
        draw_sound_panel(canvas, vx, vy, vw, vh, cover_img, accent, fonts)

    draw = ImageDraw.Draw(canvas)

    px, py, pww, ph = L["prog_x"], L["prog_y"], L["prog_w"], L["prog_h"]
    track_pad = 1
    draw.rounded_rectangle(
        [px - track_pad, py - track_pad, px + pww + track_pad, py + ph + track_pad],
        radius=3,
        fill=(18, 24, 38, 255),
        outline=(*bar_outline[:3], 80),
        width=1,
    )

    bx, by, bw, bh = L["bar_x0"], L["bar_y"], L["bar_w"], L["bar_h"]
    type_font = fonts["type_badge"]
    type_w = max(52, _text_width(type_font, "OTHER") + 14)
    bar_fill = (14, 17, 30, 245)
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=8, fill=bar_fill)
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=8, outline=bar_outline, width=2)
    draw.line([(bx + type_w, by + 6), (bx + type_w, by + bh - 6)], fill=(*bar_outline[:3], 90), width=1)

    st_abbr = TYPE_ABBR.get(tp_id, "OTHER")
    tb = type_font.getbbox(st_abbr)
    draw.text(
        (bx + type_w // 2, by + bh // 2 - (tb[3] - tb[1]) // 2),
        st_abbr,
        font=type_font,
        fill=(*accent[:3], 255),
        anchor="mm",
    )

    content_left = bx + type_w + 12
    content_right = bx + bw - 12
    credits_cx = (content_left + content_right) // 2
    credits_max_w = max(80, content_right - content_left)

    song_t = entry.get("title", "")
    artists = entry.get("artists", [])
    voc = ", ".join(a["name"] for a in artists if a.get("role_id") == 1)
    line1_core = f"{song_t} / {voc}" if voc else song_t
    fs = max(20, min(40, int(1200 / max(len(line1_core), 12))))
    try:
        tf = (
            ImageFont.truetype(fonts["lat_path"], fs)
            if fonts.get("lat_path")
            else fonts["bar_title"]
        )
    except Exception:
        tf = fonts["bar_title"]
    line1 = fit_text_width(tf, line1_core, credits_max_w)
    tbb = tf.getbbox(line1)
    title_h = tbb[3] - tbb[1]

    cal_font = fonts["bar_cal"]
    cal_segs = build_cal_segments(artists)
    w_line1 = _text_width(tf, line1)
    w_cal = segments_width(cal_font, cal_segs) if cal_segs else 0
    gap_title_cal = max(12, int(title_h * 0.42)) if cal_segs else 0
    try:
        cal_bb = cal_font.getbbox("Ag")
        cal_h = (cal_bb[3] - cal_bb[1] + 3) if cal_segs else 0
    except Exception:
        cal_h = 22 if cal_segs else 0
    block_h = title_h + gap_title_cal + cal_h
    y_block_top = by + max(0, (bh - block_h) // 2)

    x1 = credits_cx - w_line1 // 2
    draw.text((x1, y_block_top), line1, font=tf, fill=TITLE_WHITE)
    if cal_segs:
        x_cal = credits_cx - w_cal // 2
        y_cal = y_block_top + title_h + gap_title_cal
        draw_text_segments(draw, x_cal, y_cal, cal_segs, cal_font)

    rx0, rx1 = L["rx0"], L["rx1"]
    pw = rx1 - rx0
    pcx = (rx0 + rx1) // 2
    py0 = L["top_m"]
    draw.rounded_rectangle(
        [rx0 - 5, py0, rx1 + 5, H - L["margin"]],
        radius=10,
        fill=(10, 14, 28, 238),
    )
    _glow_line(draw, (rx0 - 5, py0 + 36), (rx0 - 5, H - L["margin"]), (*bar_outline[:3], 120), 2)

    rank = entry.get("rank", 0)
    rh = int(pw * 0.26)
    ry1 = py0 + rh
    rtxt = f"#{rank}"
    draw.text(
        (pcx, py0 + rh // 2),
        rtxt,
        font=fonts["rank_big"],
        fill=(235, 242, 255, 255),
        anchor="mm",
    )

    cov_top = ry1 + 12
    cov_max_h = int((H - L["margin"] - cov_top) * 0.48)
    cov_w, cov_h = pw - 10, cov_max_h
    cx0 = pcx - cov_w // 2
    if cover_img:
        sc2 = min(cov_w / cover_img.width, cov_h / cover_img.height)
        dw, dh = int(cover_img.width * sc2), int(cover_img.height * sc2)
        fit = cover_img.resize((dw, dh), Image.LANCZOS).convert("RGBA")
        panel = Image.new("RGBA", (cov_w, cov_h), (0, 0, 0, 0))
        ox, oy = (cov_w - dw) // 2, (cov_h - dh) // 2
        panel.paste(fit, (ox, oy))
        border = Image.new("RGBA", (cov_w, cov_h), (0, 0, 0, 0))
        bd = ImageDraw.Draw(border)
        bd.rounded_rectangle([0, 0, cov_w - 1, cov_h - 1], radius=6, outline=(*bar_outline[:3], 200), width=2)
        panel = Image.alpha_composite(panel, border)
        canvas.alpha_composite(panel, (cx0, cov_top))
    else:
        draw.rounded_rectangle(
            [cx0, cov_top, cx0 + cov_w, cov_top + cov_h],
            radius=6,
            outline=(*bar_outline[:3], 100),
            width=1,
        )
        draw.text(
            (cx0 + cov_w // 2, cov_top + cov_h // 2),
            "No cover",
            font=fonts["badge"],
            fill=(120, 130, 160, 255),
            anchor="mm",
        )

    draw = ImageDraw.Draw(canvas)
    meta_y = cov_top + cov_h + 14
    vn_ro = (entry.get("vn_romaji") or entry.get("game") or "").strip()
    vn_jp = (entry.get("vn_title_jp") or entry.get("game_jp") or "").strip()
    meta_max_w = max(40, pw - 8)

    draw_hcentered_line(draw, "<<TITLE>>", fonts["badge"], pcx, meta_y, LABEL_GREY)
    meta_y += 18
    if vn_ro:
        meta_y += wrap_text_centered(
            draw, vn_ro, fonts["game"], pcx, meta_y, meta_max_w, 28, TITLE_WHITE, max_lines=2
        )
        meta_y += 6
    if vn_jp and vn_jp != vn_ro:
        jf = fonts["jp"]
        meta_y += wrap_text_centered(
            draw, vn_jp, jf, pcx, meta_y, meta_max_w, 26, (210, 218, 235, 255), max_lines=2
        )
        meta_y += 8

    meta_y += 10
    draw_hcentered_line(draw, "<<DEVELOPER>>", fonts["badge"], pcx, meta_y, LABEL_GREY)
    meta_y += 18
    dev = (entry.get("vn_developers") or "").strip()
    if dev:
        meta_y += wrap_text_centered(
            draw, dev, fonts["role_nm"], pcx, meta_y, meta_max_w, 22, (220, 226, 240, 255), max_lines=3
        )
    else:
        meta_y += 16
    meta_y += 10
    draw_hcentered_line(draw, "<<RELEASE DATE>>", fonts["badge"], pcx, meta_y, LABEL_GREY)
    meta_y += 18
    rel = (entry.get("vn_released") or "").strip()
    if rel:
        draw_hcentered_line(draw, rel, fonts["role_nm"], pcx, meta_y, (220, 226, 240, 255))

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
    cmd = ["ffmpeg", "-hide_banner"] + ([] if verbose else ["-loglevel", "error"]) + args
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
):
    px, py, pw, ph = int(prog_x), int(prog_y), int(prog_w), max(2, int(prog_h))
    td = float(dur)
    w_expr = f"{pw}-{pw}*t/{td}"

    if is_video:
        if aspect_mode == "stretch":
            scale_chain = f"[0:v]scale={vw}:{vh}:flags=lanczos,setsar=1[vs]"
        else:
            scale_chain = (
                f"[0:v]scale={vw}:{vh}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2:color=0x050508,setsar=1[vs]"
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

    fc += (
        f";color=c=0x4db8e8@0.92:s={pw}x{ph}:d={td}:r={fps},format=rgba[emq_pb0];"
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
    overlay_path, clip_path, dur, fps, crf, preset, verbose, W, H, prog_x, prog_y, prog_w, prog_h
):
    px, py, pw, ph = int(prog_x), int(prog_y), int(prog_w), max(2, int(prog_h))
    td = float(dur)
    w_expr = f"{pw}-{pw}*t/{td}"
    fc = (
        f"color=c=0x0a0d12:s={W}x{H}:d={td}:r={fps},format=rgba[bg];"
        f"[1:v]format=rgba[ov];"
        f"[bg][ov]overlay=0:0:format=auto[v1];"
        f"color=c=0x4db8e8@0.92:s={pw}x{ph}:d={td}:r={fps},format=rgba[emq_pb0];"
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


def main():
    # First, check if no arguments were provided
    no_args = len(sys.argv) == 1
    
    ap = argparse.ArgumentParser(
        description="EMQ Ranking Builder — Video Renderer (with auth)",
        usage="python render_video.py [playlist.json] [options]"
    )
    ap.add_argument("playlist", nargs="?", default=None,
                    help="Playlist JSON file (default: playlist.json if exists)")
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
    no_audio = 0
    downloaded_count = 0
    used_cached_count = 0
    skipped_clips_count = 0

    for i, entry in enumerate(entries):
        rank = entry.get("rank", i + 1)
        title = entry.get("title", "?")
        print(f"\n  [{i+1:>3}/{len(entries)}] #{rank} — {title}")

        clip_path = str(clips_dir / f"{rank:04d}.mp4")
        
        # Check if clip exists and we should skip it (default behavior)
        if skip_existing and os.path.isfile(clip_path) and os.path.getsize(clip_path) > 4096:
            print("    ✓ clip exists, skipping (use --force-render to re-render)")
            clip_paths.append(clip_path)
            durations.append(float(entry.get("duration", 30)))
            skipped_clips_count += 1
            continue

        cover_img = None
        cover_url = entry.get("cover_url")
        cv_dest = str(covers / f"{rank:04d}.jpg")
        if cover_url:
            cover_img = download_cover(cover_url, cv_dest, sess)
            status = f"✓ {cover_img.width}x{cover_img.height}" if cover_img else "✗ download failed"
            print(f"    Cover:  {status}")
        else:
            print("    Cover:  none")

        # Resolve media path with persistent caching
        media_path, media_source, was_cached = resolve_media_path_persistent(
            entry, pl_path, audio_session, audio_cache, video_cache
        )
        
        if media_source == "downloaded":
            downloaded_count += 1
            print(f"    Media:  ✓ downloaded: {media_path.name}")
        elif media_source == "cached":
            used_cached_count += 1
            print(f"    Media:  ✓ from cache: {media_path.name}")
        elif media_source == "local":
            print(f"    Media:  ✓ local: {media_path.name}")
        else:
            print(f"    Media:  ✗ not available")
            no_audio += 1

        overlay_path = str(frames / f"{rank:04d}.png")
        is_video = media_path and media_kind(media_path) == "video"

        def render_ov(hole):
            render_overlay(entry, cover_img, fonts, W, H, overlay_path, has_video_window=hole)

        print("    Overlay: rendering…", end="", flush=True)
        try:
            render_ov(is_video)
            print(" ✓")
        except Exception as e:
            print(f" ✗ {e}")
            import traceback
            traceback.print_exc()
            continue

        dur = float(entry.get("duration", 30))
        start = float(entry.get("start_time", 0))

        if media_path and media_path.is_file():
            has_aud = file_has_audio(media_path)
            ok = make_clip_composite(
                str(media_path),
                overlay_path,
                clip_path,
                dur,
                start,
                fps,
                args.crf,
                args.preset,
                args.verbose,
                W,
                H,
                L["vx"],
                L["vy"],
                L["vw"],
                L["vh"],
                is_video,
                aspect_mode,
                L["prog_x"],
                L["prog_y"],
                L["prog_w"],
                L["prog_h"],
                media_has_audio=has_aud,
            )
            if not ok and is_video:
                print("    ⚠ Retrying as audio-only (no video decode)…")
                try:
                    render_ov(False)
                except Exception as e:
                    print(f"    ✗ overlay re-render: {e}")
                    ok = False
                else:
                    ok = make_clip_composite(
                        str(media_path),
                        overlay_path,
                        clip_path,
                        dur,
                        start,
                        fps,
                        args.crf,
                        args.preset,
                        args.verbose,
                        W,
                        H,
                        L["vx"],
                        L["vy"],
                        L["vw"],
                        L["vh"],
                        False,
                        aspect_mode,
                        L["prog_x"],
                        L["prog_y"],
                        L["prog_w"],
                        L["prog_h"],
                        media_has_audio=has_aud,
                    )
        else:
            print("    Media:  ─ no media file → silence")
            ok = make_silent_clip_composite(
                overlay_path,
                clip_path,
                dur,
                fps,
                args.crf,
                args.preset,
                args.verbose,
                W,
                H,
                L["prog_x"],
                L["prog_y"],
                L["prog_w"],
                L["prog_h"],
            )

        if ok:
            clip_paths.append(clip_path)
            durations.append(dur)
            print("    Clip:   ✓")
        else:
            print("    Clip:   ✗ FFmpeg failed")

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