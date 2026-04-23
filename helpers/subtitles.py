"""Generate SRT subtitles from script text + TTS audio duration.

No ASR needed — the text is already known (it's what we fed to TTS).
Timestamps are estimated by distributing characters proportionally across
the audio duration.

Usage:
    python helpers/subtitles.py \
        --text "你好世界，今天介绍一款好用的产品" \
        --duration 5.2 \
        --output edit/transcripts/seg_01.srt

    # Or pass a text file
    python helpers/subtitles.py \
        --text-file edit/segments/seg_01.txt \
        --audio edit/segments/seg_01.wav \
        --output edit/transcripts/seg_01.srt
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


CHARS_PER_LINE = 8   # characters per subtitle line (tune for pacing)
MIN_LINE_DUR   = 0.4  # minimum seconds per line


def probe_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(path),
    ])
    return float(json.loads(out)["format"]["duration"])


def _srt_ts(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def chunk_text(text: str, chars_per_line: int) -> list[str]:
    """Split text into subtitle-sized chunks, respecting punctuation boundaries."""
    # Strip whitespace
    text = re.sub(r"\s+", "", text)
    if not text:
        return []

    # Try to break on natural punctuation first
    # Chinese punctuation: ，。！？；：
    punct = set("，。！？；：,!?;:")
    chunks: list[str] = []
    current = ""

    for ch in text:
        current += ch
        if len(current) >= chars_per_line or ch in punct:
            if current.strip():
                chunks.append(current.strip())
            current = ""

    if current.strip():
        chunks.append(current.strip())

    return chunks


def text_to_srt(text: str, total_duration: float, chars_per_line: int = CHARS_PER_LINE) -> str:
    """Convert text + total duration to SRT content using proportional timestamps."""
    chunks = chunk_text(text, chars_per_line)
    if not chunks:
        return ""

    total_chars = sum(len(c) for c in chunks)
    if total_chars == 0:
        return ""

    lines: list[str] = []
    offset = 0.0

    for idx, chunk in enumerate(chunks, 1):
        proportion = len(chunk) / total_chars
        dur = max(MIN_LINE_DUR, proportion * total_duration)

        # Last chunk snaps to end
        if idx == len(chunks):
            end = total_duration
        else:
            end = min(offset + dur, total_duration)

        lines += [
            str(idx),
            f"{_srt_ts(offset)} --> {_srt_ts(end)}",
            chunk,
            "",
        ]
        offset = end

    return "\n".join(lines)


def build_srt_for_segment(
    text: str,
    audio_path: Path,
    out_path: Path,
    chars_per_line: int = CHARS_PER_LINE,
    verbose: bool = True,
) -> Path:
    duration = probe_duration(audio_path)
    srt = text_to_srt(text, duration, chars_per_line)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(srt, encoding="utf-8")
    if verbose:
        chunks = [l for l in srt.splitlines() if l and not l[0].isdigit() and "-->" not in l]
        print(f"  SRT: {out_path.name} ({len(chunks)} lines, {duration:.1f}s)")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate SRT from script text + audio duration")
    text_grp = ap.add_mutually_exclusive_group(required=True)
    text_grp.add_argument("--text", type=str, help="Script text")
    text_grp.add_argument("--text-file", type=Path, help="File containing script text")
    dur_grp = ap.add_mutually_exclusive_group(required=True)
    dur_grp.add_argument("--duration", type=float, help="Audio duration in seconds")
    dur_grp.add_argument("--audio", type=Path, help="Audio file (duration probed via ffprobe)")
    ap.add_argument("--output", "-o", type=Path, required=True)
    ap.add_argument("--chars-per-line", type=int, default=CHARS_PER_LINE)
    args = ap.parse_args()

    text = args.text or args.text_file.read_text(encoding="utf-8").strip()
    duration = args.duration if args.duration else probe_duration(args.audio.resolve())

    srt = text_to_srt(text, duration, args.chars_per_line)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(srt, encoding="utf-8")
    print(f"saved: {args.output}")


if __name__ == "__main__":
    main()
