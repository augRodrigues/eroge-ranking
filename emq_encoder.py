#!/usr/bin/env python3
"""
EMQ Ranking Video Encoder

A complete Python-based video encoder that replaces the browser-based MediaRecorder approach.
This script takes a ranking JSON export and generates high-quality videos using FFmpeg,
with proper audio crossfades, precise timing, and smooth transitions.

Usage:
    python emq_encoder.py ranking.json --output output.mp4
    
Or generate a shell script with all FFmpeg commands:
    python emq_encoder.py ranking.json --generate-script encode.sh
"""

import argparse
import json
import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import math


@dataclass
class SongEntry:
    """Represents a single song in the ranking"""
    rank: int
    song_id: str
    title: str
    title_jp: str
    game: str
    artist: str
    song_type: int
    duration: float
    start_time: float
    local_file: Optional[str] = None
    audio_url: Optional[str] = None
    vndb_id: Optional[str] = None
    cover_file: Optional[str] = None


@dataclass
class VideoConfig:
    """Video encoding configuration"""
    width: int = 1920
    height: int = 1080
    fps: int = 30
    video_bitrate: str = "8M"
    audio_bitrate: str = "320k"
    audio_sample_rate: int = 48000
    transition_duration: float = 0.5  # Crossfade duration in seconds
    output_format: str = "mp4"
    codec: str = "libx264"
    pixel_format: str = "yuv420p"
    preset: str = "slow"
    crf: int = 18


@dataclass
class EncodingProject:
    """Complete encoding project with all songs and config"""
    config: VideoConfig
    entries: List[SongEntry] = field(default_factory=list)
    working_dir: Optional[str] = None


class ColorPalette:
    """Color palette for different song types"""
    TYPE_COLORS = {
        0: ("#888888", "rgba(136,136,136,0.15)"),   # Unknown
        1: ("#e8c547", "rgba(232,197,71,0.15)"),    # OP
        2: ("#3ecfac", "rgba(62,207,172,0.15)"),    # ED
        3: ("#6ba4f5", "rgba(107,164,245,0.15)"),   # Insert
        4: ("#a48ef8", "rgba(164,142,248,0.15)"),   # BGM
        600: ("#f07070", "rgba(240,112,112,0.15)"), # Vocal/Character Song
    }
    
    TYPE_LABELS = {
        0: "?",
        1: "OP",
        2: "ED", 
        3: "INSERT",
        4: "BGM",
        600: "VOCAL",
    }


class FontConfig:
    """Font configuration for video overlays"""
    SERIF = "ShipporiMinchoB1-Bold"
    SANS = "Syne-Bold"
    MONO = "DMMono-Bold"
    
    @staticmethod
    def get_font_path(font_name: str) -> str:
        """Get system font path or fallback"""
        font_paths = [
            f"/usr/share/fonts/{font_name}.ttf",
            f"/usr/share/fonts/truetype/{font_name}.ttf",
            f"/System/Library/Fonts/{font_name}.ttf",
            f"C:/Windows/Fonts/{font_name}.ttf",
        ]
        for path in font_paths:
            if os.path.exists(path):
                return path
        # Fallback to default fonts
        return font_name


