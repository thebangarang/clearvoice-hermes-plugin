#!/usr/bin/env bash
# Build the ClearVoice demo video from a screen recording.
#
#   ./scripts/build_demo.sh ~/Videos/clearvoice-raw.mkv
#
# Produces demo/clearvoice-demo.mp4: 90 s, 1080p, title card, end card, burned
# captions and the on-device narration. Requires ffmpeg (and nothing else).
#
# The raw take is the only part a human must film: hold-to-talk, the sentence
# appearing, "Speak it", the deliberate failure. Everything after that is here.

set -euo pipefail

RAW="${1:-$HOME/Videos/clearvoice-raw.mkv}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO="$HERE/demo"
OUT="$DEMO/clearvoice-demo.mp4"
FONT="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DURATION=90

if [[ ! -f "$RAW" ]]; then
  echo "No recording at $RAW" >&2
  echo "Record once in OBS (screen capture + mic + desktop audio), then re-run." >&2
  exit 1
fi

command -v ffmpeg >/dev/null || { echo "ffmpeg is required" >&2; exit 1; }
mkdir -p "$DEMO"

# 1. Title card (0-5 s) and end card (82-90 s) as still images.
ffmpeg -y -loglevel error \
  -f lavfi -i "color=c=0x0d1014:s=1920x1080" -frames:v 1 \
  -vf "drawtext=fontfile=$FONT:text='ClearVoice':fontcolor=0xeef2f7:fontsize=96:x=(w-text_w)/2:y=(h-text_h)/2-70,\
drawtext=fontfile=$FONT:text='Speak naturally. Be understood clearly.':fontcolor=0x4c8dff:fontsize=44:x=(w-text_w)/2:y=(h-text_h)/2+40,\
drawtext=fontfile=$FONT:text='Hermes Agent plugin':fontcolor=0x7c8794:fontsize=28:x=(w-text_w)/2:y=(h-text_h)/2+130" \
  "$DEMO/title.png"

ffmpeg -y -loglevel error \
  -f lavfi -i "color=c=0x0d1014:s=1920x1080" -frames:v 1 \
  -vf "drawtext=fontfile=$FONT:text='No background listening.':fontcolor=0xeef2f7:fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2-110,\
drawtext=fontfile=$FONT:text='No saved audio.':fontcolor=0xeef2f7:fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2-20,\
drawtext=fontfile=$FONT:text='Nothing leaves the machine.':fontcolor=0x4c8dff:fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2+70,\
drawtext=fontfile=$FONT:text='github.com/thebangarang/clearvoice-hermes-plugin':fontcolor=0x7c8794:fontsize=28:x=(w-text_w)/2:y=(h-text_h)/2+190" \
  "$DEMO/endcard.png"

# 2. Narration (on-device Phonon voice). Regenerate only if missing.
if [[ ! -f "$DEMO/narration.wav" ]]; then
  hermes clearvoice say "$(cat "$DEMO/narration.txt")" --out "$DEMO/narration.wav" >/dev/null
fi

# 3. Assemble: trim the raw take to 77 s, wrap it in the two cards, lay the
#    narration over it, and burn the captions.
ffmpeg -y -loglevel error \
  -loop 1 -t 5 -i "$DEMO/title.png" \
  -i "$RAW" \
  -loop 1 -t 8 -i "$DEMO/endcard.png" \
  -i "$DEMO/narration.wav" \
  -f lavfi -t 77 -i "anullsrc=channel_layout=stereo:sample_rate=48000" \
  -filter_complex "\
[1:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,trim=start=0:duration=77,setpts=PTS-STARTPTS[mid];\
[0:v]format=yuv420p,setsar=1[title];\
[2:v]format=yuv420p,setsar=1[end];\
[title][mid][end]concat=n=3:v=1:a=0[vbase];\
[vbase]subtitles='$DEMO/captions.srt':force_style='FontName=DejaVu Sans,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=60'[vout];\
[3:a]adelay=5000|5000,apad[narr];\
[4:a][narr]amix=inputs=2:duration=longest:weights=1 1,volume=1.4[aout]" \
  -map "[vout]" -map "[aout]" -t "$DURATION" \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 30 \
  -c:a aac -b:a 160k -movflags +faststart \
  "$OUT"

echo "wrote $OUT"
ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$OUT"
