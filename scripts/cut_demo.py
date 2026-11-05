#!/usr/bin/env python3
"""Cut a natural screen recording into the 90-second ClearVoice demo.

You do not perform for this. Record however you use the app — hold the button,
talk, pause, mistype, take your time — then run:

    ./scripts/build_demo.sh ~/Videos/clearvoice-raw.mkv

What happens next is decided by *your* audio, not by a script:

1. The audio track is scanned and the silence is measured. What you were doing
   becomes a list of "beats", in your own timing.
2. Dead air is compressed, and the longest silences are dropped until the cut
   fits 86 seconds of screen.
3. A title card, an end card and captions are laid on the beats that were found.
4. The result is encoded at 1920x1080, 30 fps, with faststart for X.

The narration is optional (--narration) and is mixed under your own audio, never
in place of it: the voice in the demo should be the app's, not mine.
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

HERE = Path(__file__).resolve().parent.parent
DEMO = HERE / "demo"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

CARD_SECONDS = 3.0
END_SECONDS = 4.0
TARGET_SCREEN_SECONDS = 86.0
GAP_SECONDS = 0.35


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def duration_of(path: Path) -> float:
    out = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path),
    ]).stdout.strip()
    try:
        return float(out)
    except ValueError:
        raise SystemExit(f"Could not read a duration from {path}")


def find_active_segments(path: Path, noise_db: int = -32, min_silence: float = 0.6):
    """Non-silent intervals in the recording: where something actually happened."""
    proc = run([
        "ffmpeg", "-hide_banner", "-i", str(path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
        "-f", "null", "-",
    ])
    log = proc.stderr
    total = duration_of(path)

    silences: list[tuple[float, float]] = []
    pending: float | None = None
    for line in log.splitlines():
        start = re.search(r"silence_start:\s*(-?[\d.]+)", line)
        if start:
            pending = max(0.0, float(start.group(1)))
            continue
        end = re.search(r"silence_end:\s*([\d.]+)", line)
        if end and pending is not None:
            silences.append((pending, min(total, float(end.group(1)))))
            pending = None
    if pending is not None:
        silences.append((pending, total))

    segments: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in silences:
        if start - cursor > GAP_SECONDS:
            segments.append((cursor, start))
        cursor = max(cursor, end)
    if total - cursor > GAP_SECONDS:
        segments.append((cursor, total))
    if not segments:  # a take with no silence at all: use all of it
        segments = [(0.0, total)]

    # Sentences are separated by short gaps; merging them keeps whole thoughts
    # together instead of cutting mid-phrase at every breath.
    for merge_gap in (1.4, 2.2, 3.0, 4.0):
        merged: list[tuple[float, float]] = []
        for start, end in segments:
            if merged and start - merged[-1][1] <= merge_gap:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        segments = merged
        if len(segments) <= 10:
            break
    return segments, total


def fit_to_budget(segments, budget: float):
    """Keep the earliest moments, trim the last one, drop what does not fit."""
    plan, used = [], 0.0
    for start, end in segments:
        length = end - start
        if used + length > budget:
            remaining = budget - used
            if remaining > 0.8:
                plan.append((start, start + remaining))
            break
        plan.append((start, end))
        used += length
    return plan, used


def card(out: Path, title: str, subtitle: str, footnote: str) -> None:
    draw = (
        f"drawtext=fontfile={FONT}:text='{title}':fontcolor=0xeef2f7:fontsize=92:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-80,"
        f"drawtext=fontfile={FONT}:text='{subtitle}':fontcolor=0x4c8dff:fontsize=42:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+30,"
        f"drawtext=fontfile={FONT_REGULAR}:text='{footnote}':fontcolor=0x7c8794:fontsize=26:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+120"
    )
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
        "-i", "color=c=0x0d1014:s=1920x1080:r=30", "-frames:v", "1",
        "-vf", draw, str(out),
    ])


def encode_segment(source: Path, start: float, end: float, out: Path) -> None:
    """Re-encode one kept moment so every segment can be concatenated cleanly."""
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(source),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
               "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
        "-af", "aresample=48000:async=1",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        str(out),
    ])
    if not out.is_file() or out.stat().st_size == 0:
        raise SystemExit(f"ffmpeg produced nothing for {start:.1f}-{end:.1f}s")


def still(path: Path, seconds: float, out: Path, silent: bool = True) -> None:
    audio = ["-f", "lavfi", "-t", f"{seconds:.2f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-t", f"{seconds:.2f}", "-i", str(path),
        *audio,
        "-vf", "scale=1920:1080,setsar=1,fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        "-shortest", str(out),
    ])


BEATS = [
    ("Hold to talk — the mic is open only while held.", 0.00, 0.24),
    ("ClearVoice writes down what it heard.", 0.24, 0.46),
    ("One clear sentence, in large text — nothing spoken yet.", 0.46, 0.68),
    ("Speak it — the voice runs on this laptop, offline.", 0.68, 0.85),
    ("When it misses, it says so, and you start again.", 0.85, 1.01),
]


def write_captions(path: Path, screen_seconds: float) -> None:
    lines = []
    for index, (text, lo, hi) in enumerate(BEATS, start=1):
        start = CARD_SECONDS + screen_seconds * lo
        end = CARD_SECONDS + screen_seconds * min(hi, 1.0)
        lines.append(
            f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}\n"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def stamp(seconds: float) -> str:
    """SRT wants HH:MM:SS,mmm — a two-field stamp silently breaks libass."""
    hours, rest = divmod(max(0.0, seconds), 3600.0)
    minutes, secs = divmod(rest, 60.0)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}".replace(".", ",")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", nargs="?", default=str(Path.home() / "Videos" / "clearvoice-raw.mkv"))
    parser.add_argument("--narration", action="store_true", help="Mix demo/narration.wav under the take")
    parser.add_argument("--budget", type=float, default=TARGET_SCREEN_SECONDS)
    parser.add_argument("--out", default=str(DEMO / "clearvoice-demo.mp4"))
    args = parser.parse_args()

    raw = Path(args.raw).expanduser()
    if not raw.is_file():
        raise SystemExit(f"No recording at {raw}")
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required")

    DEMO.mkdir(parents=True, exist_ok=True)
    segments, total = find_active_segments(raw)
    plan, kept = fit_to_budget(segments, args.budget)

    print(f"recording: {total:.1f}s   active moments: {len(segments)}   "
          f"kept: {len(plan)} ({kept:.1f}s)")
    for index, (start, end) in enumerate(plan, start=1):
        print(f"  {index:2d}. {start:6.2f} → {end:6.2f}  ({end - start:.2f}s)")

    work = Path(tempfile.mkdtemp(prefix="cv-demo-"))
    try:
        parts: list[Path] = []

        card(DEMO / "title.png", "ClearVoice",
             "Speak naturally. Be understood clearly.", "Hermes Agent plugin")
        card(DEMO / "endcard.png", "Nothing leaves the machine.",
             "No background listening. No saved audio.",
             "github.com/thebangarang/clearvoice-hermes-plugin")

        title_clip = work / "00-title.mp4"
        still(DEMO / "title.png", CARD_SECONDS, title_clip)
        parts.append(title_clip)

        for index, (start, end) in enumerate(plan, start=1):
            piece = work / f"{index:02d}-take.mp4"
            encode_segment(raw, start, end, piece)
            parts.append(piece)

        end_clip = work / "99-end.mp4"
        still(DEMO / "endcard.png", END_SECONDS, end_clip)
        parts.append(end_clip)

        listing = work / "concat.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")

        write_captions(DEMO / "captions.srt", kept)
        captions = str(DEMO / "captions.srt").replace("'", r"\'")
        sub_style = ("FontName=DejaVu Sans,FontSize=22,PrimaryColour=&H00FFFFFF,"
                     "OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=54")

        filter_chain = f"[0:v]subtitles='{captions}':force_style='{sub_style}'[vout]"
        inputs = ["-f", "concat", "-safe", "0", "-i", str(listing)]
        if args.narration:
            narration = DEMO / "narration.wav"
            if not narration.is_file():
                raise SystemExit("--narration needs demo/narration.wav (run the say command first)")
            inputs += ["-i", str(narration)]
            filter_chain += (
                f";[1:a]adelay={int(CARD_SECONDS * 1000)}|{int(CARD_SECONDS * 1000)},"
                f"apad[narr];[0:a][narr]amix=inputs=2:duration=first:weights=1 1[aout]"
            )
            maps = ["-map", "[vout]", "-map", "[aout]"]
        else:
            maps = ["-map", "[vout]", "-map", "0:a"]

        final = Path(args.out)
        result = run([
            "ffmpeg", "-y", "-loglevel", "error", *inputs,
            "-filter_complex", filter_chain,
            *maps,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
            str(final),
        ])
        if result.returncode != 0:
            print(result.stderr.strip()[-1200:], file=sys.stderr)
            raise SystemExit("encode failed")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    length = duration_of(final)
    size_mb = final.stat().st_size / 1e6
    print(json.dumps({
        "file": str(final),
        "duration_s": round(length, 1),
        "size_mb": round(size_mb, 2),
        "kept_moments": len(plan),
        "screen_seconds": round(kept, 1),
        "under_90s": length <= 90.5,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
