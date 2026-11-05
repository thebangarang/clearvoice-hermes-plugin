# Decisions

Why ClearVoice is built the way it is, including the alternatives that were
rejected. Newest first.

---

## D-015 — The reframer has a rule pack per language, not one English rule set (2026-11-05)

**Decision.** `intent.py` keeps the English rules; `intent_fr.py` holds a French
pack (verb forms, time spans, determiners with elision, classification,
"Pourriez-vous … s'il vous plaît ?"). `reframe(text, style, language=)` dispatches,
the recogniser's language is preferred, and `guess_language()` decides only when
the caller has none — defaulting to English on a tie.

**Why.** One rule set written for English finds no verb, no time word and no
frame in French, so it returns the transcript unchanged. That is not a small
inaccuracy: it means the product silently does nothing in the user's own
language, and the difference is instantly visible ("in english it puts the words
in order, in french it's literally the exact thing I said").

**Cost.** Every new language is a table to write, not a model to call. Only
English and French exist today; the other 15 have speech in and out, but their
sentences are only tidied at the edges. Said plainly in the README rather than
implied.

---

## D-014 — The demo is cut from the take, not performed to a script (2026-11-05)

**Decision.** The demo video is produced by `scripts/cut_demo.py`, which reads
the audio track of a natural screen recording, finds the active moments, drops
dead air, and fits 90 seconds. Captions and cut points follow the recording. The
on-device narration is optional and never replaces the take's own audio.

**Why.** The first version asked a non-video-editor to hit ten beats inside 90
seconds while driving a UI, against a fixed 64-second narration. That is not a
thing a person can do, and the honest reading of "it's almost impossible for me
to shoot it" is that the pipeline was wrong, not the user. Deriving the cut from
`silencedetect` costs nothing and makes the recording burden ~3 minutes of
ordinary use.

**Cost.** The video is only as good as the take; a muted microphone yields no
moments and the cutter keeps the whole clip. The "active moments" line makes that
visible instead of silently producing a bad video.

---

## D-013 — Accuracy comes from a personal dictionary, not from training (2026-11-05)

**Decision.** Accuracy work is: hotwords from a user's own word list, plus
corrections learned from their edits. No fine-tuning, no cloud training, no
shared corpus.

**Why.** Measured (`scripts/accuracy_bench.py`, French, 6 runs per condition):
`base` 22.6% WER, `small` 5.6% at 2.8 s, `base` + hotword list 5.6% at 0.99 s,
`base` + dictionary 3.8% at 0.89 s. The dictionary wins on both axes. Fine-tuning
Whisper needs hours of paired audio per speaker, a GPU, degrades ordinary
speech, and would require keeping recordings of an impaired voice — the exact
data the product promises not to keep.

**Cost.** The dictionary only knows what the user teaches it; a first session is
as inaccurate as before. Stated plainly in the pane.

---

## D-012 — No community dictionary, ever (2026-11-05)

**Decision.** Learned corrections and word lists stay on the machine. There is no
export-to-community, no pack download, no shared corpus.

**Why.** A dictionary of a person's recurring sentences, names, treatments and
addresses is health-adjacent personal data. Aggregating it — even "anonymised" —
is processing under GDPR with no lawful basis this project can offer, and the
people it protects are the least able to consent meaningfully. The value of a
shared pack does not outweigh that.

**Cost.** Every user starts from zero. Accepted.

---

## D-011 — The pane's language/voice choice is a per-request override (2026-11-05)

**Decision.** The pane sends `language`, `voice` and `rewrite_style` in the
request body; the backend merges them over the saved settings for that request
only. The pane remembers its choice in `ctx.storage`.

**Why.** The alternative was for the pane to write `config.yaml`, which means a
renderer component asking for config-write authority it does not need, and two
places that can disagree about the active language. Per-request overrides keep
the write path where it belongs (a user editing Settings) and make the pane's
choice auditable in the request that used it.

**Cost.** A user who always wants French sets it once in Settings; a user who
switches per conversation gets that for free.

---

## D-010 — Multilingual synthesis uses Piper, not Phonon multilingual (2026-11-05)

**Decision.** English is voiced by Phonon 31m (Apache-2.0). The other 16
languages are voiced by Piper (MIT runtime, per-voice models).

**Why.** `ptts.TTS(lang='fr')` does not load a French model — it loads the same
English checkpoint and only changes text normalisation (verified: `languages` is
still `['en']`, and it warns "text is normalized as fr, but the model was trained
for en"). The actual multilingual Phonon checkpoint is **CC BY-NC**, which cannot
ship in an MIT plugin a business may deploy. Piper is MIT and covers every
language asked for — including Japanese, Chinese, Korean, Thai and Hindi — with
108 indexed voices.

**Cost.** Two engines to maintain, and non-English quality is below Phonon's.
Both are stated in the README rather than discovered by a user.

---

## D-009 — Three rewrite styles instead of one (2026-11-05)

**Decision.** `courteous` (default) rebuilds a polite request; `literal` keeps
the user's words in a plain order; `verbatim` changes only the edges.

**Why.** The courteous rewrite is the brief's flow and reads best aloud, but the
first real user reaction was "it feels like it's really changing the sentence" —
and that instinct is correct: rewriting someone's words without their consent is
exactly the failure mode this plugin is supposed to avoid. Making it a visible,
persistent choice keeps the useful default and hands the authority back.

**Cost.** One more control in the pane; a settings row that has to be understood.
Worth it: "who decided what I said" must never be the software's answer.

---

## D-008 — Deterministic reframer instead of an LLM call (2026-11-05)

**Decision.** The "infer the intended message" step is a rule engine over the
transcript: filler removal, intent classification, slot extraction (verb, object,
time), courteous reconstruction, confidence score, candidate list.

**Why.** An LLM call would mean sending a transcript of an impaired voice to a
model provider on every push-to-talk turn, in the default path of a plugin whose
entire promise is "nothing leaves the device". It would also add 0.5–2 s to the
loop the user is standing in the middle of, and make the output
non-deterministic, which makes the tests meaningless.

**Cost accepted.** Elliptical phrasing outside the slot patterns is handled
poorly. Mitigation: when confidence is low the plugin shows up to three
candidates and asks, instead of guessing. Documented as a limitation in the
README rather than hidden.

**Alternative rejected.** Optional LLM refinement via `ctx.llm`. It would be a
second data path to disclose and gate, for a marginal quality gain on a step the
user reads anyway.

---

## D-007 — Two independent approval gates (2026-11-05)

**Decision.** `clearvoice_speak` refuses to speak unless `confirm_required:
false`, and `POST /speak` refuses unless `approved: true`. Only the pane's
**Speak it** click handler sets either.

**Why.** A model that can call a speech tool can put words in the mouth of a
person who cannot easily correct it. One gate is a convention; two gates in two
processes is a design. The default is refusal, so forgetting to pass a flag
fails safe.

**Cost.** The agent needs two tool calls to say something. That is the intended
cost.

---

## D-006 — Audio never touches the filesystem (2026-11-05)

**Decision.** Decoding, transcription, synthesis and playback all operate on
bytes and arrays in memory. No WAV cache, no temp file, no `tempfile` usage
anywhere. `ffmpeg` is driven over stdin/stdout pipes.

**Why.** "Nothing saved" is the promise a person needs to believe before they
speak in a hospital bed. A temp file that is *usually* deleted is not the same
promise. It is also trivially verifiable: a CPython audit hook sees every
`open()` and the test asserts zero write-mode calls during a full run.

**Cost.** A crash mid-turn loses the clip. Acceptable: the user holds a button,
they can hold it again.

---

## D-005 — Desktop UI as one uncompiled `plugin.js` (2026-11-05)

**Decision.** `desktop/plugin.js` with `jsx()` calls instead of the four `.tsx`
files in the brief.

**Why.** The Desktop app loads a disk plugin uncompiled: JSX cannot be parsed,
and only `@hermes/plugin-sdk`, `react` and `react/jsx-runtime` resolve. A `.tsx`
tree would need a build step the loader does not run. The four named components
exist as separate components inside the one module.

---

## D-004 — Engine as `clearvoice_engine/`, not `clearvoice/clearvoice/` (2026-11-05)

**Decision.** Flat, uniquely-named package at the plugin root.

**Why.** The plugin directory is imported by path (its name is not a valid Python
identifier), and a nested package with the same name as its parent breaks
path-based imports. Both entry points import `clearvoice_engine` after a one-line
`sys.path` insert, so the agent half, the REST backend and the tests share one
module instance — which is what makes the in-process audio outbox work.

---

## D-003 — Phonon 31m only, via `ptts` (2026-11-05)

**Decision.** `ptts` (Gradium's official runtime) with the Apache-2.0 Phonon 31m
English checkpoint. The CC BY-NC 40m models are not referenced anywhere.

**Why.** Apache-2.0 is usable in a MIT plugin a business may adopt; CC BY-NC is
not. 31m at 64 MB runs on a CPU and starts speaking in about a second, which is
the right trade for a device people carry to a doctor's appointment.

**Cost.** One built-in voice, English only. Both stated in the limitations.

---

## D-002 — faster-whisper for local STT (2026-11-05)

**Decision.** faster-whisper with `tiny.en` by default, model selectable in
settings.

**Why.** MIT-licensed, no GPU required, small enough to download on first use,
and accurate enough on short clear clips. The alternative — a cloud STT — would
break the default-path privacy promise.

**Cost.** `tiny.en` mangles unusual vocabulary. Mitigation: the sentence is always
shown before it is spoken, so an error costs an edit, not a wrong statement.

---

## D-001 — Gradium cloud as a triple-gated opt-in (2026-11-05)

**Decision.** Cloud speech requires three independent conditions: *Allow cloud
speech* on, the backend selector set to Gradium, and a key present. No automatic
fallback from local to cloud.

**Why.** The brief asks for the Gradium path to exist and to stay off. Making it
three-way explicit means no single misconfiguration can send a recording of an
impaired voice to a vendor, and the pane can state which backend is live without
ambiguity (`Network: Offline` / `Cloud optional`).

**Cost.** A user who wants cloud speech flips three things instead of one. That is
the point.
