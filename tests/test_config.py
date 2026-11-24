import pytest

from flowpilot.config import DEFAULT_CONFIG_PATH, load_config


def write_config(tmp_path, **overrides):
    """Copy the real config.toml, replacing some `key = value` lines."""
    lines = []
    for line in DEFAULT_CONFIG_PATH.read_text().splitlines():
        key = line.split("=")[0].strip()
        lines.append(f"{key} = {overrides[key]}" if key in overrides else line)
    path = tmp_path / "config.toml"
    path.write_text("\n".join(lines))
    return path


def test_real_config_loads():
    cfg = load_config()
    assert cfg.call_interval_minutes == 15
    assert str(cfg.timezone) == "Asia/Colombo"


def test_interval_change_needs_no_code_change(tmp_path):
    assert load_config(write_config(tmp_path, call_interval_minutes=20)).call_interval_minutes == 20


@pytest.mark.parametrize("overrides, message", [
    ({"call_interval_minutes": 0}, "call_interval_minutes must be positive"),
    ({"meeting_duration_minutes": -5}, "durations must be positive"),
    ({"working_hours_start": '"9am"'}, "must be HH:MM"),
    ({"working_hours_start": '"18:00"'}, "must be before working_hours_end"),
    ({"working_days": "[]"}, "working_days"),
    ({"working_days": "[1, 9]"}, "working_days"),
    ({"default_country_code": '"94"'}, "default_country_code"),
])
def test_bad_values_are_rejected_with_clear_message(tmp_path, overrides, message):
    with pytest.raises(ValueError, match=message):
        load_config(write_config(tmp_path, **overrides))
