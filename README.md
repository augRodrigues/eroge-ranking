# ♪ EMQ Ranking Builder

A browser-based tool for building and encoding eroge music ranking videos using the [ErogeMusicQuiz](https://erogemusicquiz.com/) database.

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
3. Paste a direct media URL (e.g. `https://erogemusicquiz.com/selfhoststorage/xxx.webm`) with the **+ URL** button; auto-detects video vs audio from file extension
4. Reorder by dragging cards or using ↑↓ buttons
5. Set clip length and start offset per song, or use **Apply to all**
6. Click **▶ Generate video** — configure resolution/FPS, then encode

**Important:** Be logged into erogemusicquiz.com in the same browser before encoding. The tool uses your session cookie to fetch protected media files directly from EMQ servers. If you're not logged in, audio/video fetch will fail with CORS errors.

---

## Ranking builder features

| Feature | Details |
|---|---|
| Search | Multi-term; searches title (JP+latin), game, artists |
| Add by URL | Paste direct media URLs (.webm, .mp4, .mp3, .ogg); auto-detects video vs audio from file extension |
| Drag reorder | Full drag-and-drop |
| ↑↓ buttons | For precision reorder |
| Clip duration | Per-song, with "Apply to all" global default |
| Start offset | Skip intros — e.g. start at 10s |
| Local upload | Per-song fallback for audio/video files |
| Save/Load | Export ranking as JSON, reload later |
| Session restore | Ranking survives page refresh (sessionStorage) |
| VNDB Integration | Auto-fetches cover art from VNDB API for visual novels |

---

## Video output

- **Format**: WebM (VP9 + Opus) — directly uploadable to YouTube
- **Encoding**: Real-time in-browser using Canvas + MediaRecorder
- **Duration**: Equal to sum of all clip lengths (e.g. 300 songs × 30s = 150 min)
- **Transitions**: 0.5s smooth crossfade between songs (current fades out while next fades in)
- **Keyframes**: Optimized keyframe interval (every 2 seconds) for smooth playback and seeking

### Layout for audio tracks

```
┌──────────────────────────────────────────────────────────────┐
│  [blurred game cover background]                             │
│                                                              │
│  ┌──────────────┐  OPENING                                   │
│  │              │                                            │
│  │  Game cover  │   Song Title                               │
│  │  art panel   │   Japanese Title                           │
│  │              │                                            │
│  │              │   Game Name                                │
│  │              │                                            │
│  │  #42         │   Vocals:     Artist Name                  │
│  └──────────────┘   Composer:   Composer Name                │
│                     Arranger:   Arranger Name                │
│                     Lyrics:     Lyricist Name                │
│                                                              │
│ ███████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░  0:18       │
└──────────────────────────────────────────────────────────────┘
```

### Layout for video tracks

```
┌──────────────────────────────────────────────────────────────┐
│ INFO │                                                       │
│      │                                                       │
│ 20%  │                   VIDEO (80%)                         │
│panel │          pillarboxed for 4:3 content                  │
│      │                                                       │
│      │                                                       │
│ Song │                                                       │
│ Titl │                                                       │
│ Game │                                                       │
│ Voca │                                                       │
│ Comp │                                                       │
│ Arra │                                                       │
│ Lyri │                                                       │
│ #42  │                                                       │
│      │                                                       │
│███████████████████████████████████████████████████  0:18     │
└──────────────────────────────────────────────────────────────┘
```

Video content fills 80% of the screen width on the right side, with metadata displayed in a 20% left panel. The info panel is drawn first to prevent video overlap. 4:3 videos automatically get black pillarbars on the sides (pillarboxing). The info panel shows song title, game name, and all credited artists (vocals, composer, arranger, lyricist, etc.).

### Audio/Video Sync

The tool fetches audio/video directly from EMQ using your browser's session cookie. **Be logged into erogemusicquiz.com** before encoding. If fetch fails, use **"📁 Upload local"** per song. For video files, the start time offset is properly synchronized between audio and video tracks. The video player waits for full metadata load and seeks to the correct position before playback begins, ensuring accurate frame capture throughout encoding.

### Transition System

Between songs, a 0.5-second crossfade transition occurs:
- The current song's content fades to black
- Simultaneously, the next song's info panel fades in
- For video transitions, this creates a smooth fade-to-black effect with metadata preview
- For audio tracks, both covers blend smoothly during the transition

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
| Slow encoding | Normal — it's real-time. 10 songs × 30s = 5 min of recording |
| Output is `.webm` | To get `.mp4`: `ffmpeg -i ranking.webm -c:v libx264 -c:a aac ranking.mp4` |

---

## Python encoder (recommended for final output)

For better quality, precise timing, and reliable audio crossfades, use the included Python-based encoder instead of browser encoding.

### Setup

1. **Install FFmpeg**:
   - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html) or `choco install ffmpeg`
   - **macOS**: `brew install ffmpeg`
   - **Linux**: `sudo apt install ffmpeg` or `sudo dnf install ffmpeg`

