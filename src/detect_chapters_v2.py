#!/usr/bin/env python3
"""Fast chapter detection: find pauses, then transcribe only short windows around them."""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from faster_whisper import WhisperModel

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

NUMBER = (r"(?:\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
          r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
          r"forty|fifty|sixty|seventy|eighty|ninety|hundred|first|second|third|fourth|"
          r"fifth|sixth|seventh|eighth|ninth|tenth)(?:[ -](?:one|two|three|four|five|six|"
          r"seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
          r"seventeen|eighteen|nineteen))?")
HEADING = re.compile(rf"\b(?P<title>(?:chapter|book|part)\s+(?:the\s+)?{NUMBER}|prologue|epilogue|introduction|afterword)\b", re.I)
SILENCE_END = re.compile(r"silence_end:\s*([0-9.]+)")


def clock(seconds: float) -> str:
    n = max(0, int(round(seconds)))
    return f"{n // 3600:02d}:{n % 3600 // 60:02d}:{n % 60:02d}"


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)], check=True, capture_output=True, text=True, creationflags=NO_WINDOW)
    return float(out.stdout.strip())


def escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#").replace("\n", " ")


def find_candidates(source: Path, silence_db: int, silence_seconds: float) -> list[float]:
    print(f"Step 1/3: finding pauses of at least {silence_seconds:g} seconds...")
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(source), "-af", f"silencedetect=noise={silence_db}dB:d={silence_seconds}", "-f", "null", "-"], capture_output=True, text=True, creationflags=NO_WINDOW)
    combined = proc.stdout + "\n" + proc.stderr
    candidates = [0.0] + [float(x) for x in SILENCE_END.findall(combined)]
    # Avoid overlapping 18-second recognition windows.
    kept: list[float] = []
    for point in sorted(candidates):
        if not kept or point - kept[-1] >= 14:
            kept.append(point)
    print(f"  Found {len(kept)} likely locations to inspect.")
    return kept


def choose_device() -> tuple[str, str]:
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--model", default="base.en")
    ap.add_argument("--silence-db", type=int, default=-38)
    ap.add_argument("--silence-seconds", type=float, default=1.5)
    args = ap.parse_args()
    source = args.input.resolve()
    if not source.is_file() or source.suffix.lower() != ".mp3": raise SystemExit("Input must be an existing MP3.")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"): raise SystemExit("FFmpeg and ffprobe are required.")

    duration = probe_duration(source)
    candidates = find_candidates(source, args.silence_db, args.silence_seconds)
    device, compute = choose_device()
    print(f"Step 2/3: checking likely locations with Whisper {args.model} on {device.upper()}...")
    try:
        model = WhisperModel(args.model, device=device, compute_type=compute)
    except Exception as exc:
        if device != "cuda":
            raise
        print(f"  NVIDIA acceleration is unavailable ({exc}). Falling back to CPU.")
        device, compute = "cpu", "int8"
        model = WhisperModel(args.model, device=device, compute_type=compute)
    found: list[tuple[float, str]] = []
    with tempfile.TemporaryDirectory(prefix="audiobook-v2-") as temp:
        clip = Path(temp) / "candidate.wav"
        total = len(candidates)
        for index, point in enumerate(candidates, 1):
            start = max(0.0, point - 2.5)
            length = min(18.0, duration - start)
            if length <= 0: continue
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", str(source), "-t", str(length), "-ac", "1", "-ar", "16000", str(clip)], check=True, creationflags=NO_WINDOW)
            segments, _ = model.transcribe(str(clip), language="en", beam_size=3, vad_filter=True, condition_on_previous_text=False)
            text = " ".join(seg.text.strip() for seg in segments)
            match = HEADING.search(text)
            if match:
                title = match.group("title").title()
                stamp = max(0.0, point - 0.75)
                if not found or stamp - found[-1][0] >= 20:
                    found.append((stamp, title)); print(f"  Found {title:<24} at {clock(stamp)}")
            if index == 1 or index % 25 == 0 or index == total:
                print(f"  Progress: {index}/{total} locations checked", flush=True)

    if not found:
        print("No headings were found. Try V1 for a slower full-book scan.")
        return 3
    if found[0][0] > 15: found.insert(0, (0.0, "Opening"))
    else: found[0] = (0.0, found[0][1])

    chapter_file = source.with_name(source.stem + " - chapters.txt")
    meta_file = source.with_name(source.stem + " - chapters.ffmetadata")
    output = source.with_suffix(".m4b")
    if output.exists():
        number = 1
        output = source.with_name(source.stem + " - chaptered.m4b")
        while output.exists():
            number += 1
            output = source.with_name(source.stem + f" - chaptered {number}.m4b")
    chapter_file.write_text("\n".join(f"{i:02d}  {clock(t)}  {name}" for i, (t, name) in enumerate(found, 1)) + "\n", encoding="utf-8")
    lines = [";FFMETADATA1", f"title={escape(source.stem)}"]
    for i, (start, title) in enumerate(found):
        end = found[i + 1][0] if i + 1 < len(found) else duration
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(start*1000)}", f"END={int(end*1000)}", f"title={escape(title)}"]
    meta_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Step 3/3: creating your .m4b file...")
    working = output.with_suffix(".working.m4b")
    subprocess.run(["ffmpeg", "-hide_banner", "-y", "-i", str(source), "-i", str(meta_file), "-map", "0:a:0", "-map_metadata", "1", "-map_chapters", "1", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(working)], check=True, creationflags=NO_WINDOW)
    working.replace(output)
    print(f"Your .m4b file: {output}\nChapters: {chapter_file}\nOriginal: unchanged")
    return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"External program failed with exit code {exc.returncode}.", file=sys.stderr); raise SystemExit(exc.returncode)
