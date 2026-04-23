"""Compose one segment: B-roll clip(s) + TTS audio → MP4.

The output has no subtitles — subtitles are applied by concat_final.py after all
segments are concatenated (Hard Rule: subtitles LAST).

Flow:
  1. Get TTS audio duration
  2. Loop/trim B-roll to fill that duration (+ 0.5s tail)
  3. Mix TTS audio onto B-roll video
  4. Apply 30ms audio fades at both edges

Usage:
    python helpers/compose_segment.py \\
        --tts edit/segments/seg_01.wav \\
        --broll input/broll/product_demo.mp4 \\
        --output edit/clips/seg_01.mp4
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def probe_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(path),
    ])
    return float(json.loads(out)["format"]["duration"])


def _run(cmd: list[str], label: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed (exit {result.returncode}):\n{result.stderr[-1500:]}")


def compose_segment(
    tts_path: Path,
    broll_path: Path,
    output_path: Path,
    preview: bool = False,
    verbose: bool = True,
) -> Path:
    tts_duration = probe_duration(tts_path)
    broll_duration = probe_duration(broll_path)

    if verbose:
        print(f"  [{output_path.stem}] TTS={tts_duration:.2f}s  broll={broll_duration:.2f}s", flush=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    crf = "28" if preview else "20"
    scale = (
        "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:-1:-1"
        if preview else
        "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:-1:-1"
    )
    # 30ms audio fades (Hard Rule 3 from video-use)
    fade_out_start = max(0.0, tts_duration - 0.03)
    af = f"afade=t=in:st=0:d=0.03,afade=t=out:st={fade_out_start:.3f}:d=0.03"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        fill_duration = tts_duration + 0.5

        if broll_duration >= fill_duration:
            # Trim B-roll to needed duration — no loop needed
            broll_scaled = tmp_dir / "broll_scaled.mp4"
            _run([
                "ffmpeg", "-y",
                "-ss", "0", "-i", str(broll_path),
                "-t", f"{fill_duration:.3f}",
                "-vf", scale,
                "-c:v", "libx264", "-preset", "fast", "-crf", crf, "-an",
                str(broll_scaled),
            ], "broll scale")
        else:
            # Build concat list looping the clip until we have enough
            concat_list = tmp_dir / "loop.txt"
            lines = []
            accumulated = 0.0
            while accumulated < fill_duration:
                remaining = fill_duration - accumulated
                lines.append(f"file '{broll_path.resolve()}'")
                if remaining < broll_duration:
                    lines.append(f"duration {remaining:.6f}")
                    accumulated = fill_duration
                else:
                    lines.append(f"duration {broll_duration:.6f}")
                    accumulated += broll_duration
            concat_list.write_text("\n".join(lines))

            broll_concat = tmp_dir / "broll_loop.mp4"
            _run([
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-vf", scale,
                "-c:v", "libx264", "-preset", "fast", "-crf", crf, "-an",
                str(broll_concat),
            ], "broll loop+scale")
            broll_scaled = broll_concat

        # Mix TTS audio
        _run([
            "ffmpeg", "-y",
            "-i", str(broll_scaled), "-i", str(tts_path),
            "-map", "0:v:0", "-map", "1:a:0",
            "-t", f"{tts_duration:.3f}",
            "-c:v", "copy",
            "-af", af,
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-pix_fmt", "yuv420p", "-r", "24",
            "-movflags", "+faststart",
            str(output_path),
        ], "mix audio")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    if verbose:
        print(f"  → {output_path.name} ({size_mb:.1f} MB, {tts_duration:.1f}s)")

    return output_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Compose one segment: B-roll + TTS → MP4")
    ap.add_argument("--tts", type=Path, required=True)
    ap.add_argument("--broll", type=Path, required=True)
    ap.add_argument("--output", "-o", type=Path, required=True)
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()

    for p, name in [(args.tts, "--tts"), (args.broll, "--broll")]:
        if not p.resolve().exists():
            sys.exit(f"{name} not found: {p}")

    compose_segment(args.tts.resolve(), args.broll.resolve(), args.output.resolve(), args.preview)


if __name__ == "__main__":
    main()
