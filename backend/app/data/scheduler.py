"""Background refresh jobs, one per source, timed after each source usually publishes (ET)."""

from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.data.service import DataService

TIMEZONE = "America/New_York"
INDIA_TIMEZONE = "Asia/Kolkata"

# (hour, minute) ET on weekdays. Treasury posts the par curve by about 6 pm; FRED updates its
# daily rates in the late afternoon; TIC releases at 4 pm on release days; FiscalData's debt
# figures appear by mid-afternoon.
REFRESH_TIMES: dict[str, tuple[int, int]] = {
    "fiscaldata": (16, 30),
    "tic": (16, 45),
    "fred": (17, 30),
    "treasury": (18, 30),
}

# (hour, minute) IST, every day: RBI posts the previous day's Money Market Operations in the
# morning and FBIL its T-bill and FX benchmarks by early evening and its G-sec valuation by about
# 7:30 pm; NSDL updates after the close.
INDIA_REFRESH_TIMES: dict[str, tuple[int, int]] = {
    "rbi": (10, 30),
    "fbil": (18, 15),
    "fbil_gsec": (20, 0),
    "nsdl": (20, 30),
}


def build_scheduler(service: DataService, *, startup_delay_s: float = 5.0) -> BackgroundScheduler:
    """Daily refresh jobs plus a one-off catch-up shortly after startup (stale sources only)."""
    scheduler = BackgroundScheduler(
        timezone=TIMEZONE,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
    )
    for source, (hour, minute) in REFRESH_TIMES.items():
        if source not in service.adapters:
            continue
        scheduler.add_job(
            service.refresh,
            CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone=TIMEZONE),
            args=[source],
            id=f"refresh:{source}",
            replace_existing=True,
        )
    for source, (hour, minute) in INDIA_REFRESH_TIMES.items():
        if source not in service.adapters:
            continue
        scheduler.add_job(
            service.refresh,
            CronTrigger(hour=hour, minute=minute, timezone=INDIA_TIMEZONE),
            args=[source],
            id=f"refresh:{source}",
            replace_existing=True,
        )
    scheduler.add_job(
        service.refresh_stale,
        "date",
        run_date=datetime.now(UTC) + timedelta(seconds=startup_delay_s),
        id="refresh:startup",
    )
    return scheduler
