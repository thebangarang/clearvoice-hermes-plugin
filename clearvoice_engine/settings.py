"""Typed, validated view of the plugin's settings.

Settings arrive as ``plugins.entries.clearvoice.settings`` from either entry
point (``ctx.get_config`` in the agent half, ``load_config_readonly`` in the
backend). This module turns that loose mapping into a frozen object with
impossible values coerced to the safe default — never to a cloud backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from . import langs

STT_BACKENDS = ("local", "gradium")
TTS_BACKENDS = ("auto", "phonon", "piper", "gradium")
REWRITE_STYLES = ("courteous", "literal", "verbatim")


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


@dataclass(frozen=True)
class Settings:
    stt_backend: str = "local"
    tts_backend: str = "auto"
    language: str = "en"
    voice: str = ""
    rewrite_style: str = "courteous"
    whisper_model: str = ""
    gradium_voice_id: str = ""
    allow_cloud: bool = False
    has_gradium_key: bool = False
    phrases_dir: str = ""
    allow_speech_files: bool = False
    learn_from_edits: bool = False

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None, *, has_key: bool = False) -> "Settings":
        data = dict(mapping or {})
        language = langs.get(data.get("language"))
        return cls(
            stt_backend=_as_choice(data.get("stt_backend"), STT_BACKENDS, "local"),
            tts_backend=_as_choice(data.get("tts_backend"), TTS_BACKENDS, "auto"),
            language=language.code,
            voice=str(data.get("voice") or "").strip(),
            rewrite_style=_as_choice(data.get("rewrite_style"), REWRITE_STYLES, "courteous"),
            whisper_model=str(data.get("whisper_model") or "").strip(),
            gradium_voice_id=str(data.get("gradium_voice_id") or "").strip(),
            allow_cloud=_as_bool(data.get("allow_cloud"), False),
            has_gradium_key=has_key or _as_bool(data.get("has_gradium_key"), False),
            phrases_dir=str(data.get("phrases_dir") or "").strip(),
            allow_speech_files=_as_bool(data.get("allow_speech_files"), False),
            learn_from_edits=_as_bool(data.get("learn_from_edits"), False),
        )

    # --- derived state -----------------------------------------------------

    def phrases_folder(self) -> Path | None:
        """The folder saved phrases go in, when the user chose one.

        Returns ``None`` when unset, relative, missing or not a directory — the
        caller then falls back to the plugin's own data directory instead of
        inventing a path.
        """
        raw = self.phrases_dir.strip()
        if not raw:
            return None
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute() or not candidate.is_dir():
            return None
        return candidate

    @property
    def language_info(self) -> langs.Language:
        return langs.get(self.language)

    @property
    def resolved_tts_engine(self) -> str:
        """Which engine will actually speak: auto = Phonon for English, Piper otherwise."""
        if self.tts_backend in ("phonon", "piper", "gradium"):
            return self.tts_backend
        return self.language_info.tts_engine

    @property
    def resolved_voice(self) -> str:
        if self.voice:
            return self.voice
        if self.resolved_tts_engine == "phonon":
            return "default"
        if self.resolved_tts_engine == "gradium":
            return self.gradium_voice_id or "default"
        return self.language_info.default_voice

    @property
    def stt_model(self) -> str:
        return langs.whisper_model_for(self.language_info, self.whisper_model)

    @property
    def network_used(self) -> bool:
        """True only when a cloud backend is both allowed and selected."""
        if not self.allow_cloud:
            return False
        return self.stt_backend == "gradium" or self.resolved_tts_engine == "gradium"

    def status(self) -> dict[str, Any]:
        """The Privacy Mode panel's data — one source of truth for the UI."""
        language = self.language_info
        engine = self.resolved_tts_engine
        engine_labels = {
            "phonon": "Phonon 31m (Apache-2.0)",
            "piper": "Piper (local)",
            "gradium": "Gradium cloud",
        }
        return {
            "stt_backend": self.stt_backend,
            "tts_backend": engine,
            "stt_label": "On-device (faster-whisper)" if self.stt_backend == "local" else "Gradium cloud",
            "tts_label": engine_labels.get(engine, engine),
            "voice": self.resolved_voice,
            "language": language.code,
            "language_label": language.label,
            "language_native": language.native,
            "languages": [lang.public() for lang in langs.all_languages()],
            "rewrite_style": self.rewrite_style,
            "stt_model": self.stt_model,
            "allow_cloud": self.allow_cloud,
            "has_gradium_key": self.has_gradium_key,
            "network": "Cloud optional" if self.allow_cloud else "Offline",
            "network_active": self.network_used,
            "model_source": "huggingface.co (weights only, once per model)",
            "retention": "Session only",
            "retention_line": "Audio processed this session only. Nothing saved.",
        }
