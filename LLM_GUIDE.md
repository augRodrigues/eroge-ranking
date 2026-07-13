# LLM Guide for EMQ Ranking Builder

## Project Overview

**EMQ Ranking Builder** is a tool that creates video rankings of songs from [ErogeMusicQuiz](https://erogemusicquiz.com/). Users can search for songs, build rankings, and render them into polished videos with custom overlays.

### Core Functionality
- **Database Building**: Downloads and processes PostgreSQL dumps from EMQ to create a local song database
- **Ranking Creation**: Browser-based UI for searching, selecting, and ordering songs
- **Video Rendering**: Downloads media files and renders videos with custom glassmorphism overlays
- **Party Mode**: Collaborative rankings where multiple participants score songs

## Architecture

The project consists of three main components:

### 1. Frontend (`index.html`)
- Single-page application (SPA) built with vanilla HTML/CSS/JavaScript
- No build process required - runs directly in browser
- Features:
  - Song search with autocomplete
  - Drag-and-drop reordering
  - Clip length and start time configuration
  - Media link selection (video/audio)
  - Party mode support
  - Playlist export to JSON

### 2. Database Builder (`build_db.py`)
- Streams PostgreSQL dumps line-by-line (low memory usage)
- Extracts 7 specific tables from the dump
- Prioritizes media selection: shortest video > shortest audio > other media
- Auto-downloads latest dump or accepts local file
- Outputs compact `db.json` with song metadata

### 3. Video Renderer (`render_video.py`)
- Downloads media files using authenticated session cookies
- Caches media persistently in `media/` folder
- Renders video overlays using PIL (Pillow)
- Supports party mode with participant scores
- Uses FFmpeg for video encoding

## Key Files

| File | Purpose | Notes |
|------|---------|-------|
| `index.html` | Browser UI for building rankings | Self-contained, no dependencies |
| `build_db.py` | Creates `db.json` from PostgreSQL dump | Auto-downloads latest dump |
| `render_video.py` | Renders final video from playlist | Requires `cookies.json` |
| `db.json` | Song database (generated) | Contains song metadata and media links |
| `playlist.json` | Exported ranking (generated) | Input to render_video.py |
| `cookies.json` | EMQ session cookies | Required for media download |
| `cookies_rename.json` | Cookie template | Rename to cookies.json after filling |
| `generate_test_data.py` | Test data generator | Creates sample playlists |

## Data Flow

```
PostgreSQL Dump → build_db.py → db.json
                                    ↓
index.html → playlist.json → render_video.py → ranking.mp4
                                    ↑
                              cookies.json
```

## Database Schema (`db.json`)

```json
{
  "version": 1,
  "built": "2024-01-01T00:00:00Z",
  "count": 10000,
  "songs": [
    {
      "id": "123",
      "t": "Song Title",
      "tj": "Japanese Title",
      "gt": "Game Title",
      "gtj": "Japanese Game Title",
      "st": 1,
      "vid": "v12345",
      "au": "https://...",
      "ad": "00:03:25.270",
      "links": [
        {
          "url": "https://...",
          "type": 1,
          "is_video": true,
          "duration": "00:03:25.270",
          "duration_sec": 205.27,
          "submitted_by": "user",
          "index": 0
        }
      ],
      "ar": [
        {"n": "Artist Name", "r": 1, "nj": "Japanese Name"}
      ]
    }
  ]
}
```

### Song Type Codes (`st`)
- `1`: Opening (OP)
- `2`: Ending (ED)
- `3`: Insert Song (INS)
- `4`: BGM
- `0`: Other

### Artist Role Codes (`r`)
- `1`: Vocals
- `2`: Music (Composer)
- `5`: Arrangement
- `6`: Lyrics

## Playlist Schema (`playlist.json`)

```json
{
  "version": 5,
  "exported_at": "2024-01-01T00:00:00Z",
  "total_songs": 10,
  "total_duration_secs": 300,
  "settings": {
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "transition": 0.5,
    "direction": "asc",
    "video_aspect_mode": "letterbox"
  },
  "entries": [
    {
      "rank": 1,
      "video_rank": 1,
      "id": "123",
      "title": "Song Title",
      "title_jp": "Japanese Title",
      "game": "Game Title",
      "game_jp": "Japanese Game Title",
      "song_type": "Opening",
      "song_type_id": 1,
      "vndb_id": "v12345",
      "cover_url": "https://...",
      "vn_romaji": "Game Title",
      "vn_title_jp": "Japanese Game Title",
      "vn_developers": "Developer",
      "vn_released": "2020-01-01",
      "local_file": null,
      "audio_url": "https://...",
      "duration": 30,
      "start_time": 50,
      "artists": [
        {
          "name": "Artist",
          "name_jp": "Japanese Name",
          "role_id": 1,
          "role": "Vocals"
        }
      ]
    }
  ]
}
```

## Party Mode Schema

### Party Template (`party_template.json`)
Same structure as playlist.json with additional:
```json
{
  "type": "party_template",
  "songs": [...]  // Simplified song list for reference
}
```

### Score Files (`scores_<name>.json`)
```json
{
  "type": "party_scores",
  "version": 1,
  "participant": "username",
  "avatar": "data:image/png;base64,...",
  "scores": [
    {"id": "123", "score": 8.5},
    {"id": "456", "score": 9.0}
  ]
}
```

## Dependencies

### Required
- **Python 3.8+**
- **FFmpeg** (must be in PATH)
- **Pillow** (`pip install Pillow`)
- **requests** (`pip install requests`)

### Optional
- **7-Zip** (for auto-extracting zstd dumps)

## Common Workflows

### Building the Database
```bash
# Auto-download latest dump
python build_db.py

# Use local dump file
python build_db.py /path/to/dump.txt

# Custom output
python build_db.py --out custom_db.json
```

### Creating a Ranking
1. Open `index.html` in browser
2. Search for songs and add to ranking
3. Drag to reorder
4. Set clip duration and start times
5. Select media links (video/audio dropdown)
6. Click "Export playlist" to download `playlist.json`

### Rendering a Video
```bash
# Basic rendering
python render_video.py playlist.json

# Custom output and quality
python render_video.py playlist.json --out custom.mp4 --crf 18 --preset slow

# Force re-render all clips
python render_video.py playlist.json --force-render

# Party mode with scores
python render_video.py party_template.json --scores alice.json bob.json charlie.json
```

### Setting Up Cookies
1. Log in to erogemusicquiz.com
2. Open DevTools (F12) → Application → Cookies
3. Find `session-token` and `user-id` cookies
4. Copy values to `cookies_rename.json`
5. Rename to `cookies.json`

## Technical Details

### Media Download
- Uses session cookies from `cookies.json` for authentication
- Downloads to `media/` folder (persistent cache)
- Supports video (`.webm`, `.mp4`, etc.) and audio (`.mp3`, `.ogg`, etc.)
- Skips already-downloaded files unless `--force-render`

### Video Rendering
- Resolution: 1920x1080 (configurable)
- FPS: 30 (configurable)
- Codec: H.264 (via FFmpeg)
- Glassmorphism UI design with frosted panels
- Custom font loading (Latin and Japanese)
- CJK text wrapping support

### Overlay Design
- **Left panel**: Video/audio preview with progress bar
- **Bottom bar**: Song credits with type badge (OP/ED/etc)
- **Right panel**: Rank number and participant grid (party mode)
- **Background**: Blurred cover art with bokeh effects

### Color Scheme
- Background: `#121212`
- Panel: `rgba(30,30,46,0.75)`
- Accent Violet: `#8B5CF6`
- Accent Pink: `#EC4899`
- Type colors: OP (yellow), ED (cyan), INS (blue), BGM (purple)

## Development Guidelines

### Code Style
- Follow existing patterns in the codebase
- Use descriptive variable names
- Keep functions focused and modular
- Add comments for complex logic

### Testing
- Use `generate_test_data.py` to create test playlists
- Test with small playlists first (5-10 songs)
- Verify cookie authentication before large renders

### Common Issues
- **Cookie errors**: Ensure `cookies.json` has valid session tokens
- **FFmpeg not found**: Install FFmpeg and add to PATH
- **Memory issues**: `build_db.py` streams data, but `render_video.py` loads full images
- **Font issues**: Falls back to PIL default if fonts not found

### File Locations
- Media cache: `media/` (gitignored)
- Temporary dumps: system temp directory
- Output video: `ranking.mp4` (gitignored)

## Behavioral Guidelines

This project follows the principles in `behavior.md`:
1. **Think Before Coding**: State assumptions, ask when unclear
2. **Simplicity First**: Minimum code, no speculative features
3. **Surgical Changes**: Touch only what's necessary
4. **Goal-Driven Execution**: Define success criteria, verify results

## External APIs

### EMQ API
- Base URL: `https://erogemusicquiz.com`
- Dump URL: `https://dl.erogemusicquiz.com/dump/song/`
- Requires authentication via cookies

### VNDB API
- Base URL: `https://api.vndb.org/kana/vn`
- Used by `generate_test_data.py` for metadata
- Rate limiting: 1 second between requests

## Video Rendering Pipeline

1. **Parse playlist**: Load `playlist.json` and validate entries
2. **Download media**: Fetch video/audio files using cookies
3. **Load cover art**: Download VNDB cover images
4. **Generate overlays**: Create PNG frames for each song
5. **Encode video**: Use FFmpeg to combine media and overlays
6. **Add transitions**: Crossfade between clips
7. **Output**: Save final video to `ranking.mp4`

## Party Mode Rendering

Additional steps for party mode:
1. **Load score files**: Parse `scores_*.json` files
2. **Calculate averages**: Compute average score per song
3. **Sort by average**: Reorder songs by average score
4. **Render participant grid**: Show avatars and individual scores
5. **Color-code rings**: Pink for highest, violet for lowest

## Troubleshooting

### Build Database Issues
- **Download fails**: Check internet connection, try manual download
- **7-Zip not found**: Install 7-Zip or provide extracted dump
- **Column mismatch**: Dump format may have changed

### Rendering Issues
- **Media download fails**: Check cookies.json, verify session is active
- **FFmpeg errors**: Ensure FFmpeg is installed and in PATH
- **Font errors**: System will use fallback fonts
- **Memory errors**: Reduce resolution or clip duration

### Browser UI Issues
- **Search not working**: Ensure db.json exists and is valid
- **Drag-drop not working**: Check browser compatibility
- **Export fails**: Check browser console for errors

## Future Enhancements

Potential areas for improvement:
- Add video preview in browser UI
- Support for custom themes/skins
- Batch processing of multiple playlists
- Cloud storage integration for media cache
- Real-time collaboration for party mode
- Mobile-responsive UI
- Additional output formats (GIF, WebM)
