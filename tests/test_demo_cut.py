"""The demo cutter's pure parts, tested without touching ffmpeg."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("cut_demo", ROOT / "scripts" / "cut_demo.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load scripts/cut_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cut():
    return _load()


def test_stamp_is_three_field_srt_time(cut):
    # A two-field stamp parses as garbage in libass and the whole encode fails.
    assert cut.stamp(0) == "00:00:00,000"
    assert cut.stamp(3.5) == "00:00:03,500"
    assert cut.stamp(83.25) == "00:01:23,250"
    assert cut.stamp(3661.0) == "01:01:01,000"


def test_fit_to_budget_keeps_whole_moments(cut):
    plan, used = cut.fit_to_budget([(0, 10), (12, 22), (24, 34)], budget=40)
    assert plan == [(0, 10), (12, 22), (24, 34)]
    assert used == 30


def test_fit_to_budget_trims_rather_than_overflowing(cut):
    plan, used = cut.fit_to_budget([(0, 30), (31, 61), (62, 92)], budget=45)
    # The budget applies to kept *duration*, not to timestamps in the source.
    assert sum(end - start for start, end in plan) <= 45
    assert used <= 45
    assert plan[0] == (0, 30)
    assert plan[1][0] == 31 and plan[1][1] == 46


def test_fit_to_budget_drops_a_sliver_it_cannot_use(cut):
    plan, used = cut.fit_to_budget([(0, 20), (21, 40)], budget=20.5)
    assert plan == [(0, 20)]
    assert used == 20


def test_captions_never_run_past_the_video(cut, tmp_path):
    target = tmp_path / "captions.srt"
    cut.write_captions(target, screen_seconds=63.4)
    body = target.read_text(encoding="utf-8")
    stamps = [line for line in body.splitlines() if "-->" in line]
    assert len(stamps) == len(cut.BEATS)
    last_end = stamps[-1].split("-->")[1].strip()
    hours, minutes, rest = last_end.split(":")
    seconds = int(hours) * 3600 + int(minutes) * 60 + float(rest.replace(",", "."))
    assert seconds <= cut.CARD_SECONDS + 63.4 + 1.0
    assert ",000" in body  # millisecond separator, not a dot


def test_beats_are_ordered_and_bounded(cut):
    previous = 0.0
    for _text, lo, hi in cut.BEATS:
        assert lo >= previous
        assert hi > lo
        previous = hi
    assert cut.BEATS[0][1] == 0.0
    assert cut.BEATS[-1][2] >= 1.0
