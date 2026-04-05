#!/usr/bin/env python3
"""
EMQ Ranking Builder — Database Builder
=======================================
Reads a single plain-text PostgreSQL dump and outputs a compact db.json.
Prioritizes shortest video > shortest audio > any other media.
"""

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.error
import subprocess
import tempfile
import shutil
import os
from pathlib import Path
from datetime import datetime


# ── Tables we need (all others are skipped while streaming) ──────────────────
NEEDED = {
    "music_title": [
        "music_id", "latin_title", "non_latin_title", "language", "is_main_title"
    ],
    "music_external_link": [
        "music_id", "url", "type", "is_video", "duration",
        "submitted_by", "sha256", "analysis_raw"
    ],
    "music_source_music": [
        "music_source_id", "music_id", "type"
    ],
    "music_source_title": [
        "music_source_id", "latin_title", "non_latin_title", "language", "is_main_title"
    ],
    "music_source_external_link": [
        "music_source_id", "url", "type", "name"
    ],
    "artist_music": [
        "artist_id", "music_id", "role", "artist_alias_id"
    ],
    "artist_alias": [
        "id", "artist_id", "latin_alias", "non_latin_alias", "is_main_name"
    ],
}

# Internal hostname in the dump → public URL
URL_REPLACE_FROM = "https://emqselfhost"
URL_REPLACE_TO   = "https://erogemusicquiz.com"

# Song type and role constants
TYPE_LABEL = {1: "Opening", 2: "Ending", 3: "Insert Song", 4: "BGM"}
ROLE_ORDER  = [1, 6, 2, 5, 3, 4]

# Download settings
BASE_URL = "https://dl.erogemusicquiz.com/dump/song/"
ZSTD_EXT = ".txt.zst"


def parse_duration(duration_str: str) -> float:
    """
    Parse duration string like '00:04:07.379' or '00:03:25.27' to seconds.
    Returns float or 9999 if parsing fails.
    """
    if not duration_str:
        return 9999
    
    try:
        # Handle format: HH:MM:SS.ms or MM:SS.ms
        parts = duration_str.split(':')
        if len(parts) == 3:
            h, m, s = parts
            seconds = int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            seconds = int(m) * 60 + float(s)
        else:
            seconds = float(duration_str)
        return seconds
    except (ValueError, AttributeError):
        return 9999


def duration_to_str(seconds: float) -> str:
    """Convert seconds back to HH:MM:SS.ms format"""
    if seconds >= 9999:
        return ""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    else:
        return f"{minutes:02d}:{secs:06.3f}"


# ── Download and extraction functions ─────────────────────────────────────────
def get_todays_filename() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return f"public_pgdump_{today}_EMQ@localhost.txt.zst"


def get_todays_url() -> str:
    filename = get_todays_filename()
    encoded_filename = filename.replace("@", "%40")
    return f"{BASE_URL}{encoded_filename}"


def check_7zip() -> bool:
    for cmd in ["7z", "7za"]:
        try:
            result = subprocess.run(
                [cmd, "--help"],
                capture_output=True,
                timeout=5,
                shell=True if os.name == "nt" else False
            )
            if result.returncode == 0:
                return True
        except (subprocess.SubprocessError, FileNotFoundError):
            continue
    return False


def extract_zst_with_7z(zst_path: Path, output_dir: Path, verbose: bool) -> bool:
    if not check_7zip():
        if verbose:
            print("  ⚠ 7-Zip not found. Please install 7-Zip or use a local dump file.")
        return False
    
    cmd = ["7z", "e", str(zst_path), f"-o{output_dir}", "-y"]
    if verbose:
        print(f"  Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return True
        else:
            if verbose:
                print(f"  7-Zip error: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        if verbose:
            print("  Extraction timed out after 5 minutes")
        return False
    except Exception as e:
        if verbose:
            print(f"  Extraction error: {e}")
        return False


def download_file(url: str, dest_path: Path, verbose: bool) -> bool:
    try:
        if verbose:
            print(f"  Downloading: {url}")
            print(f"  To: {dest_path}")
        
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "EMQ-Ranking-Builder/1.0", "Accept": "*/*"}
        )
        
        with urllib.request.urlopen(req, timeout=60) as response:
            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            
            with open(dest_path, "wb") as out_file:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    downloaded += len(chunk)
                    if verbose and total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"\r    Progress: {percent:.1f}% ({downloaded/1024/1024:.1f} MB / {total_size/1024/1024:.1f} MB)", end="", flush=True)
            
            if verbose:
                print()
        
        return dest_path.exists() and dest_path.stat().st_size > 0
    
    except Exception as e:
        if verbose:
            print(f"\n  Download error: {e}")
        return False


