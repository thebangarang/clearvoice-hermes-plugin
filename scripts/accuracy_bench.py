"""How accurate is the local recogniser in French, and does a lexicon help?

    python scripts/accuracy_bench.py

Speaks a French sentence with the on-device voice (so the audio is real speech,
not a synthetic tone), then transcribes it back with different Whisper sizes and
with a domain lexicon as a prompt. Prints word-error-rate against the reference.
Needs network the first time for the models (~75 MB base, ~480 MB small).
"""

from __future__ import annotations

import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from clearvoice_engine import stt, tts  # noqa: E402
from clearvoice_engine.settings import Settings  # noqa: E402

REFERENCES = [
    "Il faut déplacer mon rendez-vous de mardi à jeudi, s'il vous plaît.",
    "Rappelez le docteur Lefèvre à propos des ordonnances, merci.",
]

LEXICON = "Lefèvre, ordonnances, rendez-vous, kinésithérapeute, pharmacie, mutuelle"


def normalise(text: str) -> list[str]:
    text = text.lower().replace("'", " ").replace("’", " ")
    text = re.sub(r"[^\w\s-]", " ", text)
    return [word for word in text.split() if word]


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = normalise(reference), normalise(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    # Levenshtein over word lists.
    previous = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, start=1):
        current = [i]
        for j, hyp_word in enumerate(hyp, start=1):
            cost = 0 if ref_word == hyp_word else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1] / len(ref)


REPETITIONS = 3


def run(model_name: str, hotwords: str | None, lexicon=None) -> None:
    settings = Settings.from_mapping({"language": "fr"})
    stt.reset_local_models()
    scores: list[float] = []
    elapsed_all: list[float] = []
    label = model_name + (" +lexicon" if hotwords else "") + (" +dictionary" if lexicon is not None else "")
    for text in REFERENCES:
        spoken = tts.synthesize(text, settings)
        for _ in range(REPETITIONS):
            started = time.time()
            result = stt.transcribe_with_model(
                spoken.wav, settings, model_name=model_name, hotwords=hotwords
            )
            elapsed_all.append(time.time() - started)
            scores.append(wer(text, result.text))
    mean = sum(scores) / len(scores)
    spread = f"{min(scores) * 100:.1f}–{max(scores) * 100:.1f}%"
    print(f"  [{label:20}] mean WER {mean * 100:5.1f}%  ({spread} over {len(scores)} runs)  "
          f"mean {sum(elapsed_all) / len(elapsed_all):5.2f}s")


def main() -> int:
    print("reference sentences:")
    for line in REFERENCES:
        print("  -", line)
    print()
    for model_name in ("base", "small"):
        run(model_name, None)
    run("base", LEXICON)

    print("shipped path: stt.transcribe() with a personal dictionary")
    import tempfile

    from clearvoice_engine.lexicon import Lexicon

    lexicon = Lexicon(tempfile.mkdtemp(prefix="cv-lex-"))
    for term in ("Lefèvre", "ordonnances", "rendez-vous"):
        lexicon.add_term(term)
    lexicon.learn("le faire", "Lefèvre", enabled=True)

    settings = Settings.from_mapping({"language": "fr"})
    scores = []
    for text in REFERENCES:
        spoken = tts.synthesize(text, settings)
        for _ in range(REPETITIONS):
            started = time.time()
            result = stt.transcribe(spoken.wav, settings, lexicon=lexicon)
            elapsed = time.time() - started
            scores.append(wer(text, result.text))
            print(f"  [base +dictionary] {scores[-1] * 100:5.1f}% WER {elapsed:5.2f}s "
                  f"(corrections: {result.corrections_applied}) -> {result.text}")
    mean = sum(scores) / len(scores)
    print(f"  mean WER: {mean * 100:.1f}% over {len(scores)} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
