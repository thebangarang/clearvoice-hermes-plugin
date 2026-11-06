#!/usr/bin/env python3
"""Montage the three style takes into one demo, trimming the OBS UI off each.

Each source clip starts and ends on the OBS window before the ClearVoice pane is
shown. The trim points are taken from the audio: the first and last sound in each
clip is where the demo actually begins and ends, with a small guard band. No fixed
offsets, so a re-record works the same way.

Then it wraps the three in a title card and an end card, labels each style, and
writes one 1080p30 file with the original audio untouched.

    python3 scripts/montage_demo.py                    # uses ~/Videos/*.mkv
    python3 scripts/montage_demo.py --order courteous,literal,verbatim
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

TITLE_SECONDS = 3.0
END_SECONDS = 5.0
GUARD_START = 0.15   # start this much before the first sound
GUARD_END = 0.45     # keep this much after the last sound

INTRO_SLIDES = [
    ("Hold one button. Speak however you can.",
     "Your words appear, big and editable.",
     "Nothing is spoken until you approve it.", 5.0),
    ("On this machine, not in a cloud.",
     "Whisper small - about 3 percent word error, 2.8 seconds.",
     "No account, no upload, no saved audio.", 5.0),
]

DIVIDER = ("Three styles, one recording.",
           "Same request, said three ways.",
           "verbatim - literal - courteous", 3.0)

OUTRO_SLIDES = [
    ("Every mode is a tool, not just a button.",
     "clearvoice_transcribe - audio file to text",
     "clearvoice_speak - text to speech, in the pane or a WAV", 5.5),
    ("Drops into a workflow, a script, an app.",
     "clearvoice_say_back - listen, propose, speak",
     "Local HTTP routes, a Python import, and a bundled skill", 5.5),
    ("All of it runs here.",
     "Your voice never leaves the machine.",
     "The agent can use the same three tools you just saw.", 5.0),
]

STYLES = {
    "verbatim": {
        "file": "Verbatim.mkv",
        "badge": "1  VERBATIM",
        "line": "Exactly your words — only capital and full stop added.",
        "note": "Nothing was re-ordered, replaced or invented.",
    },
    "literal": {
        "file": "Litteral.mkv",
        "badge": "2  LITERAL",
        "line": "Your words, put into a plain order.",
        "note": "No politeness added, no meaning changed.",
    },
    "courteous": {
        "file": "Courteous.mkv",
        "badge": "3  COURTEOUS",
        "line": "The same request, rebuilt as a polite sentence.",
        "note": "Checked grammar from the rule pack - not a model guessing.",
    },
}


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def duration_of(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", str(path)]).stdout.strip()
    return float(out or 0)


def sound_span(path: Path, noise_db: int = -32, min_silence: float = 0.35) -> tuple[float, float]:
    """First and last moment with sound in the clip."""
    total = duration_of(path)
    log = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
               f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"]).stderr

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

    first_sound = 0.0
    for start, end in silences:
        if start <= 0.05:
            first_sound = end
        else:
            break

    # OBS often stops a fraction before the file ends, so the trailing silence is
    # not exactly "to the end" — a 0.4 s tolerance is what makes the tail trim fire.
    last_sound = total
    for start, end in reversed(silences):
        if end >= total - 0.4:
            last_sound = start
        else:
            break

    begin = max(0.0, first_sound - GUARD_START)
    finish = min(total, last_sound + GUARD_END)
    if finish - begin < 1.0:  # a clip with no detectable pause: keep it whole
        return 0.0, total
    return begin, finish


def _dt(text: str) -> str:
    """Escape a string for drawtext.

    drawtext treats "%" as the start of an expansion: a stray one makes it drop the
    whole line with only a warning ("Stray % near ..."), which is how a subtitle
    silently disappeared from the overview slide.
    """
    return (str(text)
            .replace("\\", "")
            .replace("%", "%%")
            .replace(":", r"\:")
            .replace("'", r"\'"))


def _fit(text: str, base: int, max_width: int = 1720, weight: float = 0.6) -> int:
    """Shrink a line until it fits the frame.

    A centred drawtext with a text wider than the frame gets clipped at both ends
    (x becomes negative) and silently loses the first and last words - which is how
    "So it drops into a workflow, a script, an app" became "it drops into ... api".
    """
    size = base
    while size > 24 and len(text) * weight * size > max_width:
        size -= 2
    return size


def card(out: Path, title: str, subtitle: str, footnote: str) -> None:
    title_size = _fit(title, 88)
    subtitle_size = _fit(subtitle, 42)
    footnote_size = _fit(footnote, 26)
    draw = (
        f"drawtext=fontfile={FONT}:text='{_dt(title)}':fontcolor=0xf2f5f8:fontsize={title_size}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-90,"
        f"drawtext=fontfile={FONT_REGULAR}:text='{_dt(subtitle)}':fontcolor=0x5b9dff:fontsize={subtitle_size}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+20,"
        f"drawtext=fontfile={FONT_REGULAR}:text='{_dt(footnote)}':fontcolor=0x8b96a3:fontsize={footnote_size}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+110"
    )
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=0x0d1014:s=1920x1080:r=30", "-frames:v", "1",
         "-vf", draw, str(out)])


def slide(text: tuple[str, str, str, float], work: Path, name: str) -> Path:
    """A text card: title, line, footnote, duration."""
    title, line, footnote, seconds = text
    image = work / f"{name}.png"
    card(image, title, line, footnote)
    clip = work / f"{name}.mp4"
    still(image, seconds, clip)
    return clip


def still(path: Path, seconds: float, out: Path) -> None:
    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-t", f"{seconds:.2f}",
         "-i", str(path), "-f", "lavfi", "-t", f"{seconds:.2f}",
         "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
         "-vf", "scale=1920:1080,setsar=1,fps=30,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
         "-shortest", str(out)])


def segment(source: Path, begin: float, end: float, style: dict, out: Path) -> None:
    """One trimmed clip, labelled with its style and a one-line explanation."""
    badge = (
        f"drawtext=fontfile={FONT}:text='{_dt(style['badge'])}':fontcolor=0x5b9dff:fontsize=34:"
        f"x=48:y=44:box=1:boxcolor=0x0d1014@0.72:boxborderw=14"
    )
    line = (
        f"drawtext=fontfile={FONT_REGULAR}:text='{_dt(style['line'])}':fontcolor=0xf2f5f8:fontsize=40:"
        f"x=(w-text_w)/2:y=h-150:box=1:boxcolor=0x0d1014@0.78:boxborderw=18:enable='between(t,0.25,7.5)'"
    )
    note = (
        f"drawtext=fontfile={FONT_REGULAR}:text='{_dt(style['note'])}':fontcolor=0x8b96a3:fontsize=28:"
        f"x=(w-text_w)/2:y=h-92:box=1:boxcolor=0x0d1014@0.78:boxborderw=16:enable='between(t,0.25,7.5)'"
    )
    chain = ",".join([
        "scale=1920:1080:force_original_aspect_ratio=decrease",
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
        "setsar=1", "fps=30", badge, line, note,
    ])
    result = run(["ffmpeg", "-y", "-loglevel", "error",
                  "-ss", f"{begin:.3f}", "-to", f"{end:.3f}", "-i", str(source),
                  "-vf", chain, "-af", "aresample=48000:async=1",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", str(out)])
    if result.returncode != 0 or not out.is_file():
        print(result.stderr.strip()[-800:], file=sys.stderr)
        raise SystemExit(f"could not encode {source.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=str(Path.home() / "Videos"))
    parser.add_argument("--order", default="verbatim,literal,courteous")
    parser.add_argument("--out", default=str(DEMO / "clearvoice-demo.mp4"))
    args = parser.parse_args()

    source_dir = Path(args.dir).expanduser()
    order = [name.strip() for name in args.order.split(",") if name.strip() in STYLES]
    if not order:
        raise SystemExit(f"No known styles. Expected a subset of {sorted(STYLES)}.")

    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required")

    DEMO.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="cv-montage-"))
    parts: list[Path] = []
    report = []

    try:
        card(DEMO / "title.png", "ClearVoice",
             "One recording, three ways to say it.",
             "All of it on this machine · no account · nothing saved")
        title_clip = work / "00-title.mp4"
        still(DEMO / "title.png", TITLE_SECONDS, title_clip)
        parts.append(title_clip)

        for index, intro in enumerate(INTRO_SLIDES, start=1):
            parts.append(slide(intro, work, f"01-intro-{index}"))

        parts.append(slide(DIVIDER, work, "02-divider"))

        for index, name in enumerate(order, start=1):
            spec = STYLES[name]
            source = source_dir / spec["file"]
            if not source.is_file():
                raise SystemExit(f"missing recording: {source}")
            begin, end = sound_span(source)
            piece = work / f"{index:02d}-{name}.mp4"
            segment(source, begin, end, spec, piece)
            parts.append(piece)
            report.append({
                "style": name,
                "source": source.name,
                "trim": [round(begin, 2), round(end, 2)],
                "kept_s": round(end - begin, 2),
            })
            print(f"{name:10s} trimmed to {end - begin:5.1f}s  ({begin:5.2f} -> {end:5.2f})")

        for index, outro in enumerate(OUTRO_SLIDES, start=1):
            parts.append(slide(outro, work, f"50-outro-{index}"))

        card(DEMO / "endcard.png", "Nothing leaves the machine.",
             "No background listening. No saved audio. No account.",
             "github.com/thebangarang/clearvoice-hermes-plugin")
        end_clip = work / "99-end.mp4"
        still(DEMO / "endcard.png", END_SECONDS, end_clip)
        parts.append(end_clip)

        listing = work / "concat.txt"
        listing.write_text("".join(f"file '{part}'\n" for part in parts), encoding="utf-8")

        final = Path(args.out)
        # Loudness-normalised to the web standard, so a phone speaker hears it.
        result = run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                      "-i", str(listing), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                      "-pix_fmt", "yuv420p", "-r", "30",
                      "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                      "-c:a", "aac", "-b:a", "160k",
                      "-movflags", "+faststart", str(final)])
        if result.returncode != 0:
            print(result.stderr.strip()[-1000:], file=sys.stderr)
            raise SystemExit("concat failed")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    length = duration_of(Path(args.out))
    print(json.dumps({
        "file": str(Path(args.out)),
        "duration_s": round(length, 1),
        "size_mb": round(Path(args.out).stat().st_size / 1e6, 2),
        "under_90s": length <= 90.5,
        "segments": report,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
