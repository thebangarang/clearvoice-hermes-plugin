#!/usr/bin/env bash
# Build the ClearVoice demo video from a screen recording.
#
#   ./scripts/build_demo.sh ~/Videos/clearvoice-raw.mkv
#   ./scripts/build_demo.sh ~/Videos/clearvoice-raw.mkv --narration
#
# There is no cue sheet and no length to hit. Record yourself using the app once
# — hold the button, speak, press Speak it, make a mistake, try again — then run
# this. The cut points, the length and the captions come from the audio track of
# that recording, not from a script you have to perform.
#
# The work itself is in scripts/cut_demo.py, which is readable and tested.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec python3 "$HERE/scripts/cut_demo.py" "$@"
