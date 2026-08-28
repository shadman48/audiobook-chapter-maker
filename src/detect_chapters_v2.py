#!/usr/bin/env python3
"""Fast chapter detection: find pauses, then transcribe only short windows around them."""
from __future__ import annotations

import argparse
import json
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


def choose_device(requested: str) -> tuple[str, str, str]:
    if requested == "cpu":
        return "cpu", "int8", "CPU selected by user."
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16", "NVIDIA CUDA device detected."
    except Exception as exc:
        if requested == "cuda":
            raise RuntimeError(f"NVIDIA GPU was required, but CUDA detection failed: {exc}") from exc
    if requested == "cuda":
        raise RuntimeError("NVIDIA GPU was required, but no CUDA-capable device was detected.")
    return "cpu", "int8", "No usable NVIDIA CUDA device was detected."


def chapter_count(found: list[tuple[float, str]]) -> int:
    return len({title.lower() for _, title in found if title.lower().startswith("chapter ")})


def add_heading(found: list[tuple[float, str]], stamp: float, title: str) -> bool:
    for old_stamp, old_title in found:
        if abs(stamp - old_stamp) < 20 or old_title.lower() == title.lower():
            return False
    found.append((max(0.0, stamp), title)); found.sort(key=lambda row: row[0])
    print(f"  Found {title:<24} at {clock(stamp)}", flush=True)
    return True


def inspect_candidates(model, source: Path, duration: float, candidates: list[float], found: list[tuple[float, str]], scanned: list[float]) -> None:
    with tempfile.TemporaryDirectory(prefix="audiobook-scan-") as temp:
        clip = Path(temp) / "candidate.wav"
        todo = [p for p in candidates if not any(abs(p-old) < 7 for old in scanned)]
        total = len(todo)
        for index, point in enumerate(todo, 1):
            scanned.append(point); start = max(0.0, point - 2.5); length = min(18.0, duration - start)
            if length <= 0: continue
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", str(source), "-t", str(length), "-ac", "1", "-ar", "16000", str(clip)], check=True, creationflags=NO_WINDOW)
            segments, _ = model.transcribe(str(clip), language="en", beam_size=3, vad_filter=True, condition_on_previous_text=False)
            for seg in segments:
                match = HEADING.search(seg.text)
                if match: add_heading(found, start + seg.start - 0.5, match.group("title").title())
            if index == 1 or index % 25 == 0 or index == total:
                print(f"  Progress: {index}/{max(1,total)} locations checked", flush=True)


def full_scan(model, source: Path, found: list[tuple[float, str]]) -> None:
    print("Thorough fallback: scanning the complete audiobook because validation did not pass.", flush=True)
    segments, _ = model.transcribe(str(source), language="en", beam_size=5, vad_filter=True, condition_on_previous_text=False)
    for index, seg in enumerate(segments, 1):
        match = HEADING.search(seg.text)
        if match: add_heading(found, seg.start - 0.75, match.group("title").title())
        if index % 250 == 0: print(f"  Full scan progress: {clock(seg.end)} of audiobook checked", flush=True)


def amd_full_scan(cli: Path, model: Path, source: Path, found: list[tuple[float, str]]) -> None:
    print("ACTIVE PROCESSOR: AMD GPU (Vulkan)", flush=True)
    print("Thorough scan: processing the complete audiobook with AMD Vulkan...", flush=True)
    with tempfile.TemporaryDirectory(prefix="audiobook-amd-") as temp:
        output_base = Path(temp) / "transcription"
        command = [str(cli), "-m", str(model), "-f", str(source), "-l", "en", "-ojf", "-of", str(output_base), "-pp"]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", creationflags=NO_WINDOW)
        backend_seen = False
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line.rstrip(), flush=True)
            if re.search(r"vulkan|ggml_vulkan", line, re.I): backend_seen = True
        if proc.wait(): raise RuntimeError("AMD whisper.cpp transcription failed.")
        if not backend_seen: raise RuntimeError("The selected whisper.cpp executable did not report an active Vulkan backend.")
        json_path = output_base.with_suffix(".json")
        data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
        for item in data.get("transcription", []):
            match = HEADING.search(item.get("text", ""))
            if match:
                offset = item.get("offsets", {}).get("from", 0) / 1000
                add_heading(found, offset - 0.75, match.group("title").title())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--model", default="base.en")
    ap.add_argument("--silence-db", type=int, default=-38)
    ap.add_argument("--silence-seconds", type=float, default=1.5)
    ap.add_argument("--expected", type=int, default=0)
    ap.add_argument("--device", choices=("auto", "cuda", "amd", "cpu"), default="auto")
    ap.add_argument("--amd-cli", type=Path)
    ap.add_argument("--amd-model", type=Path)
    args = ap.parse_args()
    source = args.input.resolve()
    if not source.is_file() or source.suffix.lower() != ".mp3": raise SystemExit("Input must be an existing MP3.")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"): raise SystemExit("FFmpeg and ffprobe are required.")

    duration = probe_duration(source)
    if args.device == "amd":
        if not args.amd_cli or not args.amd_cli.is_file() or not args.amd_model or not args.amd_model.is_file():
            raise RuntimeError("AMD Vulkan mode requires a Vulkan whisper-cli executable and GGML model.")
        found: list[tuple[float, str]] = []
        amd_full_scan(args.amd_cli, args.amd_model, source, found)
        if args.expected and chapter_count(found) < args.expected:
            print(f"Final validation: {chapter_count(found)} of {args.expected} numbered chapters detected.", flush=True)
            print("Validation failed. No .m4b file was created.", flush=True)
            return 4
    else:
        found = []
        device, compute, device_note = choose_device(args.device)
        print(f"Hardware check: {device_note}", flush=True)
        print(f"Step 2/3: loading Whisper {args.model} on {device.upper()}...", flush=True)
        try:
            model = WhisperModel(args.model, device=device, compute_type=compute)
            if device == "cuda":
                import numpy as np
                test_segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language="en")
                list(test_segments)  # Force execution; transcription is lazy.
        except Exception as exc:
            if device != "cuda" or args.device == "cuda":
                raise
            print(f"GPU test failed: {exc}", flush=True)
            print("Falling back to CPU. Select 'Require NVIDIA GPU' in the app to prevent fallback.", flush=True)
            device, compute = "cpu", "int8"
            model = WhisperModel(args.model, device=device, compute_type=compute)
        print(f"ACTIVE PROCESSOR: {'NVIDIA GPU (CUDA)' if device == 'cuda' else 'CPU'}", flush=True)
        scanned: list[float] = []
        thresholds = [args.silence_seconds, 1.0, 0.7, 0.4]
        for pass_number, threshold in enumerate(dict.fromkeys(thresholds), 1):
            candidates = find_candidates(source, args.silence_db, threshold)
            print(f"Pause scan pass {pass_number}: inspecting new locations with Whisper...", flush=True)
            inspect_candidates(model, source, duration, candidates, found, scanned)
            count = chapter_count(found)
            if args.expected:
                print(f"Validation after pass {pass_number}: {count} of {args.expected} numbered chapters detected.", flush=True)
                if count >= args.expected: break
                print("Validation did not pass; retrying with a more sensitive pause setting.", flush=True)
            elif count >= 3:
                break

        if args.expected and chapter_count(found) < args.expected:
            full_scan(model, source, found)
            count = chapter_count(found)
            print(f"Final validation: {count} of {args.expected} numbered chapters detected.", flush=True)
            if count < args.expected:
                print("Validation failed even after the thorough scan. No .m4b file was created.", flush=True)
                return 4

    if not found:
        print("No headings were found. No .m4b file was created.")
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
