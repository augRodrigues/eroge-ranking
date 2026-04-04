#!/usr/bin/env python3
"""
EMQ Ranking Builder — Database Builder
=======================================
Reads the ErogeMusicQuiz pg_dump files and outputs a compact db.json
file for use with the ranking web app.

Usage:
    python build_db.py /path/to/dump/directory
    python build_db.py /path/to/dump/directory --out db.json
    python build_db.py file1.dat file2.dat file3.dat ...

The script auto-detects which table each .dat (or .txt) block contains,
so you do NOT need to know the file numbering.

Output: db.json  (place alongside index.html in your GitHub Pages repo)
"""

import sys, os, re, json, argparse, time
from pathlib import Path

# ── Schemas (column order matches pg_dump COPY output) ──────
SCHEMAS = {
    'artist':                     ['id', 'primary_language'],
    'artist_alias':               ['id', 'artist_id', 'latin_alias', 'non_latin_alias', 'is_main_name'],
    'artist_music':               ['artist_id', 'music_id', 'role', 'artist_alias_id'],
    'category':                   ['id', 'name', 'type', 'vndb_id'],
    'music':                      ['id', 'type', 'attributes', 'data_source'],
    'music_external_link':        ['music_id', 'url', 'type', 'is_video', 'duration',
                                   'submitted_by', 'sha256', 'analysis_raw'],
    'music_source_external_link': ['music_source_id', 'url', 'type', 'name'],
    'music_source_music':         ['music_source_id', 'music_id', 'type'],
    'music_source_title':         ['music_source_id', 'latin_title', 'non_latin_title',
                                   'language', 'is_main_title'],
    'music_title':                ['music_id', 'latin_title', 'non_latin_title',
                                   'language', 'is_main_title'],
    'artist_artist':              ['source', 'target', 'rel'],
}

# Internal URL prefix → public
_URL_IN  = 'https://emqselfhost'
_URL_OUT = 'https://erogemusicquiz.com'

NEEDED_TABLES = {
    'artist_alias', 'artist_music',
    'music_title', 'music_external_link',
    'music_source_music', 'music_source_title',
    'music_source_external_link',
}


# ────────────────────────────────────────────────────────────
#  TSV parsing
# ────────────────────────────────────────────────────────────
def parse_block(text, col_names):
    rows = []
    n = len(col_names)
    for line in text.splitlines():
        if not line or line == '\\.':
            continue
        parts = line.split('\t', n - 1)
        while len(parts) < n:
            parts.append('')
        obj = {}
        for i, col in enumerate(col_names):
            v = parts[i]
            obj[col] = '' if v == '\\N' else v
        rows.append(obj)
    return rows


def split_blocks(text):
    """Split a file that may contain multiple COPY blocks (separated by \\.)."""
    parts = re.split(r'\n\\\.[ \t]*(?:\n|$)', text)
    return [p.strip() for p in parts if p.strip()]


# ────────────────────────────────────────────────────────────
#  Table auto-detection
# ────────────────────────────────────────────────────────────
def _sample(block_text, n=40):
    """Return up to n parsed rows from a block."""
    lines = [l for l in block_text.splitlines() if l and l != '\\.'][:n]
    return [l.split('\t') for l in lines]

