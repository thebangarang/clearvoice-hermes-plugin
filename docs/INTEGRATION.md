# Using ClearVoice from somewhere else

ClearVoice is not only a pane. The same recogniser, voices and dictionary are
reachable four ways, in increasing order of coupling. Pick the loosest one that
does the job.

## 1. A shell command — for scripts, cron, and anything that speaks subprocess

```bash
hermes clearvoice say "The pharmacy closes at six." --json
hermes clearvoice hear /home/me/notes/voice-note.webm --json --reframe
hermes clearvoice say-back /home/me/notes/mum.webm --json --out /home/me/notes/clear.wav
```

`--json` prints one object and nothing else, so it pipes:

```bash
# Transcribe a folder of voice notes into text files
for f in ~/notes/*.webm; do
  hermes clearvoice hear "$f" --json | jq -r .transcript > "${f%.webm}.txt"
done

# Speak the weather every morning at 8 (cron)
hermes clearvoice say "$(curl -s wttr.in/?format=3)" --out /tmp/wx.wav
```

| Command | Arguments | Output (JSON fields) |
|---|---|---|
| `say` | `text`, `--voice`, `--backend`, `--language`, `--out` | `text`, `backend`, `voice`, `duration_s`, `file` |
| `hear` | `path`, `--language`, `--reframe` | `transcript`, `language`, `model`, `duration_s`, `corrections_applied`, `proposal` |
| `say-back` | `path`, `--language`, `--voice`, `--out` | `transcript`, `text`, `backend`, `duration_s`, `file` |

Exit codes: `0` success, `1` a plain-language failure on stderr, `2` bad usage.

## 2. An HTTP route — for a local app or a server on the same machine

The plugin mounts a router inside Hermes's gateway at `/api/plugins/clearvoice/`.
Every route speaks JSON, and audio crosses the wire as base64 — never as a file.

| Route | Body | Returns |
|---|---|---|
| `GET /status` | — | backends, language, voice, privacy line |
| `GET /languages`, `GET /voices?language=fr` | — | the pickers' data |
| `POST /transcribe` | `{audio_b64, mime, language?}` | `transcript`, `proposal`, `corrections_applied` |
| `POST /clarify` | `{transcript}` | `proposal` (the rewritten sentence) |
| `POST /speak` | `{message, approved: true, language?, voice?}` | `{audio_b64, mime, backend, duration_s}` |
| `POST /session/clear` | — | clears the session store |
| `GET/POST/DELETE /dictionary…` | terms and corrections | the dictionary |

It is **loopback only** and sits behind the gateway's own auth: it is a route for
a local companion app, not a network service. Audio never touches the disk on
this path.

## 3. A Python import — for another Hermes plugin or a local tool

`clearvoice_engine` is deliberately Hermes-free: no `ctx`, no gateway, no config
file. Point `sys.path` at the plugin directory and use it like any library.

```python
import sys
sys.path.insert(0, "/home/me/.hermes/plugins/clearvoice")

from clearvoice_engine import intent, lexicon, stt, tts
from clearvoice_engine.settings import Settings

settings = Settings.from_mapping({"language": "fr", "tts_backend": "auto"})
dictionary = lexicon.Lexicon("/home/me/.config/my-app")

text = stt.transcribe(Path("note.webm").read_bytes(), settings, lexicon=dictionary)
proposal = intent.reframe(text.text, settings.rewrite_style, language=settings.language)
audio = tts.synthesize(proposal.message, settings)      # WAV bytes, in RAM
```

The pieces are independent — a tool that only needs speech-to-text never imports
the synthesis engine, and none of them requires a model to be loaded twice.

## 4. Three tools for the agent — when Hermes itself is the integration

`clearvoice_transcribe`, `clearvoice_speak`, `clearvoice_say_back`. The bundled
skill (`skills/clearvoice/SKILL.md`) tells the model when to use each, and that
the approval gate (`confirm_required`) is not optional.

---

## The two rules that hold on every surface

1. **Nothing is stored.** Audio is decoded from bytes to arrays in memory on
   every path. The only writes are your own saved phrases, your dictionary, and
   the models — all in the plugin's data directory. `deliver: 'file'` / `--out`
   writes the *generated* speech, on purpose, because you asked for a file.
2. **Nothing is uploaded.** Cloud speech is refused unless you enabled it,
   selected the Gradium backend *and* set a key. Any refusal names the reason and
   the fix; none of them falls back silently.
