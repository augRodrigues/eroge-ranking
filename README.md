# EMQ Ranking Builder

Browser-based ranking tool + Python/FFmpeg video renderer for
[ErogeMusicQuiz](https://erogemusicquiz.com/) music rankings.

## Files

| File | Purpose |
|---|---|
| `index.html` | Browser app: search songs, build ranking, export playlist |
| `db.json` | Song database (you generate this with `build_db.py`) |
| `build_db.py` | Parses EMQ pg_dump files → `db.json` |
| `render_video.py` | Reads `playlist.json`, renders frames with Pillow, encodes with FFmpeg |

## Workflow

### 1 — Build the song database (once)

```bash
python build_db.py /path/to/pg_dump_directory
# or individual files:
python build_db.py 3844.dat 3845.dat 3851.dat ...
```

Outputs `db.json` (~10 MB). Place it next to `index.html`.

### 2 — Deploy to GitHub Pages

```bash
git init eroge-ranking && cd eroge-ranking
cp /path/to/index.html .
cp /path/to/db.json .
git add . && git commit -m "init"
git remote add origin https://github.com/YOU/eroge-ranking
git push -u origin main
# Settings → Pages → deploy from main / root
```

### 3 — Build the ranking

1. Open the site (or `index.html` locally with a server)
2. Search for songs by title, game, or artist → click to add
3. Paste EMQ links with the **+ URL** button
4. Drag-to-reorder or use ↑↓ buttons
5. Set **Clip** (seconds) and **Start at** per song, or use Apply to all
6. In the **Local file** field on each card, enter the full path to
   the audio file on your computer  
   e.g. `/home/user/music/tori_no_uta.mp3`

### 4 — Export and render

Click **Export playlist** in the app:
- It fetches VNDB cover image URLs (public API, no auth needed)
- Downloads `playlist.json` with all song info embedded

Then render the video:

```bash
# Install deps (once)
pip install Pillow requests
# ffmpeg must be on PATH

python render_video.py playlist.json
python render_video.py playlist.json --out my_ranking.mp4 --crf 18 --preset slow
python render_video.py playlist.json --transition 0      # hard cuts
python render_video.py playlist.json --width 1280 --height 720
```

## Audio files

The renderer uses **local files only** — there is no login or cookie
handling. Set paths in the browser app (Local file field) before
exporting, or edit `playlist.json` directly:

```json
{
  "rank": 1,
  "title": "Tori no Uta",
  "local_file": "/home/user/music/tori_no_uta.mp3",
  ...
}
```

If a song has no `local_file`, the clip is rendered with silence.

## render_video.py options

```
--out FILE          Output file (default: ranking.mp4)
--transition SECS   Crossfade duration (default: from playlist)
--fps N             Frame rate
--width W           Width override
--height H          Height override
--crf N             H.264 CRF quality 0-51, lower = better (default 18)
--preset NAME       ultrafast / fast / medium / slow (default fast)
--font FILE         Bold latin TTF font
--font-jp FILE      Japanese TTF/OTC font (NotoSansCJK recommended)
--work-dir DIR      Temp folder for frames/clips (default: emq_work)
--keep-clips        Keep per-song MP4 clips after encoding
--skip-existing     Resume: skip clips already on disk
-v, --verbose       Show FFmpeg output
```

## Video frame layout

```
┌──────────────────────────────────────────────────────────────┐
│  [blurred game cover background, 80% dimmed]                 │
│                                                              │
│  ┌─────────────┐  OPENING                                   │
│  │  Game cover │                                            │
│  │  art, fit   │  Song Title                                │
│  │  in panel   │  Japanese Title                            │
│  │             │                                            │
│  │             │  Game Name                                 │
│  │             │  Vocals:      Singer                       │
│  │  #42        │  Music:       Composer                     │
│  └─────────────┘  Arrangement: Arranger                     │
│                   Lyrics:      Lyricist                      │
│                                                              │
│  ─────────────────────────────────────────────────────[bar] │
└──────────────────────────────────────────────────────────────┘
```

Cover art fetched from VNDB API (public, no auth).

## Output format

`.mp4` (H.264 + AAC) — directly uploadable to YouTube.  
Use `--transition 0.5` (default) for smooth crossfades between songs.

## Tips

- **Japanese fonts**: install `fonts-noto-cjk` on Linux for best results  
  `sudo apt install fonts-noto-cjk`
- **Slow encode**: `--preset slow --crf 16` for archive quality
- **Resume**: if interrupted, re-run with `--skip-existing`
- **720p test**: `--width 1280 --height 720` for a quick preview encode

---

MIT License