def get_dump_file(dump_arg: str | None, verbose: bool) -> Path | None:
    if dump_arg:
        dump_path = Path(dump_arg)
        if dump_path.exists():
            if verbose:
                print(f"  Using local dump: {dump_path}")
            return dump_path
        else:
            print(f"  ERROR: Local file not found: {dump_path}")
            return None
    
    print("\n  No local dump provided. Attempting to download latest dump...")
    
    filename = get_todays_filename()
    zst_path = Path(tempfile.gettempdir()) / filename
    txt_filename = filename.replace(".zst", "")
    txt_path = Path(tempfile.gettempdir()) / txt_filename
    
    if zst_path.exists():
        age_hours = (datetime.now() - datetime.fromtimestamp(zst_path.stat().st_mtime)).total_seconds() / 3600
        if age_hours < 24:
            if verbose:
                print(f"  Found recent download: {zst_path} ({age_hours:.1f} hours old)")
            if txt_path.exists():
                if verbose:
                    print(f"  Using previously extracted file: {txt_path}")
                return txt_path
        else:
            if verbose:
                print(f"  Download is {age_hours:.1f} hours old, re-downloading...")
            zst_path.unlink()
    
    url = get_todays_url()
    if verbose:
        print(f"  Today's dump: {filename}")
        print(f"  Download URL: {url}")
    
    if not download_file(url, zst_path, verbose):
        print(f"  ERROR: Failed to download {url}")
        return None
    
    print(f"  Downloaded: {zst_path.name} ({zst_path.stat().st_size / 1024 / 1024:.1f} MB)")
    
    if not check_7zip():
        print("\n  ERROR: 7-Zip not found. Please install 7-Zip or provide a local dump file.")
        print("  Download 7-Zip from: https://www.7-zip.org/")
        return None
    
    print(f"  Extracting {filename}...")
    if extract_zst_with_7z(zst_path, Path(tempfile.gettempdir()), verbose):
        if txt_path.exists():
            print(f"  Extracted: {txt_filename} ({txt_path.stat().st_size / 1024 / 1024:.1f} MB)")
            zst_path.unlink()
            if verbose:
                print(f"  Deleted: {zst_path.name}")
            return txt_path
        else:
            print(f"  ERROR: Extraction completed but {txt_filename} not found")
            return None
    else:
        print("  ERROR: Extraction failed")
        return None


def cleanup_temp_file(file_path: Path, verbose: bool):
    if file_path and file_path.exists():
        try:
            file_path.unlink()
            if verbose:
                print(f"  Deleted: {file_path.name}")
        except Exception as e:
            if verbose:
                print(f"  Warning: Could not delete {file_path.name}: {e}")


# ── Streaming parser ──────────────────────────────────────────────────────────
def stream_tables(path: Path, verbose: bool):
    copy_re = re.compile(r"^COPY public\.(\w+)\s*\(([^)]+)\)\s*FROM stdin;", re.IGNORECASE)

    current_table = None
    current_cols = None
    current_schema = None
    col_map = None
    rows_parsed = 0

    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n").rstrip("\r")

            if line == "\\.":
                if current_table and verbose:
                    print(f"    {current_table}: {rows_parsed:,} rows")
                current_table = None
                current_cols = None
                current_schema = None
                col_map = None
                rows_parsed = 0
                continue

            if current_table is not None:
                if not line:
                    continue
                parts = line.split("\t")
                row = {}
                for schema_i, file_i in enumerate(col_map):
                    raw = parts[file_i] if file_i < len(parts) else ""
                    row[current_schema[schema_i]] = "" if raw == "\\N" else raw
                rows_parsed += 1
                yield current_table, row
                continue

            m = copy_re.match(line)
            if not m:
                continue

            tname = m.group(1)
            if tname not in NEEDED:
                continue

            file_cols = [c.strip() for c in m.group(2).split(",")]
            schema_cols = NEEDED[tname]

            col_map_built = []
            ok = True
            for sc in schema_cols:
                try:
                    col_map_built.append(file_cols.index(sc))
                except ValueError:
                    print(f"  ⚠  Column '{sc}' not found in {tname} dump columns: {file_cols}")
                    ok = False
                    break

            if not ok:
                print(f"  ⚠  Skipping {tname} due to column mismatch")
                continue

            current_table = tname
            current_cols = file_cols
            current_schema = schema_cols
            col_map = col_map_built
            rows_parsed = 0

            if verbose:
                print(f"  → Streaming {tname} …")