def _is_int(s):   s=s.strip(); return bool(s) and re.fullmatch(r'\d+', s) is not None
def _is_bool(s):  return s.strip() in ('t', 'f')
def _is_url(s):   return s.startswith('http://') or s.startswith('https://')
def _is_lang(s):  s=s.strip(); return bool(s) and re.fullmatch(r'[a-z]{2}(-[A-Za-z]{2,5})?', s) is not None
def _is_uuid(s):  return bool(re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', s.strip()))
def _is_hms(s):   return bool(re.match(r'^\d{2}:\d{2}:\d{2}', s.strip()))

def _col(rows, i):
    return [r[i] for r in rows if len(r) > i]


def detect_table(block_text):
    """
    Return (table_name, confidence_pct) based on content fingerprints.
    Returns (None, 0) when unrecognized.
    """
    rows = _sample(block_text)
    if len(rows) < 2:
        return None, 0
    ncols = max(len(r) for r in rows)

    c = [_col(rows, i) for i in range(min(ncols, 10))]

    def pct(vals, fn, n=20):
        sub = vals[:n]
        return sum(1 for v in sub if fn(v)) / len(sub) if sub else 0

    # 2-column: artist
    if ncols == 2:
        if pct(c[0], _is_int) > 0.9 and pct(c[1], _is_lang) > 0.7:
            return 'artist', 95
        return None, 0

    # 3-column
    if ncols == 3:
        all_int_c0 = pct(c[0], _is_int) > 0.85
        all_int_c1 = pct(c[1], _is_int) > 0.85
        all_int_c2 = pct(c[2], _is_int) > 0.85
        all_int = all_int_c0 and all_int_c1 and all_int_c2
        if all_int:
            c2_ints = [int(v.strip()) for v in c[2] if _is_int(v)]
            c1_ints = [int(v.strip()) for v in c[1] if _is_int(v)]
            if c2_ints:
                # music_source_music: majority of type values are 1-6
                small_pct = sum(1 for v in c2_ints if v <= 6) / len(c2_ints)
                if small_pct > 0.7 and (not c1_ints or max(c1_ints) > 100):
                    return 'music_source_music', 92
                # artist_artist: rel col is a consistently large code like 103
                if sum(1 for v in c2_ints if v > 10) / len(c2_ints) > 0.8:
                    return 'artist_artist', 88
        # UUID-based → MusicBrainz (skip)
        if pct(c[1], _is_uuid) > 0.7:
            return 'musicbrainz_skip', 80
        return None, 0

    # 4-column
    if ncols == 4:
        # music_source_external_link: (src_id, url, type, name)
        if pct(c[0], _is_int) > 0.9 and pct(c[1], _is_url) > 0.8:
            return 'music_source_external_link', 93

        # artist_music: 4 ints, role col in 1-9
        if all(pct(c[i], _is_int) > 0.9 for i in range(4)):
            roles = [int(v) for v in c[2] if _is_int(v)]
            if roles and max(roles) <= 9:
                return 'artist_music', 90
            return 'music', 70

        # category: (id, text, int, 'g...' or empty)
        if pct(c[0], _is_int) > 0.9 and pct(c[2], _is_int) > 0.9:
            c3_sample = [v for v in c[3][:15] if v]
            if c3_sample and all(v.startswith('g') for v in c3_sample):
                return 'category', 88

        # room/quiz: UUID-keyed
        if pct(c[0], _is_uuid) > 0.8:
            return 'room_skip', 80

        # music_vote: (music_id, user_id, vote, timestamp)
        if pct(c[0], _is_int) > 0.9 and pct(c[1], _is_int) > 0.9:
            if any('+' in v or re.search(r'\d{4}-\d{2}-\d{2}', v) for v in c[3][:5]):
                return 'music_vote_skip', 75

        return None, 0

    # 5-column
    if ncols == 5:
        # artist_alias / music_title / music_source_title all share
        # (int, text, text_or_null, lang_or_text, bool)
        if pct(c[0], _is_int) > 0.9 and pct(c[4], _is_bool) > 0.9:
            lang_score = pct(c[3], _is_lang, 30)
            if lang_score > 0.7:
                # music_title vs music_source_title: distinguish by ID range
                ids = [int(v) for v in c[0] if _is_int(v)]
                if ids and max(ids) > 15000:
                    return 'music_title', 92
                else:
                    return 'music_source_title', 90
            else:
                # col[3] is a name → artist_alias
                return 'artist_alias', 88
        return None, 0

    # 8-column (music_external_link or edit_queue/review_queue)
    if ncols >= 8:
        if pct(c[1], _is_url, 15) > 0.7 and pct(c[2], _is_int) > 0.7:
            if len(c) > 4 and pct(c[4], _is_hms, 15) > 0.6:
                return 'music_external_link', 95
        # edit_queue / review_queue: col[6] starts with JSON
        if len(rows[0]) > 6 and rows[0][6].startswith('{'):
            return 'edit_queue_skip', 80
        return None, 0

    return None, 0


# ────────────────────────────────────────────────────────────
#  File collection
# ────────────────────────────────────────────────────────────
def collect_blocks(paths, verbose):
    """Yield (block_text, source_label, block_idx) for all input paths."""
    for path in paths:
        try:
            text = Path(path).read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            if verbose:
                print(f"  ⚠  Cannot read {path}: {e}")
            continue
        blocks = split_blocks(text)
        for i, blk in enumerate(blocks):
            if blk:
                yield blk, Path(path).name, i


# ────────────────────────────────────────────────────────────
#  Main build
# ────────────────────────────────────────────────────────────
def build_db(input_paths, verbose=True):
    def log(*a): verbose and print(*a)

    log(f"\n{'═'*58}")
    log("  EMQ Ranking Builder — building db.json")
    log(f"{'═'*58}\n")

    # ── Step 1: detect + parse tables ────────────────────────
    log("Step 1/4 — Detecting and parsing tables…\n")
    tables = {}
    unrecognized = []
    t0 = time.time()

    for blk, src, idx in collect_blocks(input_paths, verbose):
        name, conf = detect_table(blk)
        lines_n = sum(1 for l in blk.splitlines() if l and l != '\\.')

        if name and name.endswith('_skip'):
            continue  # known but not needed

        if name and name in NEEDED_TABLES and name not in tables:
            schema = SCHEMAS[name]
            tables[name] = parse_block(blk, schema)
            log(f"  ✓  {name:<32} {lines_n:>8,} rows    [{src} §{idx+1}]")
        elif not name and lines_n > 50:
            unrecognized.append((lines_n, src, idx + 1, blk[:60]))

    missing = NEEDED_TABLES - set(tables.keys())
    if missing:
        log(f"\n  ⚠  Could not auto-detect: {', '.join(sorted(missing))}")
        if unrecognized:
            log("\n     Unidentified large blocks (one of these may be the missing table):")
            for sz, f, i, preview in sorted(unrecognized, reverse=True)[:6]:
                log(f"       {f} §{i}  ({sz:,} rows):  {repr(preview)}")
        if 'music_title' in missing or 'artist_alias' in missing:
            log("\n  FATAL: Cannot continue without music_title and artist_alias.")
            sys.exit(1)

    log(f"\n  Detected {len(tables)}/{len(NEEDED_TABLES)} tables in {time.time()-t0:.1f}s")

    # ── Step 2: build lookup indexes ─────────────────────────
    log("\nStep 2/4 — Building lookup indexes…")

    alias_idx = {}  # alias_id → {n, nj}
    for r in tables.get('artist_alias', []):
        alias_idx[r['id']] = {'n': r['latin_alias'], 'nj': r['non_latin_alias']}
    log(f"  artist_alias: {len(alias_idx):,}")

    am_idx = {}  # music_id → [{a, r}]
    for r in tables.get('artist_music', []):
        am_idx.setdefault(r['music_id'], []).append(
            {'a': r['artist_alias_id'], 'r': r['role']})
    log(f"  artist_music: {len(am_idx):,} songs")

    src_title_idx = {}  # source_id → {gt, gtj}
    for r in tables.get('music_source_title', []):
        sid = r['music_source_id']
        if r['is_main_title'] == 't' or sid not in src_title_idx:
            src_title_idx[sid] = {'gt': r['latin_title'], 'gtj': r['non_latin_title']}
    log(f"  music_source_title: {len(src_title_idx):,}")

    src_vndb_idx = {}  # source_id → vndb_id
    for r in tables.get('music_source_external_link', []):
        if r['type'] == '1':
            m = re.search(r'vndb\.org/(v\d+)', r['url'])
            if m and r['music_source_id'] not in src_vndb_idx:
                src_vndb_idx[r['music_source_id']] = m.group(1)
    log(f"  source→vndb: {len(src_vndb_idx):,}")

    msm_idx = {}  # music_id → {s: source_id, st: song_type}
    for r in tables.get('music_source_music', []):
        mid = r['music_id']
        if mid not in msm_idx:
            msm_idx[mid] = {
                's': r['music_source_id'],
                'st': int(r['type']) if r['type'].isdigit() else 0,
            }
    log(f"  music_source_music: {len(msm_idx):,}")

    audio_idx = {}  # music_id → {au: url, ad: duration}
    for r in tables.get('music_external_link', []):
        mid = r['music_id']
        if r['type'] == '2' and mid not in audio_idx:
            url = r['url'].replace(_URL_IN, _URL_OUT)
            audio_idx[mid] = {'au': url, 'ad': r['duration']}
    log(f"  music_external_link: {len(audio_idx):,}")

    # ── Step 3: join song records ─────────────────────────────
    log("\nStep 3/4 — Joining song records…")
    songs = []
    seen = set()

    for r in tables.get('music_title', []):
        if r['is_main_title'] != 't':
            continue
        mid = r['music_id']
        if mid in seen:
            continue
        seen.add(mid)

        src_info = msm_idx.get(mid, {})
        sid = src_info.get('s')
        st = src_info.get('st', 0)
        src_t = src_title_idx.get(sid, {}) if sid else {}
        vndb = src_vndb_idx.get(sid) if sid else None
        audio = audio_idx.get(mid, {})

        # Build artists list (deduplicate alias IDs)
        artist_list = []
        seen_alias = set()
        for e in am_idx.get(mid, []):
            aid = e['a']
            if aid in seen_alias:
                continue
            seen_alias.add(aid)
            al = alias_idx.get(aid)
            if al and al['n']:
                entry = {'n': al['n'], 'r': int(e['r']) if str(e['r']).isdigit() else 0}
                if al['nj']:
                    entry['nj'] = al['nj']
                artist_list.append(entry)

        song = {
            'id': mid,
            't':   r['latin_title'],
            'tj':  r['non_latin_title'],
            'gt':  src_t.get('gt', ''),
            'gtj': src_t.get('gtj', ''),
            'st':  st,
            'vid': vndb,
            'au':  audio.get('au'),
            'ad':  audio.get('ad'),
            'ar':  artist_list,
        }

        # Strip empty/null optional fields to save space
        for k in ('tj', 'gtj', 'vid', 'au', 'ad'):
            if not song.get(k):
                song.pop(k, None)
        if not song.get('ar'):
            song.pop('ar', None)

        songs.append(song)

    log(f"  {len(songs):,} songs built")

    # ── Step 4: output ────────────────────────────────────────
    output = {
        'version': 1,
        'built': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'count': len(songs),
        'songs': songs,
    }
    return output


# ────────────────────────────────────────────────────────────
#  CLI
# ────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description='Build db.json from EMQ pg_dump .dat files',
        epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('inputs', nargs='+',
        help='pg_dump directory, or individual .dat / .txt files')
    ap.add_argument('--out', default='db.json', metavar='FILE',
        help='Output path (default: db.json)')
    ap.add_argument('-q', '--quiet', action='store_true')
    args = ap.parse_args()

    paths = []
    for inp in args.inputs:
        p = Path(inp)
        if p.is_dir():
            dat = sorted(p.glob('*.dat'))
            if not dat:
                dat = sorted(p.glob('*.txt'))
            paths.extend(dat)
            if not args.quiet:
                print(f"  Directory {p}: {len(dat)} file(s)")
        elif p.is_file():
            paths.append(p)
        else:
            print(f"Warning: {inp} not found", file=sys.stderr)

    if not paths:
        print("Error: no input files found.", file=sys.stderr)
        sys.exit(1)

    db = build_db(paths, verbose=not args.quiet)

    out = Path(args.out)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, separators=(',', ':'))

    size_mb = out.stat().st_size / 1024 / 1024
    if not args.quiet:
        print(f"\n{'═'*58}")
        print(f"  ✓ {out}  —  {size_mb:.1f} MB  —  {db['count']:,} songs")
        print(f"{'═'*58}")
        print(f"\n  → Copy db.json alongside index.html in your GitHub repo\n")


if __name__ == '__main__':
    main()
