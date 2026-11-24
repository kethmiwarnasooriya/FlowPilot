"""Slot rules with config: every 15 min, 09:00-17:00, Mon-Fri, 15-min calls.
2026-11-24 is a Tuesday, 2026-11-27 a Friday, 2026-11-28 a Saturday.
"""

import dataclasses

from flowpilot.slots import next_free_slot, round_up


def test_round_up(at):
    assert round_up(at(2026, 11, 24, 10, 7), 15) == at(2026, 11, 24, 10, 15)
    assert round_up(at(2026, 11, 24, 10, 15), 15) == at(2026, 11, 24, 10, 15)   # already on a mark
    assert round_up(at(2026, 11, 24, 10, 15, 30), 15) == at(2026, 11, 24, 10, 30)  # seconds count
    assert round_up(at(2026, 11, 24, 10, 50), 15) == at(2026, 11, 24, 11, 0)


def test_first_slot_during_working_hours(cfg, at):
    assert next_free_slot(at(2026, 11, 24, 10, 7), [], cfg) == at(2026, 11, 24, 10, 15)


def test_before_opening_moves_to_nine(cfg, at):
    assert next_free_slot(at(2026, 11, 24, 6, 30), [], cfg) == at(2026, 11, 24, 9, 0)


def test_call_must_finish_before_closing(cfg, at):
    # 16:45 + 15 min = 17:00 -> fits exactly
    assert next_free_slot(at(2026, 11, 24, 16, 40), [], cfg) == at(2026, 11, 24, 16, 45)
    # 17:00 + 15 min = 17:15 -> too late, next morning
    assert next_free_slot(at(2026, 11, 24, 16, 50), [], cfg) == at(2026, 11, 25, 9, 0)


def test_friday_evening_moves_to_monday(cfg, at):
    assert next_free_slot(at(2026, 11, 27, 18, 0), [], cfg) == at(2026, 11, 30, 9, 0)


def test_weekend_moves_to_monday(cfg, at):
    assert next_free_slot(at(2026, 11, 28, 11, 0), [], cfg) == at(2026, 11, 30, 9, 0)


def test_skips_taken_slots(cfg, at):
    taken = [at(2026, 11, 24, 10, 15), at(2026, 11, 24, 10, 30)]
    assert next_free_slot(at(2026, 11, 24, 10, 7), taken, cfg) == at(2026, 11, 24, 10, 45)


def test_taken_slots_at_end_of_day_roll_over(cfg, at):
    taken = [at(2026, 11, 27, 16, 30), at(2026, 11, 27, 16, 45)]
    assert next_free_slot(at(2026, 11, 27, 16, 20), taken, cfg) == at(2026, 11, 30, 9, 0)


def test_future_callback_does_not_push_new_calls_back(cfg, at):
    # A callback booked for 9 December must not delay today's new contacts.
    taken = [at(2026, 12, 9, 9, 0)]
    assert next_free_slot(at(2026, 11, 24, 10, 7), taken, cfg) == at(2026, 11, 24, 10, 15)


def test_old_slots_do_not_matter(cfg, at):
    assert next_free_slot(at(2026, 11, 24, 10, 7), [at(2026, 11, 20, 14, 0)], cfg) == at(2026, 11, 24, 10, 15)


def test_slots_off_the_grid_still_keep_distance(cfg, at):
    # A slot at 10:20 (e.g. from an older config) blocks 10:15 and 10:30.
    assert next_free_slot(at(2026, 11, 24, 10, 7), [at(2026, 11, 24, 10, 20)], cfg) == at(2026, 11, 24, 10, 35)


def test_interval_is_configurable(cfg, at):
    cfg30 = dataclasses.replace(cfg, call_interval_minutes=30)
    assert next_free_slot(at(2026, 11, 24, 10, 7), [at(2026, 11, 24, 10, 30)], cfg30) == at(2026, 11, 24, 11, 0)