2. **Verify installation**:
   ```bash
   ffmpeg -version
   ```

### Workflow

1. Build your ranking in the browser app as usual
2. Click **▶ Generate video** → **🐍 Export for Python** button
3. Download `emq-encoder-input.json` file
4. Place any local audio files in the same directory as the Python script
5. Run the encoder:

```bash
python emq_encoder.py emq-encoder-input.json --output ranking.mp4 --verbose
```

### Command-line options

| Option | Description |
|--------|-------------|
| `--output`, `-o` | Output video file (default: `ranking.mp4`) |
| `--verbose`, `-v` | Show detailed progress and debug info |
| `--generate-script` | Generate a shell script with FFmpeg commands instead of encoding |

### Input JSON format

The exported JSON has this structure:

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
        "st": 1,
        "au": "https://erogemusicquiz.com/...",
        "vid": "v123",
        "artists": "Vocals: Artist · Music: Composer"
      },
      "duration": 30.0,
      "startTime": 10.5,
      "localFile": "mysong.mp3",
      "videoFile": null,
      "coverFile": null
    },
    {
      "rank": 2,
      "song": {
        "id": "67890",
        "t": "Video Song",
        "tj": "ビデオソング",
        "gt": "Visual Novel",
        "st": 1,
        "au": null,
        "vid": "v456",
        "artists": "Vocals: Singer"
      },
      "duration": 30.0,
      "startTime": 0.0,
      "localFile": "opening.webm",
      "videoFile": "opening.webm",
      "coverFile": null
    }
  ]
}
```

**Song types (`st`)**:
- `0`: Unknown
- `1`: OP (Opening)
- `2`: ED (Ending)
- `3`: Insert song
- `4`: BGM
- `600`: Vocal/Character song

### Local files

When you upload local files in the browser:
- The export includes only the filename (not full path)
- Place these files in the **same directory** where you run `emq_encoder.py`
- The encoder will automatically find them
- For **video files** (webm, mp4, avi, mkv, mov), use the `"videoFile"` field
- For **audio-only files** (mp3, ogg, wav, flac), use the `"localFile"` field

### Video files (with cinematics)

For eroge songs with video cinematics (like anime openings):
1. Export your ranking from the browser app
2. The JSON will include `"videoFile"` for video entries
3. Place the video files (`.webm`, `.mp4`, etc.) in the same directory as the encoder
4. The encoder will:
   - Extract and use the video with its embedded audio
   - Apply text overlays (rank, title, artist, game)
   - Handle proper timing with start time offsets

### Features

- ✅ Precise frame-accurate timing
- ✅ Smooth audio crossfades between songs
- ✅ Proper video length calculation
- ✅ No browser memory limits
- ✅ Higher quality output (configurable CRF/bitrate)
- ✅ Supports both URL downloads and local files
- ✅ Auto-fetches cover art from VNDB

### Troubleshooting

| Problem | Fix |
|---------|-----|
| `FFmpeg not found` | Install FFmpeg and ensure it's in your PATH |
| `No audio available` | Check that local files are in the same directory, or verify URLs are accessible |
| `Failed to process local audio` | Ensure the file format is supported by FFmpeg |
| Video has solid color background | This is intentional — background is generated from song type colors when no cover art is available |

---

## File structure

```
eroge-ranking/
├── index.html         ← The entire app (single self-contained file)
├── db.json            ← Generated by build_db.py (you create this)
├── build_db.py        ← Run this once to build db.json
├── emq_encoder.py     ← Python-based video encoder (requires FFmpeg)
├── sample_ranking.json ← Example input for Python encoder
└── README.md
```

---

MIT License
