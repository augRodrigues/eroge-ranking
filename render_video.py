#!/usr/bin/env python3
"""
EMQ Ranking Builder — Video Renderer
====================================
Reads playlist.json (exported from the browser app), downloads VNDB cover art,
renders a futuristic UI overlay (Pillow), and composites local video/audio with FFmpeg.

Video files (webm, mp4, …) are scaled into a 16:9 main window; audio-only files
(mp3, ogg, …) show a “sound only” panel. Set `local_file` to a basename (same
folder as this script or the playlist) or an absolute path.

Requirements:
    pip install Pillow requests
    ffmpeg on PATH

Usage:
    python render_video.py playlist.json
    python render_video.py playlist.json --out ranking.mp4
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance
except ImportError:
    sys.exit("ERROR: Pillow not installed.  Run:  pip install Pillow requests")

try:
    import requests
except ImportError:
    sys.exit("ERROR: requests not installed.  Run:  pip install Pillow requests")


# ─── CONSTANTS ────────────────────────────────────────────────────────────────
TYPE_LABEL = {1: "Opening", 2: "Ending", 3: "Insert Song", 4: "BGM", 0: "Unknown"}
TYPE_COLOR = {1: "#e8c547", 2: "#3ecfac", 3: "#6ba4f5", 4: "#a48ef8", 0: "#7a7a98"}
ROLE_ORDER = [1, 6, 2, 5, 3, 4]
ROLE_LABEL = {
    1: "Vocals",
    2: "Music",
    3: "Performer",
    4: "Director",
    5: "Arrangement",
    6: "Lyrics",
}

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
        rank_big=lf(max(48, H // 22)),
        bar_title=lf(max(26, H // 20)),
        sound=lf(max(36, H // 14)),
        lat_path=lat_path,
        jp_path=jp_path,
    )


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
    """Main 16:9 video window (top-left column), right panel, bottom info bar."""
    margin = max(12, int(W * 0.018))
    rw = int(W * 0.235)
    left_w = W - rw - margin
    left_x0 = margin
    bh = max(int(H * 0.125), 110)
    top_m = max(10, int(H * 0.022))
    gap_v = max(8, int(H * 0.012))

    avail_h = H - top_m - bh - gap_v - margin
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
    bar_y = vy + vh + gap_v
    bar_h = H - bar_y - margin
    bar_h = min(bar_h, bh)
    bar_x0 = left_x0

    rx0 = W - rw - margin + int(rw * 0.06)
    rx1 = W - margin - int(rw * 0.06)
    panel_w = rx1 - rx0
    # Bottom bar only spans the left column (never under the right panel)
    bar_w = max(120, rx0 - bar_x0 - 12)

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
    )


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
    """
    Full-frame RGBA overlay. If has_video_window, the main 16:9 rect is fully transparent
    so FFmpeg can place scaled video underneath.
    """
    L = layout_rects(W, H)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Deep navy background (opaque everywhere except optional video hole)
    base_bg = (12, 14, 28, 255)
    draw.rectangle([0, 0, W, H], fill=base_bg)

    if cover_img:
        sc = max(W / cover_img.width, H / cover_img.height) * 1.08
        bw, bh = int(cover_img.width * sc), int(cover_img.height * sc)
        bg = cover_img.resize((bw, bh), Image.LANCZOS)
        bg = bg.crop(((bw - W) // 2, (bh - H) // 2, (bw - W) // 2 + W, (bh - H) // 2 + H))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=W // 50))
        bg = ImageEnhance.Brightness(bg).enhance(0.14)
        bg = ImageEnhance.Color(bg).enhance(1.35)
        canvas.paste(bg.convert("RGBA"), (0, 0))

    # Darken with cyan-tinted vignette
    vign = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vign)
    for y in range(H):
        t = y / max(H - 1, 1)
        a = int(120 * (0.25 + 0.75 * t))
        vd.line([(0, y), (W, y)], fill=(4, 12, 28, a))
    canvas = Image.alpha_composite(canvas, vign)

    draw = ImageDraw.Draw(canvas)
    tp_id = entry.get("song_type_id", 0)
    accent = hex_rgb(TYPE_COLOR.get(tp_id, "#00e8ff"))
    cyan = (0, 220, 255, 255)
    magenta = (255, 60, 180, 255)
    gold = (232, 197, 71, 255)

    # Outer HUD frame
    inset = max(6, L["margin"] // 2)
    _draw_corner_brackets(draw, (inset, inset, W - inset, H - inset), (255, 255, 255, 100), 2, 24)
    dsz = 4
    for mx in (inset + 40, W // 2, W - inset - 40):
        draw.polygon(
            [(mx - dsz, inset), (mx + dsz, inset), (mx, inset + dsz + 3)],
            fill=(255, 255, 255, 75),
        )

    # Left column: video frame decoration (visible border around hole area)
    vx, vy, vw, vh = L["vx"], L["vy"], L["vw"], L["vh"]
    frame_pad = 3
    fx0, fy0 = vx - frame_pad, vy - frame_pad
    fx1, fy1 = vx + vw + frame_pad, vy + vh + frame_pad
    draw.rounded_rectangle(
        [fx0, fy0, fx1, fy1],
        radius=6,
        outline=(*cyan[:3], 200),
        width=2,
    )
    _draw_corner_brackets(draw, (fx0, fy0, fx1, fy1), (*cyan[:3], 160), 2, 20)
    for i in range(0, vh, max(28, vh // 12)):
        draw.ellipse([fx0 - 8, vy + i, fx0 - 3, vy + i + 4], fill=(*cyan[:3], 120))

    # Punch transparent window for live video
    if has_video_window:
        hole = Image.new("RGBA", (vw, vh), (0, 0, 0, 0))
        canvas.paste(hole, (vx, vy))

    else:
        # Sound-only panel inside frame
        inner = Image.new("RGBA", (vw, vh), (8, 10, 22, 245))
        canvas.paste(inner, (vx, vy))
        sdraw = ImageDraw.Draw(canvas)
        grid_c = (40, 80, 120, 90)
        step = max(24, vw // 28)
        for gx in range(vx, vx + vw, step):
            sdraw.line([(gx, vy), (gx, vy + vh)], fill=grid_c, width=1)
        for gy in range(vy, vy + vh, step):
            sdraw.line([(vx, gy), (vx + vw, gy)], fill=grid_c, width=1)
        msg = "SOUND ONLY"
        bb = fonts["sound"].getbbox(msg)
        tw = bb[2] - bb[0]
        sdraw.text(
            (vx + (vw - tw) // 2, vy + vh // 2 - (bb[3] - bb[1]) // 2),
            msg,
            font=fonts["sound"],
            fill=(0, 240, 255, 220),
        )
        sdraw.text(
            (vx + vw // 2, vy + vh // 2 + (bb[3] - bb[1]) // 2 + 8),
            "Audio sample · no video",
            font=fonts["badge"],
            fill=(255, 255, 255, 140),
            anchor="mt",
        )

    draw = ImageDraw.Draw(canvas)

    # Bottom bar (song + credits) — under video column
    bx, by, bw, bh = L["bar_x0"], L["bar_y"], L["bar_w"], L["bar_h"]
    bar_fill = (16, 18, 32, 242)
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=8, fill=bar_fill)
    draw.rounded_rectangle(
        [bx, by, bx + bw, by + bh],
        radius=8,
        outline=(*gold[:3], 200),
        width=2,
    )
    # Timer ornament (left)
    tcx, tcy = bx + int(bh * 0.52), by + bh // 2
    tr = int(min(bh * 0.36, 46))
    draw.ellipse(
        [tcx - tr, tcy - tr, tcx + tr, tcy + tr],
        outline=(*cyan[:3], 220),
        width=2,
    )
    draw.ellipse(
        [tcx - tr + 5, tcy - tr + 5, tcx + tr - 5, tcy + tr - 5],
        outline=(*magenta[:3], 80),
        width=1,
    )

    timer_x = tcx + tr + 18
    credits_x0 = timer_x + 8
    credits_max_w = bx + bw - credits_x0 - 16

    title = entry.get("title", "")
    fs = max(22, min(48, int(1400 / max(len(title), 8))))
    try:
        tf = ImageFont.truetype(fonts["lat_path"], fs) if fonts.get("lat_path") else fonts["bar_title"]
    except Exception:
        tf = fonts["bar_title"]

    tbb = tf.getbbox(title)
    tx = credits_x0 + max(0, (credits_max_w - (tbb[2] - tbb[0])) // 2)
    draw.text((tx, by + 10), title, font=tf, fill=(248, 250, 255, 255))

    cy = by + 14 + int((tbb[3] - tbb[1]) * 1.15)
    artists = entry.get("artists", [])
    credit_parts = []
    for role_id in ROLE_ORDER:
        group = [a for a in artists if a.get("role_id") == role_id]
        if not group:
            continue
        names = ", ".join(a["name"] for a in group)
        credit_parts.append(f"{ROLE_LABEL.get(role_id, '?')}: {names}")
    credit_line = "  ·  ".join(credit_parts[:4]) if credit_parts else ""
    if credit_line:
        lh = 22
        try:
            bb0 = fonts["role_nm"].getbbox("Ag")
            lh = max(18, bb0[3] - bb0[1] + 4)
        except Exception:
            pass
        wrap_text(
            draw,
            credit_line,
            fonts["role_nm"],
            credits_x0,
            cy,
            credits_max_w,
            lh,
            (200, 210, 230, 230),
            max_lines=2,
        )

    # Right panel background strip
    rx0, rx1 = L["rx0"], L["rx1"]
    pw = rx1 - rx0
    py0 = L["top_m"]
    draw.rounded_rectangle(
        [rx0 - 6, py0, rx1 + 6, H - L["margin"]],
        radius=10,
        fill=(10, 12, 26, 230),
    )
    _glow_line(draw, (rx0 - 6, py0 + 40), (rx0 - 6, H - L["margin"]), (*cyan[:3], 180), 3)

    # Rank block (top right)
    rank = entry.get("rank", 0)
    rh = int(pw * 0.42)
    ry1 = py0 + rh
    draw.rounded_rectangle([rx0, py0, rx1, ry1], radius=8, fill=(*magenta[:3], 55))
    draw.rounded_rectangle(
        [rx0, py0, rx1, ry1],
        radius=8,
        outline=(*magenta[:3], 220),
        width=2,
    )
    rtxt = str(rank)
    draw.text(
        (rx0 + pw // 2, py0 + rh // 2 - 6),
        rtxt,
        font=fonts["rank_big"],
        fill=(255, 255, 255, 255),
        anchor="mm",
    )
    draw.text(
        (rx1 - 10, py0 + 14),
        "RANK",
        font=fonts["badge"],
        fill=(255, 255, 255, 160),
        anchor="rt",
    )

    # Cover art
    cov_top = ry1 + 14
    cov_max_h = int((H - L["margin"] - cov_top) * 0.52)
    cov_w, cov_h = pw - 8, cov_max_h
    cx0 = rx0 + 4
    if cover_img:
        sc2 = min(cov_w / cover_img.width, cov_h / cover_img.height)
        dw, dh = int(cover_img.width * sc2), int(cover_img.height * sc2)
        fit = cover_img.resize((dw, dh), Image.LANCZOS).convert("RGBA")
        panel = Image.new("RGBA", (cov_w, cov_h), (0, 0, 0, 0))
        ox, oy = (cov_w - dw) // 2, (cov_h - dh) // 2
        panel.paste(fit, (ox, oy))
        border = Image.new("RGBA", (cov_w, cov_h), (0, 0, 0, 0))
        bd = ImageDraw.Draw(border)
        bd.rounded_rectangle([0, 0, cov_w - 1, cov_h - 1], radius=6, outline=(255, 255, 255, 200), width=2)
        panel = Image.alpha_composite(panel, border)
        canvas.alpha_composite(panel, (cx0, cov_top))
    else:
        draw.rounded_rectangle(
            [cx0, cov_top, cx0 + cov_w, cov_top + cov_h],
            radius=6,
            outline=(255, 255, 255, 80),
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
    meta_y = cov_top + cov_h + 16
    game = entry.get("game", "Unknown")
    stype = entry.get("song_type", TYPE_LABEL.get(tp_id, "?"))
    gh = wrap_text(
        draw,
        game,
        fonts["game"],
        rx0,
        meta_y,
        pw,
        30,
        (240, 245, 255, 255),
        max_lines=2,
    )
    meta_y += max(gh, 28) + 10
    draw.rounded_rectangle(
        [rx0, meta_y, rx1, meta_y + 32],
        radius=5,
        fill=(*accent, 45),
        outline=(*accent, 160),
        width=1,
    )
    draw.text(
        (rx0 + pw // 2, meta_y + 16),
        stype.upper(),
        font=fonts["badge"],
        fill=(*accent, 255),
        anchor="mm",
    )

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


def resolve_media_path(local_file, playlist_path):
    lf = (local_file or "").strip()
    if not lf:
        return None
    p = Path(lf)
    if p.is_file():
        return p
    script_dir = Path(__file__).resolve().parent
    pl_parent = Path(playlist_path).resolve().parent
    for base in (pl_parent, script_dir, Path.cwd()):
        cand = (base / lf).resolve()
        if cand.is_file():
            return cand
    return p


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


def escape_filter_path(p: str) -> str:
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")


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
    drawfont_path,
    media_has_audio=True,
):
    """
    Composite: background + scaled media in (vx,vy,vw,vh) + overlay + optional drawtext timer.
    Inputs: 0 = media, 1 = overlay PNG; if not media_has_audio, 2 = anullsrc (silent AAC).
    """
    font_esc = escape_filter_path(drawfont_path) if drawfont_path and os.path.isfile(drawfont_path) else ""

    if is_video:
        if aspect_mode == "stretch":
            scale_chain = f"[0:v]scale={vw}:{vh}:flags=lanczos,setsar=1[vs]"
        else:
            scale_chain = (
                f"[0:v]scale={vw}:{vh}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2:color=0x050508,setsar=1[vs]"
            )
        fc = (
            f"color=c=0x0a0d12:s={W}x{H}:d={dur}:r={fps},format=rgba[bg];"
            f"{scale_chain};"
            f"[bg][vs]overlay=x={vx}:y={vy}:format=auto[vm];"
            f"[1:v]format=rgba[ov];"
            f"[vm][ov]overlay=0:0:format=auto[v1]"
        )
    else:
        fc = (
            f"color=c=0x0a0d12:s={W}x{H}:d={dur}:r={fps},format=rgba[bg];"
            f"[1:v]format=rgba[ov];"
            f"[bg][ov]overlay=0:0:format=auto[v1]"
        )

    tx = max(12, vx - 5)
    ty = H - 85
    if font_esc:
        dt = (
            f"drawtext=fontfile='{font_esc}':text='%{{pts\\:hms}}':x={tx}:y={ty}:"
            f"fontsize={max(16, H // 54)}:fontcolor=white@0.92:borderw=1:bordercolor=black@0.5"
        )
        fc += f";[v1]{dt}[vout]"
        vmap = "[vout]"
    else:
        vmap = "[v1]"

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


def make_silent_clip_composite(overlay_path, clip_path, dur, fps, crf, preset, verbose, W, H, drawfont_path):
    font_esc = escape_filter_path(drawfont_path) if drawfont_path and os.path.isfile(drawfont_path) else ""
    fc = (
        f"color=c=0x0a0d12:s={W}x{H}:d={dur}:r={fps},format=rgba[bg];"
        f"[1:v]format=rgba[ov];"
        f"[bg][ov]overlay=0:0:format=auto[v1]"
    )
    if font_esc:
        fc += (
            f";[v1]drawtext=fontfile='{font_esc}':text='%{{pts\\:hms}}':x=24:y={H - 85}:"
            f"fontsize={max(16, H // 54)}:fontcolor=white@0.92[vout]"
        )
        vmap = "[vout]"
    else:
        vmap = "[v1]"

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
            "18",
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


def main():
    ap = argparse.ArgumentParser(description="EMQ Ranking Builder — Video Renderer")
    ap.add_argument("playlist")
    ap.add_argument("--out", default="ranking.mp4")
    ap.add_argument("--transition", default=None, type=float)
    ap.add_argument("--fps", default=None, type=int)
    ap.add_argument("--width", default=None, type=int)
    ap.add_argument("--height", default=None, type=int)
    ap.add_argument("--crf", default=18, type=int)
    ap.add_argument(
        "--preset",
        default="fast",
        choices=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "veryslow"],
    )
    ap.add_argument("--font", default=None)
    ap.add_argument("--font-jp", default=None)
    ap.add_argument("--work-dir", default="emq_work")
    ap.add_argument("--keep-clips", action="store_true")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    print(f"\n{'='*60}\n  EMQ Ranking Builder — Video Renderer\n{'='*60}\n")

    if not check_ffmpeg():
        sys.exit(1)

    pl_path = Path(args.playlist)
    if not pl_path.is_file():
        sys.exit(f"ERROR: {args.playlist} not found")

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
    print(f"  4:3 / non-16:9 video: {aspect_mode}")
    print(f"  Duration:   ~{m}m {s}s")
    print(f"  Transition: {trans}s crossfade" if trans else "  Transition: hard cuts")

    print("\n  Fonts:")
    fonts = load_fonts(args, W, H)
    drawfont = args.font or fonts.get("lat_path") or ""

    work = Path(args.work_dir)
    frames = work / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    covers = work / "covers"
    covers.mkdir(exist_ok=True)
    clips = work / "clips"
    clips.mkdir(exist_ok=True)

    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 EMQ-Ranking-Builder/4"

    print(f"\n{'─'*60}\n  Processing {len(entries)} songs\n{'─'*60}")

    clip_paths, durations = [], []
    no_audio = 0

    for i, entry in enumerate(entries):
        rank = entry.get("rank", i + 1)
        title = entry.get("title", "?")
        print(f"\n  [{i+1:>3}/{len(entries)}] #{rank} — {title}")

        clip_path = str(clips / f"{rank:04d}.mp4")
        if args.skip_existing and os.path.isfile(clip_path) and os.path.getsize(clip_path) > 4096:
            print("    ✓ clip exists, skipping")
            clip_paths.append(clip_path)
            durations.append(float(entry.get("duration", 30)))
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

        lf_raw = entry.get("local_file")
        media_path = resolve_media_path(lf_raw, pl_path)
        kind = media_kind(media_path) if media_path and media_path.is_file() else "missing"
        is_video = kind == "video"

        overlay_path = str(frames / f"{rank:04d}.png")

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
            print(f"    Media:  ✓ {media_path.name}  ({'video' if is_video else 'audio'})")
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
                drawfont,
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
                        drawfont,
                        media_has_audio=has_aud,
                    )
        else:
            if lf_raw:
                print(f"    Media:  ✗ not found: {lf_raw!r}  → silence")
            else:
                print("    Media:  ─ no local_file  → silence")
            no_audio += 1
            ok = make_silent_clip_composite(
                overlay_path, clip_path, dur, fps, args.crf, args.preset, args.verbose, W, H, drawfont
            )

        if ok:
            clip_paths.append(clip_path)
            durations.append(dur)
            print("    Clip:   ✓")
        else:
            print("    Clip:   ✗ FFmpeg failed")

    if not clip_paths:
        sys.exit("\nERROR: No clips generated successfully.")

    print(f"\n{'─'*60}\n  Concatenating {len(clip_paths)} clips → {args.out}\n{'─'*60}")

    if trans > 0 and len(clip_paths) > 1:
        ok = concat_xfade(clip_paths, durations, trans, args.out, args.verbose)
    else:
        filelist = str(work / "filelist.txt")
        ok = concat_cuts(clip_paths, filelist, args.out, args.verbose)

    if ok and os.path.isfile(args.out):
        size_mb = os.path.getsize(args.out) / 1024 / 1024
        print(f"\n{'='*60}\n  ✓  {args.out}  ({size_mb:.1f} MB)")
        if no_audio:
            print(f"\n  ⚠  {no_audio} song(s) missing usable media path.")
        print(f"{'='*60}\n")
    else:
        sys.exit("\n  ✗ Concatenation failed.")

    if not args.keep_clips:
        shutil.rmtree(str(work), ignore_errors=True)


if __name__ == "__main__":
    main()
