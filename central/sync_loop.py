"""
Scheduler for running `central.sync` inside the `sync` Docker container.

Native deployments use a platform scheduler for this instead -- systemd
timers on Linux (deploy/linux_server/asistencia-sync.timer, every 15 min)
or a Windows Scheduled Task (deploy/windows_server/install.ps1's -SyncTime,
once daily at 23:00 by default). Neither exists inside a plain container,
so this replaces them with an explicit loop, configurable the same two
ways via environment variables (first one set wins):

    SYNC_DAILY_AT=HH:MM      -- once a day at that time.
    SYNC_INTERVAL_MINUTES=N  -- every N minutes.

Defaults to SYNC_DAILY_AT=23:00 if neither is set, matching what's
already running in real production today (see CHANGELOG.md: the sync
schedule moved from every 15 min to once nightly specifically to cut
load) rather than silently reverting to a different cadence just because
this runs in a container now. The "Sincronizar" buttons in the panel
still work on demand any time, independent of this schedule.
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from central.db import init_db  # noqa: E402


def _run_once():
    # A separate process (not an in-process import of central.sync) so a
    # hang deep inside pyzk talking to a flaky device can't wedge this
    # scheduler loop itself -- the same isolation a systemd timer or a
    # Scheduled Task already gives each run on the native deployments.
    print(f"[sync_loop] {datetime.now().isoformat(timespec='seconds')} -- arrancando sincronización", flush=True)
    subprocess.run([sys.executable, "-m", "central.sync"], check=False)


def _seconds_until(hh_mm):
    target_h, target_m = (int(x) for x in hh_mm.split(":"))
    now = datetime.now()
    target = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def main():
    # Redundant with the init_db() call already inside sync_all() itself,
    # but cheap and idempotent (see central/db.py) -- kept here too so
    # this loop never depends on that staying true.
    init_db()

    interval_raw = os.environ.get("SYNC_INTERVAL_MINUTES")
    if interval_raw:
        interval_seconds = int(interval_raw) * 60
        print(f"[sync_loop] corriendo cada {interval_raw} minuto(s)", flush=True)
        while True:
            _run_once()
            time.sleep(interval_seconds)
    else:
        daily_at = os.environ.get("SYNC_DAILY_AT", "23:00")
        print(f"[sync_loop] corriendo una vez al día, a las {daily_at}", flush=True)
        while True:
            time.sleep(_seconds_until(daily_at))
            _run_once()


if __name__ == "__main__":
    main()