# ── Build indexes from streamed rows ──────────────────────────────────────────
def build_db(dump_path: Path, verbose: bool):
    print(f"\n{'='*60}")
    print("  EMQ Ranking Builder — build_db.py")
    print(f"{'='*60}\n")

    size_mb = dump_path.stat().st_size / 1024 / 1024
    print(f"  Input:  {dump_path}  ({size_mb:.0f} MB)")
    print(f"  Mode:   streaming line-by-line (low memory)\n")

    if verbose:
        print("  Streaming tables:")

    t0 = time.time()

    # Data structures
    alias_idx: dict[str, dict] = {}
    am_idx: dict[str, list] = {}
    src_title_idx: dict[str, dict] = {}
    src_vndb_idx: dict[str, str] = {}
    msm_idx: dict[str, dict] = {}
    
    # Store ALL media links per song, then choose best one
    media_links: dict[str, list] = {}  # music_id -> list of (type, is_video, duration_sec, url)
    title_rows: list[dict] = []

    tables_found: set[str] = set()
    row_counts: dict[str, int] = {t: 0 for t in NEEDED}

    for tname, row in stream_tables(dump_path, verbose):
        tables_found.add(tname)
        row_counts[tname] += 1

        if tname == "artist_alias":
            alias_idx[row["id"]] = {
                "n": row["latin_alias"],
                "nj": row["non_latin_alias"],
            }

        elif tname == "artist_music":
            mid = row["music_id"]
            if mid not in am_idx:
                am_idx[mid] = []
            am_idx[mid].append({"a": row["artist_alias_id"], "r": row["role"]})

        elif tname == "music_source_title":
            sid = row["music_source_id"]
            if row["is_main_title"] == "t" or sid not in src_title_idx:
                src_title_idx[sid] = {
                    "gt": row["latin_title"],
                    "gtj": row["non_latin_title"],
                }

        elif tname == "music_source_external_link":
            if row["type"] == "1":
                m = re.search(r"vndb\.org/(v\d+)", row["url"])
                if m:
                    sid = row["music_source_id"]
                    if sid not in src_vndb_idx:
                        src_vndb_idx[sid] = m.group(1)

        elif tname == "music_source_music":
            mid = row["music_id"]
            if mid not in msm_idx:
                msm_idx[mid] = {
                    "s": row["music_source_id"],
                    "st": int(row["type"]) if row["type"].isdigit() else 0,
                }

        elif tname == "music_external_link":
            mid = row["music_id"]
            # Type 2 = audio, Type 1 = video? Let's check both
            media_type = int(row["type"]) if row["type"].isdigit() else 0
            is_video = row["is_video"] == "t"
            duration_sec = parse_duration(row["duration"])
            url = row["url"].replace(URL_REPLACE_FROM, URL_REPLACE_TO)
            
            if mid not in media_links:
                media_links[mid] = []
            
            media_links[mid].append({
                "type": media_type,
                "is_video": is_video,
                "duration": duration_sec,
                "duration_str": row["duration"],
                "url": url,
                "submitted_by": row.get("submitted_by", "")
            })

        elif tname == "music_title":
            if row["is_main_title"] == "t":
                title_rows.append(row)

    elapsed = time.time() - t0

    print(f"\n  Streaming complete in {elapsed:.1f}s\n")
    missing = set(NEEDED) - tables_found
    if missing:
        print(f"  ⚠  Tables NOT found in dump: {', '.join(sorted(missing))}\n")
    else:
        print("  All 7 needed tables found.\n")

    print("  Row counts:")
    for t, n in sorted(row_counts.items()):
        mark = "✓" if n > 0 else "✗"
        print(f"    {mark}  {t:<35} {n:>8,}")

    if not title_rows:
        print("\nERROR: music_title has no main-title rows. Cannot build db.json.")
        sys.exit(1)

    # ── Join song records with best media selection ───────────────────────────
    print(f"\n  Joining {len(title_rows):,} song records…")
    print("  Media selection priority: shortest video > shortest audio > any other")
    
    songs: list[dict] = []
    seen_ids: set[str] = set()

    for row in title_rows:
        mid = row["music_id"]
        if mid in seen_ids:
            continue
        seen_ids.add(mid)

        src = msm_idx.get(mid, {})
        sid = src.get("s")
        st = src.get("st", 0)
        src_t = src_title_idx.get(sid, {}) if sid else {}
        vndb_id = src_vndb_idx.get(sid) if sid else None
        
        # Select best media link
        best_media = None
        links = media_links.get(mid, [])
        
        if links:
            # Separate by type
            videos = [l for l in links if l["is_video"]]
            audios = [l for l in links if not l["is_video"] and l["type"] == 2]
            
            # Priority 1: Shortest video
            if videos:
                videos.sort(key=lambda x: x["duration"])
                best_media = videos[0]
                if verbose:
                    print(f"    Song {mid}: selected video ({best_media['duration_str']}) over {len(videos)} video(s)")
            
            # Priority 2: Shortest audio
            elif audios:
                audios.sort(key=lambda x: x["duration"])
                best_media = audios[0]
                if verbose:
                    print(f"    Song {mid}: selected audio ({best_media['duration_str']}) over {len(audios)} audio(s)")
            
            # Priority 3: Any other link
            else:
                links.sort(key=lambda x: x["duration"])
                best_media = links[0]
                if verbose:
                    print(f"    Song {mid}: selected other media ({best_media['duration_str']})")

        # Build artists list
        artist_entries = am_idx.get(mid, [])
        artists: list[dict] = []
        seen_alias_role: set[tuple] = set()
        for e in artist_entries:
            aid = e["a"]
            role = int(e["r"]) if e["r"].isdigit() else 0
            if (aid, role) in seen_alias_role:
                continue
            seen_alias_role.add((aid, role))
            al = alias_idx.get(aid)
            if al and al["n"]:
                entry: dict = {"n": al["n"], "r": role}
                if al["nj"]:
                    entry["nj"] = al["nj"]
                artists.append(entry)

        song: dict = {
            "id": mid,
            "t": row["latin_title"],
            "tj": row["non_latin_title"],
            "gt": src_t.get("gt", ""),
            "gtj": src_t.get("gtj", ""),
            "st": st,
            "vid": vndb_id,
            "ar": artists,
        }
        
        # Add best media if found
        if best_media:
            song["au"] = best_media["url"]
            song["ad"] = best_media["duration_str"]
            # Also track if it's video for debugging
            if best_media["is_video"]:
                song["is_video"] = True

        # Strip empty/null optional fields to save space
        for k in ("tj", "gtj", "vid", "au", "ad"):
            if not song.get(k):
                song.pop(k, None)
        if not song.get("ar"):
            song.pop("ar", None)

        songs.append(song)

    print(f"  Built {len(songs):,} songs.")

    # Stats
    has_vndb = sum(1 for s in songs if s.get("vid"))
    has_audio = sum(1 for s in songs if s.get("au"))
    has_video = sum(1 for s in songs if s.get("is_video"))
    has_ar = sum(1 for s in songs if s.get("ar"))
    
    print(f"\n  Coverage:")
    print(f"    VNDB IDs   : {has_vndb:>8,} / {len(songs):,}")
    print(f"    Media URLs : {has_audio:>8,} / {len(songs):,}")
    print(f"      - Video  : {has_video:>8,}")
    print(f"      - Audio  : {has_audio - has_video:>8,}")
    print(f"    Artists    : {has_ar:>8,} / {len(songs):,}")

    return {
        "version": 1,
        "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(songs),
        "songs": songs,
    }


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description="Build db.json from a plain-text pg_dump SQL file (auto-downloads latest dump)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("dump", nargs="?", metavar="dump.txt", default=None,
                    help="Plain-text pg_dump file (optional - if omitted, downloads latest dump)")
    ap.add_argument("--out", default="db.json", metavar="FILE",
                    help="Output path (default: db.json)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Print table names as they are streamed")
    args = ap.parse_args()

    dump_path = get_dump_file(args.dump, args.verbose)
    if not dump_path:
        sys.exit(1)

    is_temp = args.dump is None
    temp_dump_path = dump_path if is_temp else None

    try:
        db = build_db(dump_path, args.verbose)

        out_path = Path(args.out)
        print(f"\n  Writing {out_path} …", end="", flush=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, separators=(",", ":"))
        size_mb = out_path.stat().st_size / 1024 / 1024
        print(f" done  ({size_mb:.1f} MB)")

        print(f"\n{'='*60}")
        print(f"  ✓  {out_path}  ({size_mb:.1f} MB, {db['count']:,} songs)")
        print(f"{'='*60}")
        print(f"\n  → Place db.json alongside index.html in your GitHub repo.\n")

    finally:
        if temp_dump_path and temp_dump_path.exists():
            cleanup_temp_file(temp_dump_path, args.verbose)


if __name__ == "__main__":
    main()