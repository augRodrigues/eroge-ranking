# ♪ EMQ Ranking Builder

A browser-based tool for building eroge music ranking videos using the [ErogeMusicQuiz](https://erogemusicquiz.com/) database, with optional Python-based encoding for higher quality output.

**[→ Open the app](https://YOUR-USERNAME.github.io/eroge-ranking/)**

---

## Quick start

### 1. Build the song database

You need the EMQ PostgreSQL dump. Run the included script:

```bash
python build_db.py /path/to/pg_dump_directory
# or pass individual .dat files:
python build_db.py file1.dat file2.dat file3.dat ...
```

This outputs `db.json` (~10 MB). The script auto-detects which table each file contains — no manual file numbering needed.

> **Python 3.8+ only.** No dependencies beyond the standard library.

### 2. Deploy to GitHub Pages

```bash
git init eroge-ranking && cd eroge-ranking
cp /path/to/index.html .
cp /path/to/db.json .
git add . && git commit -m "init"
git remote add origin https://github.com/YOUR-USERNAME/eroge-ranking
git push -u origin main
```

In your repo → Settings → Pages → deploy from `main` / root.

### 3. Use the app

1. Open the site — it fetches `db.json` automatically.  
   If running locally without a server, open the page and pick `db.json` via the file picker.
2. Search for songs by title, game, or artist → click to add
3. Paste an EMQ link (e.g. `https://erogemusicquiz.com/music/12345`) with the **+ URL** button
4. Reorder by dragging cards or using ↑↓ buttons
5. Set clip length and start offset per song, or use **Apply to all**
6. Click **▶ Generate video** — choose either:
   - **Browser encoding**: Real-time WebM generation (faster preview)
   - **Export for Python**: JSON export for high-quality FFmpeg encoding

---

## Two encoding workflows

### Option A: Browser encoding (built-in)

- **Format**: WebM (VP9 + Opus)
- **Encoding**: Real-time in-browser using Canvas + MediaRecorder
- **Best for**: Quick previews, shorter rankings (< 50 songs)
- **Limitations**: Timing inaccuracies, no audio crossfades, browser-dependent quality

### Option B: Python encoder (recommended for final output)

- **Format**: MP4 (H.264 + AAC) or WebM
- **Encoding**: FFmpeg-based with precise timing and audio crossfades
- **Best for**: Final uploads to YouTube, longer rankings, professional quality
- **Requirements**: Python 3.8+, FFmpeg installed

**Workflow:**
1. Build your ranking in the browser app
2. Click **▶ Generate video** → **Export for Python**
3. Download `emq-encoder-input.json`
4. Run the encoder:
   ```bash
   python emq_encoder.py emq-encoder-input.json --output ranking.mp4 --verbose
   ```

---

## Ranking builder features

| Feature | Details |
|---|---|
| Search | Multi-term; searches title (JP+latin), game, artists |
| Add by URL | Paste EMQ link or just the numeric ID |
| Drag reorder | Full drag-and-drop |
| ↑↓ buttons | For precision reorder |
| Clip duration | Per-song, with "Apply to all" global default |
| Start offset | Skip intros — e.g. start at 10s |
| Local audio upload | Per-song fallback when EMQ audio fails |
| Save/Load | Export ranking as JSON, reload later |
| Session restore | Ranking survives page refresh (sessionStorage) |
| Python export | Generate JSON for high-quality external encoding |

---

## Video output

### Browser encoding

- **Duration**: Equal to sum of all clip lengths (e.g. 300 songs × 30s = 150 min)
- **What each frame shows**:
```
┌──────────────────────────────────────────────────────────────┐
│  [blurred game cover background]                             │
│                                                              │
│  ┌──────────────┐  OPENING                                  │
│  │              │                                           │
│  │  Game cover  │  Song Title                               │
│  │  art panel   │  Japanese Title                           │
│  │              │                                           │
│  │              │  Game Name                                │
│  │              │                                           │
│  │  #42         │  Vocals:      Artist Name                 │
│  └──────────────┘  Lyrics:      Lyricist Name               │
│                    Music:       Composer Name               │
│                                                             │
│ ███████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░  0:18      │
└──────────────────────────────────────────────────────────────┘
```

Cover art is fetched from the **VNDB API** (public, no auth needed).

### Audio

The tool fetches audio directly from EMQ. Since EMQ requires login, **be logged into erogemusicquiz.com in the same browser** before encoding — the browser sends your session cookie automatically.

If audio fetch fails (CORS or auth issue), use the **"📁 Upload local"** button on each song card to provide an audio file you downloaded manually.

---

## Python encoder (emq_encoder.py)

A complete FFmpeg-based encoder that solves the limitations of browser encoding:

### Features

- ✅ Precise video timing (no frame drops or length mismatches)
- ✅ Audio crossfades between songs (configurable transition duration)
- ✅ Video crossfade transitions
- ✅ Better quality control (CRF, preset, bitrate)
- ✅ Reproducible output
- ✅ Background processing (no browser tab needed)

### Installation

```bash
# Ensure FFmpeg is installed
# Ubuntu/Debian:
sudo apt install ffmpeg
# macOS:
brew install ffmpeg
# Windows: Download from ffmpeg.org or use choco/scoop
```

### Usage

```bash
# Basic usage
python emq_encoder.py emq-encoder-input.json --output ranking.mp4

# With verbose output
python emq_encoder.py emq-encoder-input.json --output ranking.mp4 --verbose

# Generate shell script with FFmpeg commands (for inspection/modification)
python emq_encoder.py emq-encoder-input.json --generate-script encode.sh

# Custom resolution
python emq_encoder.py emq-encoder-input.json --output ranking.mp4 --width 1280 --height 720

# Adjust crossfade duration
python emq_encoder.py emq-encoder-input.json --output ranking.mp4 --transition 1.0
```

### Input JSON format

The HTML app exports JSON in this format:
```json
{
  "config": {
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "bitrate": "8M",
    "transition_duration": 0.5
  },
  "entries": [
    {
      "rank": 1,
      "song": {
        "id": "12345",
        "t": "Song Title",
        "tj": "曲タイトル",
        "gt": "Game Name",
        "artists": "Artist Name",
        "st": 1,
        "au": "https://...",
        "vid": "v12345"
      },
      "duration": 30.0,
      "startTime": 0.0,
      "localFile": null,
      "coverFile": null
    }
  ]
}
```

---

## build_db.py details

The script scans all `.dat` files in your dump directory, auto-detects which table each file (or each block within a merged file) contains, and joins:

| Table detected | Used for |
|---|---|
| `music_title` | Song names (latin + Japanese) |
| `music_external_link` | Audio URLs |
| `music_source_music` | Song type (Opening/Ending/Insert/BGM) |
| `music_source_title` | Game titles |
| `music_source_external_link` | VNDB IDs (→ cover art) |
| `artist_music` | Artist roles |
| `artist_alias` | Artist names |

Detection uses content fingerprints (column count, data types, value ranges) — no reliance on file naming.

URLs in the database use the internal hostname `emqselfhost` — the script replaces these with `erogemusicquiz.com` automatically.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "db.json not found" | Run `python build_db.py` first; or use the file picker |
| Missing table in build output | Pass more `.dat` files; check the "Unidentified blocks" hint in output |
| No audio in video | Log into erogemusicquiz.com first; or upload local files |
| CORS error on audio | Same — login required, or use local upload |
| Slow encoding (browser) | Normal — it's real-time. Use Python encoder for faster processing |
| Video length wrong | Browser encoding limitation — use Python encoder |
| Audio cuts between songs | Browser doesn't support crossfades — use Python encoder |
| FFmpeg not found | Install FFmpeg and ensure it's in your PATH |
| Python encoder too slow | Use `-preset ultrafast` or reduce CRF quality |

---

## File structure

```
eroge-ranking/
├── index.html         ← The entire app (single self-contained file)
├── db.json            ← Generated by build_db.py (you create this)
├── build_db.py        ← Run this once to build db.json
├── emq_encoder.py     ← Python video encoder (optional, for high-quality output)
├── sample_ranking.json← Example input for emq_encoder.py
└── README.md
```

---

MIT License
