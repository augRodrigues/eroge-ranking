# EMQ Ranking Builder

Browser app to build an [ErogeMusicQuiz](https://erogemusicquiz.com/) ranking and export `playlist.json`, plus a Python/FFmpeg renderer that composites media into a single ranking video.

## Files

| File | Purpose |
|------|---------|
| `index.html` | Search DB, order songs, export playlist |
| `db.json` | Song database (from `build_db.py`) |
| `build_db.py` | Parse EMQ pg_dump → `db.json` |
| `render_video.py` | Read `playlist.json`, render HUD overlay, encode with FFmpeg |

## Workflow

1. **Database** — Run `build_db.py` (auto-downloads today's dump if no file is given), place `db.json` next to `index.html`.

```bash
python build_db.py              # auto-download
python build_db.py dump.txt     # use local dump
```

2. **Ranking** — Open `index.html`, search for songs, drag to reorder, set clip length and start time per entry. Attaching a local media file is optional — the renderer can download files automatically from erogemusicquiz.com using session cookies.

3. **Export** — Click **Export playlist**. The app fetches VN cover, romanized/Japanese title, developers, and release date from the VNDB API, then downloads `playlist.json`.

4. **Render** — Place `cookies.json` (exported from your browser for erogemusicquiz.com) next to `render_video.py`, then run:

```bash
pip install Pillow requests   # once
python render_video.py playlist.json
python render_video.py playlist.json --out my_ranking.mp4 --crf 18 --preset slow
```

Downloaded media is cached in a `media/` folder and never deleted. Re-runs skip already-rendered clips unless `--force-render` is passed.

## `render_video.py` options

`--out`, `--transition`, `--fps`, `--width`, `--height`, `--crf`, `--preset`, `--font`, `--font-jp`, `--work-dir`, `--keep-clips`, `--force-render`, `--cookies`, `--token`, `--no-download`, `-v` / `--verbose`.

Japanese text requires a CJK-capable font (`--font-jp` or install Noto CJK). Output is H.264 + AAC MP4.

---

MIT License
