"""The optional cloud rewrite: strict validation, and a silent local fallback.

The interesting tests are the refusals. A model that invents a day, swaps language
or paraphrases away the meaning must never become the sentence a person speaks to
a doctor, so every such reply is discarded and the local rule pack stands.
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
    mapping = {"language": "en", "rewrite_style": "courteous", "reframe_backend": "local"}
    mapping.update(overrides)
    return Settings.from_mapping(mapping)


# --- validation ------------------------------------------------------------


def test_a_faithful_rewrite_is_accepted():
    ok, why = rewrite_llm.validate(
        "Could you move the appointment to Tuesday, please?",
        "i need appointment tuesday move",
        "en",
    )
    assert ok, why


def test_an_invented_number_is_refused():
    # The single most damaging hallucination: a different day, dose or time.
    ok, why = rewrite_llm.validate(
        "Could you move the appointment to Tuesday at 3 pm, please?",
        "i need appointment tuesday move",
        "en",
    )
    assert not ok and why == "invented_number"


def test_a_number_that_was_said_is_allowed():
    ok, _ = rewrite_llm.validate(
        "Could you move the appointment to Tuesday at 3 pm, please?",
        "i need appointment tuesday 3 move",
        "en",
    )
    assert ok


@pytest.mark.parametrize(
    "reply,reason",
    [
        ("**Could you move it?**", "markdown"),
        ("\"Could you move the appointment?\"", "quoted"),
        ("First sentence. Second one. Third.", "not_one_sentence"),
        ("", "empty"),
        ("x" * 300, "too_long"),
    ],
)
def test_shapes_we_never_show(reply, reason):
    ok, why = rewrite_llm.validate(reply, "i need appointment tuesday move", "en")
    assert not ok and why == reason


def test_a_wrong_script_is_refused():
    ok, why = rewrite_llm.validate("Could you move the appointment?", "予約 移動", "ja")
    assert not ok and why == "wrong_script"


def test_total_loss_of_meaning_is_refused():
    ok, why = rewrite_llm.validate("Could you water the plants, please?", "pharmacy tomorrow", "en")
    assert not ok and why == "loss_of_meaning"


# --- the call --------------------------------------------------------------


def test_a_good_reply_comes_back_as_the_sentence():
    calls = {}

    def complete(messages, **kwargs):
        calls["messages"] = messages
        calls["kwargs"] = kwargs
        return FakeResult("Could you move the appointment to Tuesday, please?")

    sentence, meta = rewrite_llm.rewrite(
        "i need appointment tuesday move", "en", "English", "courteous", complete
    )
    assert sentence == "Could you move the appointment to Tuesday, please?"
    assert meta["ok"] is True and meta["model"] == "fake-model"
    assert meta["cost_usd"] == pytest.approx(0.00012)
    assert calls["kwargs"]["temperature"] == 0.0
    assert "English" in calls["messages"][1]["content"]


def test_a_model_that_raises_returns_nothing_instead_of_breaking():
    def complete(messages, **kwargs):
        raise RuntimeError("network down")

    sentence, meta = rewrite_llm.rewrite("hello there", "en", "English", "courteous", complete)
    assert sentence is None
    assert meta["ok"] is False and meta["reason"].startswith("error:")


# --- the routing -----------------------------------------------------------


def test_local_mode_never_touches_the_model():
    called = []

    def complete(messages, **kwargs):
        called.append(True)
        return FakeResult("Should not be used.")

    proposal = propose.propose("i need appointment tuesday move", settings(), complete=complete)
    assert called == []
    assert proposal.engine == "local"
    assert proposal.message == "Could you move the appointment to Tuesday, please?"


def test_gateway_mode_uses_the_model_and_says_so():
    def complete(messages, **kwargs):
        return FakeResult("Could you move the appointment to Tuesday, please?")

    proposal = propose.propose(
        "i need appointment tuesday move",
        settings(reframe_backend="gateway"),
        complete=complete,
    )
    assert proposal.engine == "gateway"
    assert proposal.needs_confirmation is False
    assert proposal.message.startswith("Could you move")


def test_gateway_mode_rebuilds_a_language_with_no_rule_pack():
    def complete(messages, **kwargs):
        return FakeResult("予約を火曜日に変更していただけますか。")

    proposal = propose.propose(
        "予約 火曜日 変える 必要",
        settings(reframe_backend="gateway", language="ja"),
        complete=complete,
    )
    assert proposal.engine == "gateway"
    assert proposal.message.startswith("予約")


def test_a_bad_reply_falls_back_to_the_local_sentence():
    def complete(messages, **kwargs):
        return FakeResult("Could you move the appointment to the moon at 9?")

    proposal = propose.propose(
        "i need appointment tuesday move",
        settings(reframe_backend="gateway"),
        complete=complete,
    )
    assert proposal.engine == "local"
    assert "moon" not in proposal.message
    assert proposal.message == "Could you move the appointment to Tuesday, please?"


def test_gateway_mode_without_a_model_stays_local():
    proposal = propose.propose(
        "i need appointment tuesday move",
        settings(reframe_backend="gateway"),
        complete=None,
    )
    assert proposal.engine == "local"
    assert proposal.message.startswith("Could you")


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