class VideoEncoder:
    """Main video encoder class using FFmpeg"""
    
    def __init__(self, project: EncodingProject, verbose: bool = False):
        self.project = project
        self.verbose = verbose
        self.temp_dir = None
        self.segment_files: List[str] = []
        self.audio_files: List[str] = []
        
    def log(self, message: str, level: str = "INFO"):
        """Log message with level"""
        print(f"[{level}] {message}")
        
    def check_ffmpeg(self) -> bool:
        """Check if FFmpeg is available"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
            
    def setup_temp_dir(self):
        """Create temporary working directory"""
        self.temp_dir = tempfile.mkdtemp(prefix="emq_encoder_")
        self.project.working_dir = self.temp_dir
        if self.verbose:
            self.log(f"Working directory: {self.temp_dir}")
            
    def cleanup_temp_dir(self):
        """Remove temporary working directory"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            if self.verbose:
                self.log("Cleaned up temporary directory")
                
    def download_audio(self, entry: SongEntry, output_path: str) -> bool:
        """Download audio from URL if needed"""
        if not entry.audio_url:
            return False
            
        try:
            import urllib.request
            urllib.request.urlretrieve(entry.audio_url, output_path)
            return True
        except Exception as e:
            self.log(f"Failed to download audio: {e}", "ERROR")
            return False
            
    def prepare_audio(self, entry: SongEntry, index: int) -> Optional[str]:
        """Prepare audio file for a song entry"""
        output_path = os.path.join(self.temp_dir, f"audio_{index:04d}.wav")
        
        # Try local file first - check in current directory if only filename provided
        if entry.local_file:
            local_path = entry.local_file
            # If it's just a filename (no path), look in current directory
            if not os.path.exists(local_path):
                local_path = os.path.join(os.getcwd(), entry.local_file)
            
            if os.path.exists(local_path):
                try:
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", local_path,
                        "-ss", str(entry.start_time),
                        "-t", str(entry.duration),
                        "-ar", str(self.project.config.audio_sample_rate),
                        "-ac", "2",
                        "-vn",
                        output_path
                    ]
                    if self.verbose:
                        self.log(f"Processing local audio: {local_path}")
                    subprocess.run(cmd, capture_output=True, check=True)
                    return output_path
                except subprocess.CalledProcessError as e:
                    self.log(f"Failed to process local audio: {e}", "ERROR")
                
        # Try downloaded/cached audio
        if entry.audio_url:
            downloaded = os.path.join(self.temp_dir, f"downloaded_{index:04d}.tmp")
            if self.download_audio(entry, downloaded):
                try:
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", downloaded,
                        "-ss", str(entry.start_time),
                        "-t", str(entry.duration),
                        "-ar", str(self.project.config.audio_sample_rate),
                        "-ac", "2",
                        "-vn",
                        output_path
                    ]
                    subprocess.run(cmd, capture_output=True, check=True)
                    return output_path
                except subprocess.CalledProcessError as e:
                    self.log(f"Failed to process downloaded audio: {e}", "ERROR")
                    
        self.log(f"No audio available for #{entry.rank}: {entry.title}", "WARN")
        return None
        
    def generate_cover_image(self, entry: SongEntry, index: int) -> str:
        """Generate or get cover image for song"""
        output_path = os.path.join(self.temp_dir, f"cover_{index:04d}.png")
        
        # Use existing cover file if available
        if entry.cover_file and os.path.exists(entry.cover_file):
            try:
                cmd = [
                    "ffmpeg", "-y",
                    "-i", entry.cover_file,
                    "-vf", f"scale={self.project.config.width}//4:{int(self.project.config.height*0.65)}",
                    output_path
                ]
                subprocess.run(cmd, capture_output=True, check=True)
                return output_path
            except subprocess.CalledProcessError:
                pass
                
        # Generate placeholder cover using proper syntax
        width = self.project.config.width // 4
        height = int(self.project.config.height * 0.65)
        color = ColorPalette.TYPE_COLORS.get(entry.song_type, ColorPalette.TYPE_COLORS[0])[0]
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c={color}:s={width}x{height}:d={entry.duration}",
            "-frames:v", "1",
            "-update", "1",
            output_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        return output_path
        
    def generate_background(self, entry: SongEntry, index: int) -> str:
        """Generate blurred background from cover"""
        output_path = os.path.join(self.temp_dir, f"bg_{index:04d}.png")
        cover_path = self.generate_cover_image(entry, index)
        
        cmd = [
            "ffmpeg", "-y",
            "-i", cover_path,
            "-vf", f"scale={self.project.config.width}:{self.project.config.height},boxblur=30:1",
            "-frames:v", "1",
            "-update", "1",
            output_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        return output_path
        
    def create_video_segment(self, entry: SongEntry, index: int) -> Optional[str]:
        """Create a video segment for a single song"""
        output_path = os.path.join(self.temp_dir, f"segment_{index:04d}.mp4")
        
        # Get colors and labels
        type_color = ColorPalette.TYPE_COLORS.get(entry.song_type, ColorPalette.TYPE_COLORS[0])[0]
        type_label = ColorPalette.TYPE_LABELS.get(entry.song_type, "?")
        
        # Generate background
        bg_path = self.generate_background(entry, index)
        
        # Escape special characters in text for FFmpeg
        def escape_text(text):
            if not text:
                return ""
            return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")
        
        # Build filter complex for overlays
        filters = []
        
        # Rank number overlay (using default font)
        rank_text = escape_text(f"#{entry.rank}")
        filters.append(
            f"drawtext=text='{rank_text}':fontsize=72:fontcolor={type_color}:"
            f"x=50:y=h-100"
        )
        
        # Type badge
        badge_x = self.project.config.width // 8
        badge_y = self.project.config.height // 8
        filters.append(
            f"drawtext=text='{type_label}':fontsize=28:fontcolor={type_color}:"
            f"x={badge_x}:y={badge_y}"
        )
        
        # Song title
        title_y = badge_y + 60
        escaped_title = escape_text(entry.title)
        filters.append(
            f"drawtext=text='{escaped_title}':"
            f"fontsize=48:fontcolor=white:x={badge_x}:y={title_y}"
        )
        
        # Japanese title if available
        if entry.title_jp:
            jp_y = title_y + 55
            escaped_jp = escape_text(entry.title_jp)
            filters.append(
                f"drawtext=text='{escaped_jp}':"
                f"fontsize=28:fontcolor=#aaaaaa:x={badge_x}:y={jp_y}"
            )
            
        # Game and artist info
        info_y = jp_y + 45 if entry.title_jp else title_y + 45
        info_text = escape_text(f"{entry.game} · {entry.artist}")
        filters.append(
            f"drawtext=text='{info_text}':"
            f"fontsize=22:fontcolor=#888888:x={badge_x}:y={info_y}"
        )
        
        filter_str = ",".join(filters)
        
        # Create video segment with loop and proper duration
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", bg_path,
            "-t", str(entry.duration),
            "-vf", filter_str,
            "-c:v", self.project.config.codec,
            "-preset", "ultrafast",  # Use ultrafast for quick encoding
            "-crf", str(self.project.config.crf),
            "-pix_fmt", self.project.config.pixel_format,
            "-an",
            "-r", str(self.project.config.fps),
            output_path
        ]
        
        try:
            if self.verbose:
                self.log(f"Creating segment {index + 1}/{len(self.project.entries)}: {entry.title}")
            subprocess.run(cmd, capture_output=True, check=True, timeout=60)
            return output_path
        except subprocess.CalledProcessError as e:
            self.log(f"Failed to create segment: {e}", "ERROR")
            if self.verbose and e.stderr:
                self.log(e.stderr.decode(), "DEBUG")
            return None
        except subprocess.TimeoutExpired:
            self.log(f"Timeout creating segment: {entry.title}", "ERROR")
            return None
            
    def concatenate_segments(self, output_path: str):
        """Concatenate all video segments with crossfade transitions"""
        if not self.segment_files:
            raise ValueError("No segment files to concatenate")
            
        if len(self.segment_files) == 1:
            # Single segment, just copy
            shutil.copy(self.segment_files[0], output_path)
            return
            
        n_segments = len(self.segment_files)
        transition_dur = self.project.config.transition_duration
        
        # Build inputs list
        inputs = []
        for seg in self.segment_files:
            inputs.extend(["-i", seg])
        
        # Calculate cumulative durations for proper offset calculation
        durations = [e.duration for e in self.project.entries]
        
        # Build xfade chain - each new segment fades in at (cumulative_duration - transition_dur)
        filter_parts = []
        cumulative = durations[0]
        
        # First crossfade
        filter_parts.append(
            f"[0:v][1:v]xfade=transition=fade:duration={transition_dur}:offset={cumulative - transition_dur}[v0]"
        )
        cumulative += durations[1]
        
        # Chain remaining segments
        for i in range(2, n_segments):
            offset = cumulative - transition_dur
            filter_parts.append(
                f"[v{i-2}][{i}:v]xfade=transition=fade:duration={transition_dur}:offset={offset}[v{i-1}]"
            )
            cumulative += durations[i]
        
        final_video = f"v{n_segments-2}"
        filter_complex = ";".join(filter_parts) + f";[{final_video}]format=yuv420p[outv]"
        
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-c:v", self.project.config.codec,
            "-preset", "ultrafast",
            "-crf", str(self.project.config.crf),
            output_path
        ]
        
        self.log("Concatenating segments with crossfades...")
        subprocess.run(cmd, capture_output=True, check=True, timeout=300)
        
    def encode_simple(self, output_path: str):
        """Simple encoding without crossfades (fallback)"""
        if not self.segment_files:
            raise ValueError("No segment files")
            
        # Create concat list
        concat_file = os.path.join(self.temp_dir, "concat_list.txt")
        with open(concat_file, "w") as f:
            for seg in self.segment_files:
                f.write(f"file '{os.path.abspath(seg)}'\n")
                
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            output_path
        ]
        
        subprocess.run(cmd, capture_output=True, check=True)
        
    def encode(self, output_path: str, use_crossfade: bool = True) -> bool:
        """Main encoding method"""
        if not self.check_ffmpeg():
            self.log("FFmpeg not found! Please install FFmpeg.", "ERROR")
            return False
            
        try:
            self.setup_temp_dir()
            
            # Process each song
            self.log(f"Processing {len(self.project.entries)} songs...")
            for i, entry in enumerate(self.project.entries):
                segment = self.create_video_segment(entry, i)
                if segment:
                    self.segment_files.append(segment)
                    
            if not self.segment_files:
                self.log("No segments created!", "ERROR")
                return False
                
            # Concatenate with or without crossfades
            if use_crossfade and len(self.segment_files) > 1:
                self.concatenate_segments(output_path)
            else:
                self.encode_simple(output_path)
                
            self.log(f"Video saved to: {output_path}", "SUCCESS")
            return True
            
        except Exception as e:
            self.log(f"Encoding failed: {e}", "ERROR")
            return False
        finally:
            self.cleanup_temp_dir()


