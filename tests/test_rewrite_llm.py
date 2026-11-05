"""The optional model pass may only *clean* the transcript, never improve it.

The first version asked the model to rewrite fragmented speech into a polite
sentence, and it did — paraphrasing and sometimes inventing. These tests hold the
stricter contract now: the reply must be a subsequence of the user's own words, and
anything that adds or reorders a word is discarded in favour of the on-device
sentence.
"""

from __future__ import annotations

import pytest

from clearvoice_engine import propose, rewrite_llm
from clearvoice_engine.settings import Settings


class FakeResult:
    def __init__(self, text: str, cost: float | None = 0.00012):
        self.text = text
        self.model = "fake-model"
        self.usage = type("U", (), {"cost_usd": cost})()


def settings(**overrides):
    mapping = {"language": "en", "rewrite_style": "verbatim", "reframe_backend": "local"}
    mapping.update(overrides)
    return Settings.from_mapping(mapping)


# --- accepted: a cleanup of the same words --------------------------------


def test_hesitations_removed_is_accepted():
    ok, why = rewrite_llm.validate(
        "I need appointment tuesday move.",
        "i need, euh, appointment... tuesday... move",
        "en",
    )
    assert ok, why


def test_capital_and_full_stop_are_accepted():
    ok, why = rewrite_llm.validate(
        "I need appointment tuesday move.", "i need appointment tuesday move", "en"
    )
    assert ok, why


def test_japanese_cleanup_keeps_the_characters():
    ok, why = rewrite_llm.validate("予約 火曜日 変える 必要。", "予約 火曜日 変える 必要", "ja")
    assert ok, why


# --- refused: anything that speaks instead of the user --------------------


def test_an_added_word_is_refused():
    ok, why = rewrite_llm.validate(
        "I need the appointment on Tuesday.", "i need appointment tuesday move", "en"
    )
    assert not ok and why == "added_or_reordered_words"


def test_an_invented_politeness_phrase_is_refused():
    # Exactly what the model used to do: "Could you ... please?" was never said.
    ok, why = rewrite_llm.validate(
        "Could you move the appointment to Tuesday, please?",
        "i need appointment tuesday move",
        "en",
    )
    assert not ok and why == "added_or_reordered_words"


def test_reordered_words_are_refused():
    ok, why = rewrite_llm.validate("Tuesday move appointment.", "appointment tuesday move", "en")
    assert not ok and why == "added_or_reordered_words"


def test_dropping_half_the_sentence_is_refused():
    ok, why = rewrite_llm.validate(
        "Tuesday.", "i need appointment tuesday move pharmacy tomorrow", "en"
    )
    assert not ok and why == "dropped_too_much"


def test_a_wrong_script_is_refused():
    ok, why = rewrite_llm.validate("Could you move the appointment?", "予約 移動", "ja")
    assert not ok and why == "wrong_script"


@pytest.mark.parametrize(
    "reply,reason",
    [
        ("**I need it.**", "markdown"),
        ('"I need appointment."', "quoted"),
        ("First sentence. Second one. Third.", "not_one_sentence"),
        ("", "empty"),
        ("x" * 300, "too_long"),
    ],
)
def test_shapes_we_never_show(reply, reason):
    ok, why = rewrite_llm.validate(reply, "i need appointment tuesday move", "en")
    assert not ok and why == reason


# --- the call --------------------------------------------------------------


def test_a_cleanup_reply_comes_back_with_its_cost():
    calls = {}

    def complete(messages, **kwargs):
        calls["messages"] = messages
        calls["kwargs"] = kwargs
        return FakeResult("I need appointment tuesday move.")

    sentence, meta = rewrite_llm.rewrite(
        "i need appointment tuesday move", "en", "English", "verbatim", complete
    )
    assert sentence == "I need appointment tuesday move."
    assert meta["ok"] is True and meta["model"] == "fake-model"
    assert meta["cost_usd"] == pytest.approx(0.00012)
    assert calls["kwargs"]["temperature"] == 0.0
    assert "transcript" in calls["messages"][1]["content"].lower()


def test_a_model_that_raises_returns_nothing_instead_of_breaking():
    def complete(messages, **kwargs):
        raise RuntimeError("network down")

    sentence, meta = rewrite_llm.rewrite("hello there", "en", "English", "verbatim", complete)
    assert sentence is None
    assert meta["ok"] is False and meta["reason"].startswith("error:")


# --- routing ---------------------------------------------------------------


def test_local_mode_never_touches_the_model():
    called = []

    def complete(messages, **kwargs):
        called.append(True)
        return FakeResult("Should not be used.")

    proposal = propose.propose("i need appointment tuesday move", settings(), complete=complete)
    assert called == []
    assert proposal.engine == "local"
    # verbatim is the default: the user's own words, tidied at the edges only.
    assert proposal.message == "I need appointment tuesday move."


def test_gateway_mode_uses_the_model_for_a_cleanup():
    def complete(messages, **kwargs):
        return FakeResult("I need appointment tuesday move.")

    proposal = propose.propose(
        "i need, euh, appointment tuesday move",
        settings(reframe_backend="gateway"),
        complete=complete,
    )
    assert proposal.engine == "gateway"
    assert proposal.message == "I need appointment tuesday move."


def test_a_model_that_rewrites_falls_back_to_the_users_own_words():
    # The regression that made the feature untrustworthy: a "nicer" sentence the
    # speaker never said. It must never reach the pane.
    def complete(messages, **kwargs):
        return FakeResult("Could you please move the appointment to Tuesday?")

    proposal = propose.propose(
        "i need appointment tuesday move",
        settings(reframe_backend="gateway"),
        complete=complete,
    )
    assert proposal.engine == "local"
    assert proposal.reason == "local_fallback"
    assert proposal.message == "I need appointment tuesday move."


def test_gateway_mode_without_a_model_stays_local():
    proposal = propose.propose(
        "i need appointment tuesday move",
        settings(reframe_backend="gateway"),
        complete=None,
    )
    assert proposal.engine == "local"


def test_an_empty_transcript_is_not_sent_anywhere():
    called = []

    def complete(messages, **kwargs):
        called.append(True)
        return FakeResult("nope")

    proposal = propose.propose("", settings(reframe_backend="gateway"), complete=complete)
    assert called == []
    assert proposal.message == ""


def test_the_completers_are_optional_and_never_required():
    assert propose.completer_from_ctx(None) is None
    ctx = type("Ctx", (), {"llm": None})()
    assert propose.completer_from_ctx(ctx) is None
