"""Concat all segment MP4s and burn subtitles LAST.

Flow:
  1. Lossless -c copy concat all clips
  2. Optionally build master SRT from per-segment transcript JSONs + time offsets
  3. Burn subtitles LAST (Hard Rule: subtitles after all compositing)
  4. Loudness normalize to -14 LUFS

Usage:
    python helpers/concat_final.py \\
        --clips edit/clips/seg_01.mp4 edit/clips/seg_02.mp4 \\
        --output edit/final.mp4

    python helpers/concat_final.py \\
        --clips-dir edit/clips \\
        --transcripts-dir edit/transcripts \\
        --output edit/final.mp4
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# Subtitle style matching compose_narration in video-use
FORCE_STYLE = (
    "FontName=PingFang SC,FontSize=42,Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
    "BorderStyle=1,Outline=4,Shadow=0,"
    "Alignment=2,MarginV=80"
)


def _run(cmd: list[str], label: str = "") -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{label or cmd[0]} failed:\n{result.stderr[-1500:]}")


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


def build_srt(clips: list[Path], transcripts_dir: Path | None, out_path: Path) -> bool:
    """Build master SRT from per-segment transcript JSONs with output-timeline offsets.
    Returns True if SRT was created.
    """
    if not transcripts_dir or not transcripts_dir.is_dir():
        return False

    entries: list[tuple[float, float, str]] = []
    offset = 0.0
    chunk = 3  # words per subtitle line

    for clip in clips:
        tr_path = transcripts_dir / f"{clip.stem}.json"
        if not tr_path.exists():
            offset += probe_duration(clip)
            continue

        words = [w for w in json.loads(tr_path.read_text()).get("words", [])
                 if w.get("type") == "word"]

        i = 0
        while i < len(words):
            group = words[i:i + chunk]
            start = group[0]["start"] + offset
            end = group[-1]["end"] + offset
            text = "".join(w["text"] for w in group)
            entries.append((start, end, text))
            i += chunk

        offset += probe_duration(clip)

    if not entries:
        return False

    lines: list[str] = []
    for idx, (a, b, t) in enumerate(entries, 1):
        lines += [str(idx), f"{_srt_ts(a)} --> {_srt_ts(b)}", t, ""]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  SRT: {out_path.name} ({len(entries)} cues)")
    return True


def concat_clips(clips: list[Path], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for c in clips:
            f.write(f"file '{c.resolve()}'\n")
        concat_file = Path(f.name)

    _run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c", "copy", "-movflags", "+faststart",
        str(out_path),
    ], "concat")
    concat_file.unlink(missing_ok=True)
    print(f"  concat → {out_path.name}")


def burn_subtitles(base: Path, srt_path: Path, out_path: Path) -> None:
    srt_escaped = str(srt_path.resolve()).replace("\\", "/").replace(":", r"\:")
    _run([
        "ffmpeg", "-y", "-i", str(base),
        "-vf", f"subtitles=filename={srt_escaped}:force_style='{FORCE_STYLE}'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy", "-movflags", "+faststart",
        str(out_path),
    ], "subtitles")
    print(f"  subtitles burned → {out_path.name}")


def loudnorm(input_path: Path, output_path: Path, preview: bool = False) -> None:
    if preview:
        filter_str = "loudnorm=I=-14:TP=-1:LRA=11"
        _run([
            "ffmpeg", "-y", "-hide_banner", "-nostats",
            "-i", str(input_path),
            "-c:v", "copy", "-af", filter_str,
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            str(output_path),
        ], "loudnorm 1-pass")
        return

    # Two-pass
    measure_cmd = [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-i", str(input_path),
        "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
        "-vn", "-f", "null", "-",
    ]
    proc = subprocess.run(measure_cmd, capture_output=True, text=True)
    stderr = proc.stderr
    start, end = stderr.rfind("{"), stderr.rfind("}")
    if start == -1 or end <= start:
        shutil.copy(input_path, output_path)
        return
    try:
        m = json.loads(stderr[start:end + 1])
    except json.JSONDecodeError:
        shutil.copy(input_path, output_path)
        return

    filter_str = (
        f"loudnorm=I=-14:TP=-1:LRA=11"
        f":measured_I={m['input_i']}"
        f":measured_TP={m['input_tp']}"
        f":measured_LRA={m['input_lra']}"
        f":measured_thresh={m['input_thresh']}"
        f":offset={m['target_offset']}"
        f":linear=true"
    )
    _run([
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-i", str(input_path),
        "-c:v", "copy", "-af", filter_str,
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(output_path),
    ], "loudnorm 2-pass")
    print(f"  loudnorm -14 LUFS → {output_path.name}")


def build_final(
    clips: list[Path],
    output_path: Path,
    transcripts_dir: Path | None = None,
    preview: bool = False,
    no_subtitles: bool = False,
    no_loudnorm: bool = False,
) -> None:
    edit_dir = output_path.parent

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # 1. Lossless concat
        base = tmp_dir / "base.mp4"
        concat_clips(clips, base)

        # 2. Build SRT
        srt_path = edit_dir / "master.srt"
        has_srt = (not no_subtitles) and build_srt(clips, transcripts_dir, srt_path)

        # 3. Burn subtitles LAST
        if has_srt:
            subbed = tmp_dir / "subbed.mp4"
            burn_subtitles(base, srt_path, subbed)
            pre_norm = subbed
        else:
            pre_norm = base

        # 4. Loudnorm
        if no_loudnorm:
            shutil.copy(pre_norm, output_path)
        else:
            loudnorm(pre_norm, output_path, preview=preview)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"\ndone: {output_path} ({size_mb:.1f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Concat segments + subtitles → final")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--clips", nargs="+", type=Path, help="Ordered list of segment MP4s")
    group.add_argument("--clips-dir", type=Path, help="Directory of seg_*.mp4 (sorted by name)")
    ap.add_argument("--transcripts-dir", type=Path, default=None,
                    help="Directory with per-segment JSON transcripts (for subtitles)")
    ap.add_argument("--output", "-o", type=Path, required=True)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--no-subtitles", action="store_true")
    ap.add_argument("--no-loudnorm", action="store_true")
    args = ap.parse_args()

    if args.clips_dir:
        clips = sorted(args.clips_dir.glob("seg_*.mp4"))
        if not clips:
            sys.exit(f"No seg_*.mp4 found in {args.clips_dir}")
    else:
        clips = [p.resolve() for p in args.clips]

    build_final(
        clips=clips,
        output_path=args.output.resolve(),
        transcripts_dir=args.transcripts_dir.resolve() if args.transcripts_dir else None,
        preview=args.preview,
        no_subtitles=args.no_subtitles,
        no_loudnorm=args.no_loudnorm,
    )


if __name__ == "__main__":
    main()
