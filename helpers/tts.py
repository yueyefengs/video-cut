"""Generate TTS audio using Alibaba Cloud qwen3-tts-flash via DashScope.

Saves synthesized audio as WAV to the specified output path.

Usage:
    python helpers/tts.py "你好世界" --voice Cherry --output edit/tts.wav
    python helpers/tts.py "文案内容" --voice Cherry --instructions "语速较快，语调上扬" --output edit/tts.wav
    python helpers/tts.py --list-voices
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

try:
    import dashscope
except ImportError:
    sys.exit("dashscope not installed — run: pip install 'dashscope>=1.24.6'")


DASHSCOPE_API_URL = "https://dashscope.aliyuncs.com/api/v1"

BUILTIN_VOICES = [
    "Cherry",    # 女声，温柔自然
    "Ethan",     # 男声，沉稳
    "Serena",    # 女声，清晰
    "Dylan",     # 男声，活力
    "Aria",      # 女声，优雅
    "Aiden",
    "Luna",
    "Noah",
]


def load_config() -> dict:
    cfg: dict[str, str] = {}
    for candidate in [Path(__file__).resolve().parent.parent / ".env", Path(".env")]:
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
            break
    if "DASHSCOPE_API_KEY" not in cfg:
        cfg["DASHSCOPE_API_KEY"] = os.environ.get("DASHSCOPE_API_KEY", "")
    if not cfg.get("DASHSCOPE_API_KEY"):
        sys.exit("DASHSCOPE_API_KEY not found in .env or environment")
    return cfg


def synthesize(
    text: str,
    voice: str,
    cfg: dict,
    output_path: Path,
    instructions: str | None = None,
    language_type: str = "Chinese",
    verbose: bool = True,
) -> Path:
    """Generate TTS audio. Returns path to saved WAV file."""
    dashscope.base_http_api_url = DASHSCOPE_API_URL

    model = "qwen3-tts-instruct-flash" if instructions else "qwen3-tts-flash"

    call_kwargs: dict = {
        "model": model,
        "api_key": cfg["DASHSCOPE_API_KEY"],
        "text": text,
        "voice": voice,
        "language_type": language_type,
        "stream": False,
    }
    if instructions:
        call_kwargs["instructions"] = instructions
        call_kwargs["optimize_instructions"] = True

    if verbose:
        instr_note = f" [{instructions}]" if instructions else ""
        print(f"  TTS: model={model}, voice={voice}{instr_note}", flush=True)
        print(f"  text ({len(text)} chars): {text[:60]}{'...' if len(text) > 60 else ''}", flush=True)

    response = dashscope.MultiModalConversation.call(**call_kwargs)

    if response.status_code != 200:
        raise RuntimeError(
            f"TTS failed ({response.status_code}): {getattr(response, 'code', '')} — "
            f"{getattr(response, 'message', response)}"
        )

    audio_url = response.output.audio.url
    if verbose:
        print(f"  downloading audio from {audio_url[:60]}...", flush=True)

    r = requests.get(audio_url, timeout=120)
    r.raise_for_status()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(r.content)

    size_kb = output_path.stat().st_size / 1024
    if verbose:
        print(f"  saved: {output_path.name} ({size_kb:.0f} KB)")

    return output_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate TTS audio with qwen3-tts-flash")
    ap.add_argument("text", nargs="?", type=str, help="Text to synthesize")
    ap.add_argument("--voice", type=str, default="Cherry", help="Voice name (default: Cherry)")
    ap.add_argument("--output", "-o", type=Path, default=Path("tts.wav"))
    ap.add_argument("--instructions", type=str, default=None,
                    help="Style instructions (enables qwen3-tts-instruct-flash)")
    ap.add_argument("--language", type=str, default="Chinese")
    ap.add_argument("--list-voices", action="store_true", help="Print known voice names and exit")
    args = ap.parse_args()

    if args.list_voices:
        print("Known built-in voices for qwen3-tts-flash:")
        for v in BUILTIN_VOICES:
            print(f"  {v}")
        return

    if not args.text:
        ap.error("text argument is required")

    cfg = load_config()
    synthesize(
        text=args.text,
        voice=args.voice,
        cfg=cfg,
        output_path=args.output.resolve(),
        instructions=args.instructions,
        language_type=args.language,
    )


if __name__ == "__main__":
    main()
