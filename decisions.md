# Decisions

Why ClearVoice is built the way it is, including the alternatives that were
rejected. Newest first.

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
