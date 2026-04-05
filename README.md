# EMQ Ranking Builder

Browser app to build an [ErogeMusicQuiz](https://erogemusicquiz.com/) ranking and export `playlist.json`, plus a Python/FFmpeg renderer that composites local media into a single ranking video.

## Files

| File | Purpose |
|------|---------|
| `index.html` | Search DB, order songs, pick media files, export playlist |
| `db.json` | Song database (from `build_db.py`) |
| `build_db.py` | Parse EMQ pg_dump → `db.json` |
| `render_video.py` | Read `playlist.json`, draw HUD overlay, encode with FFmpeg |

## Workflow

1. **Database** — Run `build_db.py` on your dump, place `db.json` next to `index.html`.
2. **Ranking** — Open the app, add songs, set clip length and start time, use **Browse** on each card to attach a media file (only the filename is stored; put the real files next to `render_video.py` or `playlist.json` before rendering).
3. **Export** — **Export playlist** calls the public VNDB API (no token) for cover URL, romanized title, Japanese title, developers, and release date, then downloads `playlist.json`. Re-export after changes so metadata stays in sync.
4. **Render** — From the folder that contains your media and `playlist.json`:

```bash
pip install Pillow requests   # once
python render_video.py playlist.json
python render_video.py playlist.json --out my_ranking.mp4 --crf 18 --preset slow
```

Video files are fitted into a 16:9 window (letterbox or stretch per export settings). Audio-only files use a dedicated “sound only” panel. A thin progress bar under the video reflects elapsed time in the clip. Missing or wrong `local_file` paths produce silent clips.

## `render_video.py` options

`--out`, `--transition`, `--fps`, `--width`, `--height`, `--crf`, `--preset`, `--font`, `--font-jp`, `--work-dir`, `--keep-clips`, `--skip-existing`, `-v` / `--verbose`.

Japanese text needs a CJK-capable `--font-jp` (or install Noto CJK). Output is H.264 + AAC MP4, suitable for YouTube.

---

MIT License
