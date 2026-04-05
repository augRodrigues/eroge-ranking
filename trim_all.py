import glob
import os

EXTRACTS = [
    {
        "start": "COPY public.quiz_song_history (quiz_id, sp, music_id, user_id, guess, first_guess_ms, is_correct, is_on_list, played_at, guess_kind, start_time, duration) FROM stdin;",
        "output": "songhistorydump.txt",
    },
    {
        "start": "COPY public.music_source_music (music_source_id, music_id, type) FROM stdin;",
        "output": "music_source_music_dump.txt",
    },
    {
        "start": "COPY public.music_source_title (music_source_id, latin_title, non_latin_title, language, is_main_title) FROM stdin;",
        "output": "music_source_title_dump.txt",
    },
    {
        "start": "COPY public.music_title (music_id, latin_title, non_latin_title, language, is_main_title) FROM stdin;",
        "output": "music_title_dump.txt",
    },
    {
        "start": "COPY public.music_source_external_link (music_source_id, url, type, name) FROM stdin;",
        "output": "music_source_external_link_dump.txt",
    },
        {
        "start": "COPY public.artist_alias (id, artist_id, latin_alias, non_latin_alias, is_main_name) FROM stdin;",
        "output": "artist_alias_dump.txt",
    },
        {
        "start": "COPY public.artist_music (artist_id, music_id, role, artist_alias_id) FROM stdin;",
        "output": "artist_music_dump.txt",
    },
]

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


def find_end(content, start_idx):
    """Find the index of the first standalone \\. line after start_idx."""
    lines = content[start_idx:].split("\n")
    offset = 0
    for line in lines:
        if line.strip() == "\\.":
            return start_idx + offset
        offset += len(line) + 1
    return -1


def trim_all():
    matches = glob.glob("public_pgdump*.txt")
    if not matches:
        print("No file matching 'public_pgdump*.txt' found in the current directory.")
        return

    filepath = matches[0]
    print(f"Found file: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    for extract in EXTRACTS:
        start_line = extract["start"]
        output_path = extract["output"]

        start_idx = content.find(start_line)
        if start_idx == -1:
            print(f"ERROR: Start marker not found for '{output_path}', skipping.")
            continue

        end_idx = find_end(content, start_idx)
        if end_idx == -1:
            print(f"ERROR: End marker not found for '{output_path}', skipping.")
            continue

        trimmed = content[start_idx:end_idx]

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(trimmed)

        print(f"Written: {output_path}")

    print("\nAll done!")


if __name__ == "__main__":
    trim_all()
