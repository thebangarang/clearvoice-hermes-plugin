# Decisions

Why ClearVoice is built the way it is, including the alternatives that were
rejected. Newest first.

---

## D-023 — The rejected experiment's packages leave the environment (2026-11-12)

**Decision.** `llama-cpp-python` and the `diskcache` it drags in are gone from
`.venv`. The plugin never imported either; D-017 rejected the small local model on
measured grounds, and the package stayed installed for six days after the decision.

**Why now, and why not a `# nosec`.** `dep-audit.py status` reported
`diskcache 5.6.3 — PYSEC-2026-2447` as *real*: DiskCache through 5.6.3 serialises
with pickle by default, so anyone who can write into the cache directory gets code
execution when it is read back. No fixed release is published, which makes
"upgrade" impossible and "accept" the tempting answer. The honest one is that the
package was not a dependency: `pyproject.toml` names `ptts`, `piper-tts`,
`faster-whisper` and `numpy`, nothing in the tree imports `diskcache` or
`llama_cpp`, and nothing else in the venv requires either. Removing an unused
package is strictly better than recording a risk on it.

**Cost.** None measured: 163 tests pass before and after, every engine imports,
and `dep-audit.py run` now reads Clearvoice as *no known vulnerabilities*. If the
model idea is ever revived (D-017 says it is not dead, only not this model on this
hardware), `llama-cpp-python` comes back carrying the same advisory — pin it
deliberately and point its cache at a directory only the plugin writes.

---

## D-022 — A model may queue a sentence; only a person can make it speak (2026-11-06)

**Decision.** `clearvoice_speak` and `clearvoice_say_back` no longer synthesise
anything for the room, and `confirm_required` is removed from both schemas. They
queue text. `/pending` returns that text plus a single-use, 120-second token and
**no audio**, so polling can never play anything. The pane shows the sentence as a
proposal, and `/speak` redeems the token only on the user's click — refusing a
wrong, missing, reused or expired one. Editing the sentence discards the token.

**Why.** Review found that the old flag was a parameter *the model* supplied: a
prompt-injected turn could call the tool with `confirm_required: false`, the handler
would synthesise immediately, and the pane's four-second `/pending` poll played
whatever it found. So "never text the user has not seen" was an instruction in a
description, not a property of the code — in the one product where that claim is the
whole argument. The fix moves the gate from a boolean to a capability: the model
cannot produce audio at all.

**Cost.** A tool call now needs a human press to have any audible effect, which is
the point, but it means an agent cannot "just speak" in an unattended pipeline.
`deliver: "file"` remains for that, writes a WAV instead of speaking, and stays off
until the user enables *Allow speech files*.

---

## D-021 — The language model path is deleted, not disabled (2026-11-05)

**Decision.** `clearvoice_engine/rewrite_llm.py`, the `reframe_backend` setting, the
pane toggle and their tests are removed. A transcript becomes a sentence through
rule packs only; there is no code path that can send it to a model.

**Why.** Two rounds of tightening were not enough: a chat model asked to help will
help, and the first prompt produced paraphrase, invented content and wrong detail.
A switch that can be turned back on is a promise waiting to be broken, and the
privacy claim is only worth something if it is absolute. "Nothing leaves the
machine" is now literal — the only outbound traffic left is model and voice
downloads, plus the Gradium backend if the user opts into cloud speech.

**Cost.** No model-assisted phrasing in any language. Ten languages get polish, not
re-ordering. Accepted: the plugin's value is being local and honest, and the sales
pitch is "your own words, clearly spoken back", not "an AI that says it better".

---

## D-020 — `small` everywhere, because the model was the accuracy problem (2026-11-05)

**Decision.** Every language now defaults to Whisper `small`: English was on
`tiny.en`, the other sixteen on `base`. Both remain selectable overrides.

**Measured** on four sentences (2 French, 2 English), real Piper audio, real
recogniser, on this 16-core CPU-only box:

| model | mean WER | mean time |
|---|---|---|
| `base` (was the default) | 9.4% | 1.1 s |
| `small` (**now**) | **3.1%** | 2.8 s |
| `medium` | 6.2% | 15.5 s |

`small` is three times more accurate than what we were shipping, and `medium` is
both slower and, on short clips, worse. So the "accuracy is far too low" report was
partly a default that had been chosen for latency we did not need: after the button
is released, 2.8 s is acceptable; mis-hearing someone is not.

**Cost.** First use downloads ~480 MB. On a machine that cannot afford it, `base`
is one setting away, and the README says what it costs in accuracy.

---

## D-019 — ClearVoice may tidy what you said; it may not improve it (2026-11-05)

**Decision.** `rewrite_style` now defaults to **verbatim**: the sentence offered is
the transcript, tidied at the edges. `courteous` — the rebuild — is an explicit
opt-in and exists only where a grammar pack can be checked. The optional model pass
may remove hesitations and fix punctuation, and **nothing else**: the reply must be
a subsequence of the transcript's words, or it is discarded.

