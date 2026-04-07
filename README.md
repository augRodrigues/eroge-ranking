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

2. **Ranking** — Open `index.html`, search for songs, drag to reorder, set clip length and start time per entry. Attaching a local media file is optional — the renderer downloads files automatically from erogemusicquiz.com using session cookies.

3. **Export** — Click **Export playlist**. The app fetches VN cover, romanized/Japanese title, developers, and release date from the VNDB API, then downloads `playlist.json`.

4. **Render** — Place `cookies.json` (exported from your browser for erogemusicquiz.com) next to `render_video.py`, then run:

```bash
pip install Pillow requests   # once
python render_video.py playlist.json
python render_video.py playlist.json --out my_ranking.mp4 --crf 18 --preset slow
```

Downloaded media is cached in `media/` and never deleted. Re-runs skip already-rendered clips unless `--force-render` is passed.

## Video Overlay

The rendered overlay uses a glassmorphism aesthetic:
- `#121212` dark base with blurred cover art background
- Frosted glass panels (credits bar + sidebar) with hero-color dynamic tinting
- Hero color is sampled from each clip's cover art; falls back to violet `#8B5CF6` for dark/grey art
- Sidebar shows rank number, VN cover art, `<<TITLE>>` / `<<DEVELOPER>>` / `<<RELEASE DATE>>`
- Credits bar shows song title, vocalist, and C/A/L composer credits

## Party Rank

Multiple people can score the same song list and the host renders a combined ranking.

**Host:**
1. Build the song list in `index.html` as usual.
2. Click **★ Party** → **Export template**. Downloads a single `party_template.json` — share with participants.

**Each participant:**
1. Load `party_template.json` via **Load ranking** — enter your name and pick a profile picture.
2. Score each song 1–10 using the star rating. Use **Play** to listen via EMQ.
3. Click **↓ Export scores** → send `scores_Name.json` to the host.

**Host renders:**
```bash
python render_video.py party_template.json --scores alice.json bob.json charlie.json
```

Scores are averaged. Video plays worst (#N) to best (#1). Right panel shows participant avatars with scores and the average per song.

## `render_video.py` options

`--out`, `--scores`, `--transition`, `--fps`, `--width`, `--height`, `--crf`, `--preset`, `--font`, `--font-jp`, `--work-dir`, `--keep-clips`, `--force-render`, `--cookies`, `--token`, `--no-download`, `-v` / `--verbose`.

Japanese text requires a CJK-capable font (`--font-jp` or install Noto CJK). Output is H.264 + AAC MP4.

---

MIT License
