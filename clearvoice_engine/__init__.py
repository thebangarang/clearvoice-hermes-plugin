"""ClearVoice engine — speech clarity bridge internals.

Everything here is deliberately free of Hermes imports so the pipeline can be
unit-tested in isolation and so the same code serves both entry points:

* ``__init__.py``        — the agent half (tools, slash command)
* ``dashboard/plugin_api.py`` — the REST backend the Desktop pane talks to

Privacy invariants implemented by this package (see PRIVACY.md):

* no audio, transcript or generated speech is ever written to disk;
* the decoded utterance lives in a local variable and dies with the request;
* cloud backends refuse to run unless the user turned them on *and* selected
  them for that step.
"""

from __future__ import annotations

__all__ = [
    "audio",
    "cloud",
    "intent",
    "privacy",
    "settings",
    "stt",
    "tts",
]

__version__ = "0.1.0"