**Why.** Asked to make fragmented speech "clear and polite", the connected model
did what chat models do: it paraphrased, dropped details and invented content
("it hallucinates a lot, it's going far from what I told"). For a person whose
speech is already hard to hear, a machine that improves their sentence has replaced
them — the exact failure this product exists to prevent. The brief's "propose a
clear sentence" was implemented as a rewrite; that was the mistake, and it was mine.

**Cost.** With verbatim by default the demo is less flattering: it shows a
transcript, not a language model's gift for prose. That is the honest product. The
rewrite remains available for people who want it, labelled as a rewrite, and only
in the seven languages whose grammar is checked.

---

## D-018 — The sentence can be rebuilt by the user's own model; the audio never leaves (2026-11-05)

*Reversed by D-021: the model path is deleted.*

**Decision.** `reframe_backend: gateway` (default `local`) sends the transcript
text, language and style hint to the model Hermes already configured — through
`ctx.llm` / `PluginLlm`, so the plugin holds no key and adds no vendor. The reply
is validated before display; on any failure the local rule-pack sentence stands and
the pane says the reply was rejected.

**Why.** A frontier model *could* rebuild fragmented speech in all seventeen
languages, which the rule packs do for seven. In practice it paraphrased and
invented, so the model's role was cut back to cleanup only — see D-019, which
supersedes the rewriting part of this decision.

**What is deliberately *not* claimed.** This does nothing for recognition. An LLM
never hears audio; ASR accuracy comes from the speech model and from speaker
adaptation, which is what Voiceitt (50–200 recorded phrase cards) and Google's
Project Relate (500 phrases, then a personal model) actually sell. Our dictionary
and learning loop is the cheap local approximation of that; proper adaptation is
the honest v0.6+ item.

**Cost.** Text leaves the machine when enabled, and the provider's retention then
applies — said in PRIVACY.md §3 and in the manifest description, not buried. The
validation rules are strict enough to reject a correct-but-unusual sentence
occasionally; the fallback makes that a quality issue, never a data one.

---

## D-017 — One engine, a table per language: seven rebuilt, ten polished (2026-11-05)

**Decision.** The reframing pipeline is shared (`intent_packs.py`); a language is
a `Pack` of four tables — verbs, time words, frame words + determiners, courtesy
template. Packs ship for English, French, German, Spanish, Italian, Portuguese and
Dutch. The other ten keep `polish()`, labelled `polished_only` in the pane.

**Why the shape changed.** French cost 379 lines because it re-implemented the
algorithm. Measured for this decision: 84 verb forms, and only four things vary
between languages. As a table, a language is ~80 lines and reviewable by a native
speaker; as a module it was a copy of the engine anyone would have to read first.
Verb-final order is one field of the table (`"{object}{time} bitte {verb}"`), which
is what made German and Dutch possible at all.

**Why a small local model was rejected — measured, not assumed.**
`llama-cpp-python` + Qwen2.5-1.5B-Instruct Q4 on this CPU box: model loads in 2.1 s,
median 2.7 s per sentence with a few-shot prompt. But on *fragmented* input — the
only input this product exists for — it produced "I need an appointment for Tuesday
and move." and "Je dois avoir un rendez-vous le mardi et déplacer.": it concatenates
fragments instead of restructuring them, and the 1.5B French/German output is not
grammatical. The size that would fix that (7B+) is ~10× slower on CPU, which no
push-to-talk flow survives. Rules stay the engine; the model idea is not dead, it
is just not this model on this hardware.

**Cost.** Ten languages still do not reorder. Said in the README, in the pane, and
in `reason`. Naming a limit is cheaper than a judge finding it.

---

## D-016 — Fifteen languages get "polished", not "rebuilt" — and the UI says which (2026-11-05)

*Superseded in part by D-017: five of those fifteen now have their own table.*

**Decision.** English and French have full rule packs. The other 15 get
`intent_langs.polish()`: punctuation tidied, first letter capitalised, the
language's own politeness word appended, and the confirmation question in that
language. Word order is never touched, `reason` is `polished_only`, and the pane
shows one line saying the sentence was tidied, not rebuilt.

**Why.** Full rebuilding needs per-language grammar — verbs, time expressions,
determiners, elision — that nobody native has checked for those 15. Shipping
grammar I cannot verify would produce sentences that read as broken to the very
people this is for. A polite, clean sentence with an honest label is worth more
than a confident wrong one.

**Cost.** A German user's fragmented speech is made polite but stays fragmented.
That is a real limit, and it is the reason a local rewrite model is the v0.4
plan rather than a "someday" idea: one model, all 17 languages, still offline.

**Extension path, in the order that makes sense.** (1) More packs: each is a
table plus native review, not a model — and a pack is code, so a speaker can
contribute one without any user data moving. (2) One small local model, which
scales to every language at once and costs disk and CPU latency. Neither is
needed for the hackathon.

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
