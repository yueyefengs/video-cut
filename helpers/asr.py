"""Transcribe a WAV/audio file with Alibaba Cloud Paraformer v2 via DashScope.

Used to get word-level timestamps from TTS audio for subtitle generation.

Flow:
  1. Upload WAV to Qiniu → get public URL
  2. Submit async task to DashScope Paraformer v2 API
  3. Poll until done, fetch result JSON
  4. Delete Qiniu file
  5. Convert response → {"words": [...]} with start/end timestamps

Usage:
    python helpers/asr.py edit/segments/seg_01.wav
    python helpers/asr.py edit/segments/seg_01.wav --out edit/transcripts/seg_01.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests

try:
    from qiniu import Auth as QiniuAuth, BucketManager, put_file_v2
except ImportError:
    sys.exit("qiniu SDK not installed — run: pip install qiniu")


DASHSCOPE_SUBMIT = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
DASHSCOPE_QUERY  = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"


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
    for key in ["DASHSCOPE_API_KEY", "QINIU_ACCESS_KEY", "QINIU_SECRET_KEY", "QINIU_BUCKET", "QINIU_DOMAIN"]:
        if key not in cfg and key in os.environ:
            cfg[key] = os.environ[key]
    missing = [k for k in ["DASHSCOPE_API_KEY", "QINIU_ACCESS_KEY", "QINIU_SECRET_KEY", "QINIU_BUCKET", "QINIU_DOMAIN"] if not cfg.get(k)]
    if missing:
        sys.exit(f"Missing in .env or environment: {', '.join(missing)}")
    return cfg


def _qiniu_domain(cfg: dict) -> str:
    d = cfg["QINIU_DOMAIN"].strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    return d


def upload_to_qiniu(audio_path: Path, cfg: dict) -> tuple[str, str]:
    auth = QiniuAuth(cfg["QINIU_ACCESS_KEY"], cfg["QINIU_SECRET_KEY"])
    key = f"asr/{audio_path.stem}_{uuid.uuid4().hex[:8]}.wav"
    token = auth.upload_token(cfg["QINIU_BUCKET"], key, 7200)
    ret, info = put_file_v2(token, key, str(audio_path))
    if info.status_code != 200:
        raise RuntimeError(f"Qiniu upload failed ({info.status_code}): {info.text_body}")
    url = f"https://{_qiniu_domain(cfg)}/{key}"
    return url, key


def delete_from_qiniu(key: str, cfg: dict) -> None:
    auth = QiniuAuth(cfg["QINIU_ACCESS_KEY"], cfg["QINIU_SECRET_KEY"])
    bm = BucketManager(auth)
    bm.delete(cfg["QINIU_BUCKET"], key)


def submit_task(audio_url: str, cfg: dict) -> str:
    headers = {
        "Authorization": f"Bearer {cfg['DASHSCOPE_API_KEY']}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    payload = {
        "model": "paraformer-v2",
        "input": {"file_urls": [audio_url]},
        "parameters": {
            "channel_id": [0],
            "timestamp_alignment_enabled": True,
            "disfluency_removal_enabled": False,
            "language_hints": ["zh"],
        },
    }
    resp = requests.post(DASHSCOPE_SUBMIT, json=payload, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Paraformer submit failed ({resp.status_code}): {resp.text[:400]}")
    return resp.json()["output"]["task_id"]


def poll_task(task_id: str, cfg: dict, timeout: int = 600) -> dict:
    headers = {"Authorization": f"Bearer {cfg['DASHSCOPE_API_KEY']}"}
    url = DASHSCOPE_QUERY.format(task_id=task_id)
    deadline = time.time() + timeout
    interval = 3.0

    while time.time() < deadline:
        time.sleep(interval)
        interval = min(interval * 1.5, 10.0)
        resp = requests.get(url, headers=headers, timeout=30)
        data = resp.json()
        status = data.get("output", {}).get("task_status", "")
        if status == "SUCCEEDED":
            results = data["output"].get("results", [])
            if not results or results[0].get("subtask_status") != "SUCCEEDED":
                raise RuntimeError("Paraformer subtask failed")
            tr = requests.get(results[0]["transcription_url"], timeout=60)
            tr.raise_for_status()
            return tr.json()
        elif status in ("PENDING", "RUNNING"):
            continue
        else:
            raise RuntimeError(f"Paraformer task failed — status={status}")
    raise TimeoutError(f"ASR task timed out after {timeout}s")


def paraformer_to_words(data: dict) -> list[dict]:
    """Extract word-level entries with start/end in seconds."""
    words = []
    for transcript in data.get("transcripts", []):
        for sentence in transcript.get("sentences", []):
            for w in sentence.get("words", []):
                text = (w.get("text") or "").strip()
                if not text:
                    continue
                words.append({
                    "type": "word",
                    "start": w["begin_time"] / 1000.0,
                    "end": w["end_time"] / 1000.0,
                    "text": text,
                })
    return words


def transcribe(audio_path: Path, out_path: Path, verbose: bool = True) -> list[dict]:
    """Transcribe audio → word list. Writes JSON to out_path. Returns words."""
    if out_path.exists():
        if verbose:
            print(f"  cached: {out_path.name}")
        return json.loads(out_path.read_text())["words"]

    cfg = load_config()
    if verbose:
        print(f"  uploading {audio_path.name} to Qiniu...", flush=True)
    audio_url, qiniu_key = upload_to_qiniu(audio_path, cfg)

    try:
        if verbose:
            print("  submitting to Paraformer v2...", flush=True)
        task_id = submit_task(audio_url, cfg)
        if verbose:
            print(f"  polling task {task_id}...", flush=True)
        result = poll_task(task_id, cfg)
    finally:
        try:
            delete_from_qiniu(qiniu_key, cfg)
        except Exception:
            pass

    words = paraformer_to_words(result)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"words": words}, indent=2, ensure_ascii=False))
    if verbose:
        print(f"  saved: {out_path.name} ({len(words)} words)")
    return words


def main() -> None:
    ap = argparse.ArgumentParser(description="Transcribe audio with Paraformer v2")
    ap.add_argument("audio", type=Path)
    ap.add_argument("--out", "-o", type=Path, default=None)
    args = ap.parse_args()

    audio = args.audio.resolve()
    if not audio.exists():
        sys.exit(f"audio not found: {audio}")

    out = args.out or (audio.parent / f"{audio.stem}.json")
    transcribe(audio, out.resolve())


if __name__ == "__main__":
    main()
