"""Entry point: `python -m flowpilot`. Will grow into the full CLI later."""

from flowpilot.config import load_config


def main() -> None:
    cfg = load_config()
    print("FlowPilot config loaded:")
    print(f"  Call interval : every {cfg.call_interval_minutes} min")
    print(f"  Working hours : {cfg.working_hours_start:%H:%M}-{cfg.working_hours_end:%H:%M}")
    print(f"  Working days  : {cfg.working_days}")
    print(f"  Timezone      : {cfg.timezone}")
    print(f"  Schedule file : {cfg.schedule_file}")


if __name__ == "__main__":
    main()
