"""Typed, validated view of the plugin's settings.

Settings arrive as ``plugins.entries.clearvoice.settings`` from either entry
point (``ctx.get_config`` in the agent half, ``load_config_readonly`` in the
backend). This module turns that loose mapping into a frozen object with
impossible values coerced to the safe default — never to a cloud backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

STT_BACKENDS = ("local", "gradium")
TTS_BACKENDS = ("phonon", "gradium")
LANGUAGES = ("en", "fr", "de", "es", "pt")


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
    tts_backend: str = "phonon"
    language: str = "en"
    whisper_model: str = "tiny.en"
    phonon_voice: str = "default"
    gradium_voice_id: str = ""
    allow_cloud: bool = False
    has_gradium_key: bool = False

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None, *, has_key: bool = False) -> "Settings":
        data = dict(mapping or {})
        return cls(
            stt_backend=_as_choice(data.get("stt_backend"), STT_BACKENDS, "local"),
            tts_backend=_as_choice(data.get("tts_backend"), TTS_BACKENDS, "phonon"),
            language=_as_choice(data.get("language"), LANGUAGES, "en"),
            whisper_model=str(data.get("whisper_model") or "tiny.en").strip() or "tiny.en",
            phonon_voice=str(data.get("phonon_voice") or "default").strip() or "default",
            gradium_voice_id=str(data.get("gradium_voice_id") or "").strip(),
            allow_cloud=_as_bool(data.get("allow_cloud"), False),
            has_gradium_key=has_key or _as_bool(data.get("has_gradium_key"), False),
        )

    # --- derived state -----------------------------------------------------

    @property
    def network_used(self) -> bool:
        """True only when a cloud backend is both allowed and selected."""
        if not self.allow_cloud:
            return False
        return self.stt_backend == "gradium" or self.tts_backend == "gradium"

    def status(self) -> dict[str, Any]:
        """The Privacy Mode panel's data — one source of truth for the UI."""
        return {
            "stt_backend": self.stt_backend,
            "tts_backend": self.tts_backend,
            "stt_label": "On-device (faster-whisper)" if self.stt_backend == "local" else "Gradium cloud",
            "tts_label": "On-device (Phonon 31m)" if self.tts_backend == "phonon" else "Gradium cloud",
            "language": self.language,
            "whisper_model": self.whisper_model,
            "allow_cloud": self.allow_cloud,
            "has_gradium_key": self.has_gradium_key,
            "network": "Cloud optional" if self.allow_cloud else "Offline",
            "network_active": self.network_used,
            "retention": "Session only",
            "retention_line": "Audio processed this session only. Nothing saved.",
        }
