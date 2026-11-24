"""Slot rules with config: every 15 min, 09:00-17:00, Mon-Fri, 15-min calls.
2026-11-24 is a Tuesday, 2026-11-27 a Friday, 2026-11-28 a Saturday.
"""

import dataclasses

from flowpilot.slots import next_slot, round_up


def test_round_up(at):
    assert round_up(at(2026, 11, 24, 10, 7), 15) == at(2026, 11, 24, 10, 15)
    assert round_up(at(2026, 11, 24, 10, 15), 15) == at(2026, 11, 24, 10, 15)   # already on a mark
    assert round_up(at(2026, 11, 24, 10, 15, 30), 15) == at(2026, 11, 24, 10, 30)  # seconds count
    assert round_up(at(2026, 11, 24, 10, 50), 15) == at(2026, 11, 24, 11, 0)


def test_first_slot_during_working_hours(cfg, at):
    assert next_slot(at(2026, 11, 24, 10, 7), None, cfg) == at(2026, 11, 24, 10, 15)


def test_before_opening_moves_to_nine(cfg, at):
    assert next_slot(at(2026, 11, 24, 6, 30), None, cfg) == at(2026, 11, 24, 9, 0)


def test_call_must_finish_before_closing(cfg, at):
    # 16:45 + 15 min = 17:00 -> fits exactly
    assert next_slot(at(2026, 11, 24, 16, 40), None, cfg) == at(2026, 11, 24, 16, 45)
    # 17:00 + 15 min = 17:15 -> too late, next morning
    assert next_slot(at(2026, 11, 24, 16, 50), None, cfg) == at(2026, 11, 25, 9, 0)


def test_friday_evening_moves_to_monday(cfg, at):
    assert next_slot(at(2026, 11, 27, 18, 0), None, cfg) == at(2026, 11, 30, 9, 0)


def test_weekend_moves_to_monday(cfg, at):
    assert next_slot(at(2026, 11, 28, 11, 0), None, cfg) == at(2026, 11, 30, 9, 0)


def test_continues_after_last_booked_slot(cfg, at):
    now = at(2026, 11, 24, 10, 7)
    assert next_slot(now, at(2026, 11, 24, 14, 0), cfg) == at(2026, 11, 24, 14, 15)


def test_old_last_slot_does_not_schedule_in_the_past(cfg, at):
    now = at(2026, 11, 24, 10, 7)
    assert next_slot(now, at(2026, 11, 20, 14, 0), cfg) == at(2026, 11, 24, 10, 15)


def test_interval_is_configurable(cfg, at):
    cfg30 = dataclasses.replace(cfg, call_interval_minutes=30)
    assert next_slot(at(2026, 11, 24, 10, 7), at(2026, 11, 24, 10, 30), cfg30) == at(2026, 11, 24, 11, 0)
