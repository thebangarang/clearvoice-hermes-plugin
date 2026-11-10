"""Voice downloads: pinned revision, verified digest, nothing half-written.

The catalogue review asked for reproducible voice downloads. Two properties are
tested here, both without touching the network: a mismatched checksum is refused,
and a mismatched size is refused — the temporary file never becomes the model.
"""

from __future__ import annotations

import hashlib

import pytest

from clearvoice_engine import langs, piper


class FakeResponse:
    """Minimal stand-in for urlopen: headers + .read() chunks."""

    def __init__(self, payload: bytes, headers: dict[str, str]):
        self._payload = payload
        self._offset = 0
        self.headers = headers

    def read(self, size: int) -> bytes:
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _install(monkeypatch, payload: bytes, headers: dict[str, str]):
    monkeypatch.setattr(piper.urllib.request, "urlopen", lambda *a, **k: FakeResponse(payload, headers))


def test_a_verified_download_lands(monkeypatch, tmp_path):
    payload = b"RIFF" + b"\x00" * 4096
    digest = hashlib.sha256(payload).hexdigest()
    _install(monkeypatch, payload, {"x-linked-etag": f'"{digest}"', "x-linked-size": str(len(payload))})

    target = tmp_path / "voice.onnx"
    piper._download("https://example.invalid/voice.onnx", target)
    assert target.read_bytes() == payload
    assert not target.with_suffix(".onnx.part").exists()


def test_a_wrong_checksum_is_refused_and_nothing_is_kept(monkeypatch, tmp_path):
    payload = b"RIFF" + b"\x00" * 4096
    wrong = hashlib.sha256(b"something else entirely").hexdigest()
    _install(monkeypatch, payload, {"x-linked-etag": f'"{wrong}"', "x-linked-size": str(len(payload))})

    target = tmp_path / "voice.onnx"
    with pytest.raises(piper.PiperError) as err:
        piper._download("https://example.invalid/voice.onnx", target)
    assert "checksum" in str(err.value)
    assert not target.exists()
    assert not target.with_suffix(".onnx.part").exists()


def test_a_truncated_download_is_refused(monkeypatch, tmp_path):
    payload = b"RIFF" + b"\x00" * 4096
    digest = hashlib.sha256(payload).hexdigest()
    _install(
        monkeypatch,
        payload,
        {"x-linked-etag": f'"{digest}"', "x-linked-size": str(len(payload) + 10)},
    )

    target = tmp_path / "voice.onnx"
    with pytest.raises(piper.PiperError) as err:
        piper._download("https://example.invalid/voice.onnx", target)
    assert "incomplete" in str(err.value)
    assert not target.exists()


def test_a_config_without_a_digest_is_accepted(monkeypatch, tmp_path):
    # Small JSON files are served without an LFS digest; the revision pin covers them.
    payload = b'{"audio": {"sample_rate": 22050}}' + b" " * 2048
    _install(monkeypatch, payload, {})

    target = tmp_path / "voice.onnx.json"
    piper._download("https://example.invalid/voice.onnx.json", target)
    assert target.read_bytes() == payload


def test_the_url_is_pinned_to_a_commit():
    url = langs.piper_url("fr_FR-siwis-medium")
    assert "/resolve/main/" not in url
    assert langs.PIPER_REVISION in url
