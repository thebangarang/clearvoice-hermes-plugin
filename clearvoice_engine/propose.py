"""One place that decides how a transcript becomes a sentence.

The rule is simple and it is enforced here, not at each call site:

1. the local rule pack always produces a sentence — it is the fallback and the
   offline mode;
2. if the user turned on ``reframe_backend: gateway`` **and** the host offers a
   model, that model is asked for a better one;
3. a reply that fails validation is thrown away and the local sentence stands,
   with ``engine="local"`` so the pane can say what happened.

No audio ever reaches this module. In gateway mode the transcript text — and only
that — leaves the machine.
"""

from __future__ import annotations

from typing import Callable

from . import intent, langs, rewrite_llm
from .settings import Settings

Completer = Callable[..., object]


def propose(
    transcript: str,
    settings: Settings,
    *,
    language: str | None = None,
    complete: Completer | None = None,
) -> intent.Proposal:
    """The sentence ClearVoice will offer, and how it was produced."""
    code = (language or settings.language or "en").strip().lower()[:2]
    local = intent.reframe(transcript, settings.rewrite_style, language=code)

    if settings.reframe_backend != "gateway" or complete is None or not local.transcript:
        return local

    name = langs.get(code).label
    sentence, meta = rewrite_llm.rewrite(
        local.transcript, code, name, settings.rewrite_style, complete
    )
    if not sentence:
        # The model failed, timed out, or said something we refuse to show.
        local.reason = "local_fallback"
        return local

    rebuilt = intent.Proposal(
        transcript=local.transcript,
        message=sentence[: intent.MAX_MESSAGE_CHARS],
        intent=local.intent if local.intent != "unclear" else "request",
        confidence=max(local.confidence, 0.9),
        needs_confirmation=False,
        consequential=local.consequential,
        candidates=[sentence[: intent.MAX_MESSAGE_CHARS]],
        confirmation_question="",
        reason="",
        style=settings.rewrite_style,
        engine="gateway",
        cost_usd=meta.get("cost_usd"),
    )
    return rebuilt


def completer_from_ctx(ctx) -> Completer | None:
    """The host's model, if this plugin is allowed to use it. Never required."""
    if ctx is None:
        return None
    try:
        llm = ctx.llm
    except Exception:
        return None
    if llm is None:
        return None

    def call(messages, **kwargs):
        return llm.complete(messages, **kwargs)

    return call


def completer_from_host(plugin_id: str = "clearvoice") -> Completer | None:
    """Same thing for the dashboard router, which has no ``ctx`` object."""
    try:
        from agent.plugin_llm import PluginLlm
    except Exception:
        return None
    try:
        llm = PluginLlm(plugin_id=plugin_id)
    except Exception:
        return None

    def call(messages, **kwargs):
        return llm.complete(messages, **kwargs)

    return call
