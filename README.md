# EMQ Ranking Builder

Build a ranking of songs from [ErogeMusicQuiz](https://erogemusicquiz.com/) and render it into a video!

## What you need
- Python 3
- FFmpeg
- Pillow & requests (`pip install Pillow requests`)

---

## Quick Start
1. **(Optional) Build/update the song database**
   - Skip this step if you already have an updated `db.json`.
   - To update:
     ```bash
     python build_db.py
     ```
     This will try to auto-download today's database and create `db.json`
   - If auto-download fails:
     1. Manually download the dump from https://dl.erogemusicquiz.com/dump/song/
     2. Extract it
     3. Run:
        ```bash
        python build_db.py /path/to/extracted/dump.txt
        ```

2. **Make your ranking**
   Open `index.html` in your browser:
   - Search for songs and add them to your ranking
   - Drag to reorder
   - Set clip length and start time for each song
   - Use the new dropdown to choose which song link to use (video or audio)

3. **Export your playlist**
   Click **Export playlist** → it will download `playlist.json`

4. **Set up cookies (for downloading media)**
   - Open erogemusicquiz.com in your browser and log in
   - Press F12 → Go to **Application/Storage** tab → **Cookies**
   - Find `session-token` and `user-id` cookies for erogemusicquiz.com
   - Open `cookies_rename.json` and replace the placeholder values with your actual cookie values
   - Rename the file to `cookies.json`
   - Place `cookies.json` next to `render_video.py`

5. **Render the video!**
   ```bash
   python render_video.py playlist.json
   ```
   This will download media, render the video, and save it to `ranking.mp4`.

---

## Party Rank
Have multiple people score the same songs?
1. **Host:** Build your song list → click **★ Party** → **Export template** → share `party_template.json`
2. **Participants:** Load the template, add your name/avatar, score each song 1–10, then export your `scores_Name.json`
3. **Host:** Render the combined ranking
   ```bash
   python render_video.py party_template.json --scores alice.json bob.json charlie.json
   ```

---

## Useful `render_video.py` Options
```bash
# Custom output filename and quality
python render_video.py playlist.json --out my_ranking.mp4 --crf 18 --preset slow

# Force re-render already-processed clips
python render_video.py playlist.json --force-render

# See all options
python render_video.py --help
```

---

## Files Explained
| File | Purpose |
|------|---------|
| `index.html` | Browser app to build rankings |
| `db.json` | Song database (from build_db.py) |
| `build_db.py` | Creates db.json (auto-downloads dump) |
| `render_video.py` | Renders the final video |
| `cookies.json` | Your EMQ session cookies (for downloading media) |

---

MIT License
