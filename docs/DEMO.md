# Filming the demo — you do not perform

The old plan asked you to hit ten beats inside 90 seconds while driving a UI.
That is a video-editor's job, not a user's, and it is why this file exists: the
cut follows your recording instead of the other way round.

## What you actually do

1. Open ClearVoice in the Desktop app.
2. In OBS: **Start Recording**. (Screen capture + mic. Desktop audio on, so the
   app's own voice is in the take — that is the proof.)
3. Use ClearVoice the way you would use it for real:
   - hold the button, say something, let go
   - read the sentence it proposes
   - press **Speak it** and listen
   - switch to French and do it once in French
   - let it fail once — that is a feature, not a blemish
4. Press **Stop Recording**. Save to `~/Videos/clearvoice-raw.mkv`.

No length to hit. Fumbling at the start is fine, it gets cut. A long silence in
the middle is fine, it gets cut. Three minutes is fine, it gets cut to 90.

## What the build does with it

```
./scripts/build_demo.sh            # reads ~/Videos/clearvoice-raw.mkv
./scripts/build_demo.sh --narration   # same, plus the on-device voice-over
```

1. `silencedetect` reads the audio track and returns where you were active.
   Short gaps are merged so a sentence is never cut in half; the result is a
   handful of "moments".
2. Moments are kept in order until 86 seconds of screen are used up. Anything
   left over is dropped from the end, never from the middle of an action.
3. A 3-second title card, the kept moments, then a 4-second end card: 90 seconds
   at most, 1920×1080, 30 fps, `+faststart` for X.
4. Captions are placed on the moments it found, in the order the product works.
5. `demo/captions.srt` is written alongside. It is regenerated on every run, so
   change the wording in the `BEATS` table at the top of `scripts/cut_demo.py`,
   not in the .srt.

It prints the plan it chose before encoding:

```
recording: 82.4s   active moments: 5   kept: 5 (63.4s)
   1.   7.19 →  18.58  (11.39s)
   2.  21.08 →  38.23  (17.15s)
   ...
{"duration_s": 70.7, "kept_moments": 5, "under_90s": true}
```

## Rules that keep the demo honest

- **The voice in the video is the app's.** Narration is optional and mixed
  *under* your audio; never a substitute for it.
- **No mockups.** If a frame shows the pane, it is the pane.
- **The failure stays in.** A demo where the product is perfect is a demo nobody
  believes; the "it missed, here is what it says" moment is the part a speech
  therapist recognizes.
- **Say the limit out loud**, in the post or the end card: not a medical device,
  no speech therapy claim.

## If the recording is unusable

`scripts/cut_demo.py --budget 120` keeps more of the take. If the audio is dead
(the mic was muted), the file has no moments to find and the cutter will keep the
whole clip — check the "active moments" line; `1` means it heard nothing.