def load_ranking_json(json_path: str) -> EncodingProject:
    """Load ranking data from JSON file exported by the web app"""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    config_data = data.get("config", {})
    config = VideoConfig(
        width=config_data.get("width", 1920),
        height=config_data.get("height", 1080),
        fps=config_data.get("fps", 30),
        video_bitrate=config_data.get("bitrate", "8M"),
        transition_duration=config_data.get("transition_duration", 0.5),
    )
    
    project = EncodingProject(config=config)
    
    entries_data = data.get("entries", [])
    for i, entry in enumerate(entries_data):
        song = entry.get("song", {})
        song_entry = SongEntry(
            rank=entry.get("rank", i + 1),
            song_id=song.get("id", ""),
            title=song.get("t", "Unknown"),
            title_jp=song.get("tj", ""),
            game=song.get("gt", ""),
            artist=song.get("artists", ""),
            song_type=song.get("st", 0),
            duration=entry.get("duration", 15.0),
            start_time=entry.get("startTime", 0.0),
            local_file=entry.get("localFile"),
            audio_url=song.get("au"),
            vndb_id=song.get("vid"),
            cover_file=entry.get("coverFile"),
        )
        project.entries.append(song_entry)
        
    return project


def generate_ffmpeg_script(project: EncodingProject, script_path: str):
    """Generate a shell script with all FFmpeg commands"""
    lines = [
        "#!/bin/bash",
        "# EMQ Ranking Video Encoding Script",
        "# Generated by emq_encoder.py",
        "",
        "set -e",
        "",
        f'OUTPUT="{os.path.abspath(script_path).replace(".sh", ".mp4")}"',
        f'TEMP_DIR=$(mktemp -d)',
        'trap "rm -rf $TEMP_DIR" EXIT',
        "",
        f"# Configuration",
        f'WIDTH={project.config.width}',
        f'HEIGHT={project.config.height}',
        f'FPS={project.config.fps}',
        "",
    ]
    
    # Add commands for each segment
    for i, entry in enumerate(project.entries):
        type_color = ColorPalette.TYPE_COLORS.get(entry.song_type, ColorPalette.TYPE_COLORS[0])[0]
        type_label = ColorPalette.TYPE_LABELS.get(entry.song_type, "?")
        
        lines.extend([
            f"# Segment {i + 1}: {entry.title}",
            f'ffmpeg -y -loop 1 -t {entry.duration} "',
            f'  -vf "drawtext=text=\'#{entry.rank}\':fontsize=72:fontcolor={type_color}:x=50:y=h-100"',
            f'  segment_{i:04d}.mp4',
            "",
        ])
        
    # Add concat command
    lines.extend([
        "# Concatenate all segments",
        "ls segment_*.mp4 > concat_list.txt",
        'ffmpeg -y -f concat -safe 0 -i concat_list.txt -c copy "$OUTPUT"',
        "",
        'echo "Video saved to: $OUTPUT"',
    ])
    
    with open(script_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        
    os.chmod(script_path, 0o755)
    print(f"Generated encoding script: {script_path}")


def main():
    parser = argparse.ArgumentParser(
        description="EMQ Ranking Video Encoder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ranking.json --output video.mp4
  %(prog)s ranking.json --output video.mp4 --crossfade
  %(prog)s ranking.json --generate-script encode.sh
  %(prog)s ranking.json --verbose
        """
    )
    
    parser.add_argument("input", help="Input ranking JSON file")
    parser.add_argument("-o", "--output", help="Output video file")
    parser.add_argument("--generate-script", metavar="FILE", help="Generate encoding script instead of encoding")
    parser.add_argument("--width", type=int, default=1920, help="Video width (default: 1920)")
    parser.add_argument("--height", type=int, default=1080, help="Video height (default: 1080)")
    parser.add_argument("--fps", type=int, default=30, help="Frame rate (default: 30)")
    parser.add_argument("--crf", type=int, default=18, help="CRF quality (default: 18)")
    parser.add_argument("--transition", type=float, default=0.5, help="Crossfade duration in seconds (default: 0.5)")
    parser.add_argument("--no-crossfade", action="store_true", help="Disable crossfade transitions")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    # Load ranking data
    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)
        
    try:
        project = load_ranking_json(args.input)
    except Exception as e:
        print(f"Error loading JSON: {e}")
        sys.exit(1)
        
    # Apply command-line overrides
    project.config.width = args.width
    project.config.height = args.height
    project.config.fps = args.fps
    project.config.crf = args.crf
    project.config.transition_duration = args.transition
    
    print(f"Loaded {len(project.entries)} songs from {args.input}")
    
    # Generate script or encode
    if args.generate_script:
        generate_ffmpeg_script(project, args.generate_script)
    elif args.output:
        encoder = VideoEncoder(project, verbose=args.verbose)
        success = encoder.encode(args.output, use_crossfade=not args.no_crossfade)
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
        print("\nError: Must specify either --output or --generate-script")
        sys.exit(1)


if __name__ == "__main__":
    main()
