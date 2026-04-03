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
3. Paste an EMQ link (e.g. `https://erogemusicquiz.com/music/12345`) with the **+ URL** button
4. Reorder by dragging cards or using ↑↓ buttons
5. Set clip length and start offset per song, or use **Apply to all**
6. Click **▶ Generate video** — configure resolution/FPS, then encode

---

## Ranking builder features

| Feature | Details |
|---|---|
| Search | Multi-term; searches title (JP+latin), game, artists |
| Add by URL | Paste direct media URLs (.webm, .mp4, .mp3, .ogg) or EMQ links; auto-detects video vs audio |
| Drag reorder | Full drag-and-drop |
| ↑↓ buttons | For precision reorder |
| Clip duration | Per-song, with "Apply to all" global default |
| Start offset | Skip intros — e.g. start at 10s |
| Local upload | Per-song fallback for audio/video files |
| Save/Load | Export ranking as JSON, reload later |
| Session restore | Ranking survives page refresh (sessionStorage) |

---

## Video output

- **Format**: WebM (VP9 + Opus) — directly uploadable to YouTube
- **Encoding**: Real-time in-browser using Canvas + MediaRecorder
- **Duration**: Equal to sum of all clip lengths (e.g. 300 songs × 30s = 150 min)
- **Transitions**: 0.5s fade between songs

### Layout for audio tracks

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

### Layout for video tracks

```
┌──────────────────────────────────────────────────────────────┐
│ INFO │                                                       │
│      │                                                       │
│ 20%  │                   VIDEO (80%)                         │
│panel │          pillarboxed for 4:3 content                  │
│      │                                                       │
│ #42  │                                                       │
│      │                                                       │
│███████████████████████████████████████████████████  0:18     │
└──────────────────────────────────────────────────────────────┘
```

Video content fills 80% of the screen width, with metadata displayed in a 20% left panel. 4:3 videos automatically get black pillarbars on the sides.

### Audio

The tool fetches audio/video directly from EMQ using your browser's session cookie. **Be logged into erogemusicquiz.com** before encoding. If fetch fails, use **"📁 Upload local"** per song.

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

## File structure

```
eroge-ranking/
├── index.html     ← The entire app (single self-contained file)
├── db.json        ← Generated by build_db.py (you create this)
├── build_db.py    ← Run this once to build db.json
└── README.md
```

---

MIT License
