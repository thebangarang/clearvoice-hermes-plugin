# Filming the demo

The demo is **three short takes, one per rewrite style**, recorded in one sitting,
then cut together automatically. You do not perform to a script and there is no
length to hit.

## What you record

Open ClearVoice, open OBS with screen capture + microphone + desktop audio (the
app's own voice in the take is the proof), then record three takes:

| Take | Save as | What to do in it |
|---|---|---|
| 1 | `~/Videos/Verbatim.mkv` | Set the style to **verbatim**, hold to talk, say a normal sentence with a name in it, release, read what appears, press **Speak it** |
| 2 | `~/Videos/Litteral.mkv` | Switch to **literal**, say the same kind of sentence, let it put your words in a plain order |
| 3 | `~/Videos/Courteous.mkv` | Switch to **courteous**, say a fragmented sentence, let the grammar pack rebuild it |

Press start/stop around each take; the OBS window at the head and tail of each file
is expected and gets removed. Fumbling, pauses and a second attempt are all fine.

## What the build does

```bash
python3 scripts/montage_demo.py             # ~/Videos/{Verbatim,Litteral,Courteous}.mkv
python3 scripts/montage_demo.py --no-music
python3 scripts/montage_demo.py --order courteous,verbatim,literal
```

1. **Trims the OBS UI.** `silencedetect` finds the first and last *sound* in each
   take and cuts 0.15 s before and 0.45 s after it. No fixed offsets, so a reshoot
   needs no new numbers.
2. **Labels each take.** A numbered badge top-left (`1 VERBATIM`), plus one line and
   one note for the first 7.5 s, e.g. *"Exactly your words — only capital and full
   stop added."*
3. **Frames it.** Title card (3 s), two intro slides, a divider, the three takes,
   three outro slides, end card (5 s). Outro covers the three tools, the API/import/
   skill surfaces, and that everything stays on the machine.
4. **Encodes** 1920×1080, 30 fps, AAC, `+faststart`, speech normalised to −16 LUFS
   with a generated drone 12 dB under it on the text cards only.

It prints the trims it chose before encoding:

```
verbatim   trimmed to  19.0s  ( 4.05 -> 23.09)
literal    trimmed to  10.2s  ( 3.34 -> 13.56)
courteous  trimmed to  14.0s  ( 3.60 -> 17.59)
```

## Rules that keep the demo honest

- **The voice in the video is the app's**, not a narrator's. The music bed is
  synthesised by ffmpeg, so there is nothing to license.
- **No mockups.** If a frame shows the pane, it is the pane.
- **Keep one imperfection.** A take where the recogniser misses something and you
  fix it says more than a perfect run.
- **Say the limit out loud**, in the post or the end card: not a medical device, no
  speech-therapy claim.

## Two traps worth knowing (both cost a render)

- **`drawtext` eats text containing `%`.** A stray `%` starts an expansion and the
  whole line is dropped with only a *"Stray % near …"* warning in the log — a
  subtitle can vanish without the render failing. Strings are escaped, and the copy
  says "3 percent" rather than "3%".
- **A centred `drawtext` wider than the frame is clipped at both ends**, silently
  losing the first and last words. Card text is sized to fit the frame now.

## If a take is unusable

Re-record only that one file with the same name and run the command again — the
other takes are untouched. If the audio is dead (muted microphone), the clip has no
sound to find and the cutter keeps it whole; check the "trimmed to" line, it will
show nearly the full length.
