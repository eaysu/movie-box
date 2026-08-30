"""One-time full watched-history crawl + incremental refresh runner.

Started in-process from ``POST /api/profile/sync``. A run walks the Letterboxd
diary window by window, checkpointing progress to ``profile_sync_jobs`` so a
Render free-tier restart mid-crawl is resumed on the user's next visit — the
``/api/profile/me`` poll re-spawns a job whose heartbeat has gone stale. No
external scheduler is required.

The runner is dependency-injected via a ``pipeline`` object (see
``main._SyncPipeline``) so it can be unit-tested without Supabase or the network.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger("uvicorn.error")

# `/films/` grid pages fetched per crawl step (~72 posters per page).
WATCHED_WINDOW_PAGES = 4
# Hard ceiling on films analysed in one full sweep.
FULL_MAX_FILMS = 10_000
# Director/keyword detail calls per checkpointed batch.
ENRICH_BATCH = 150
# A running job whose heartbeat is older than this is treated as abandoned.
HEARTBEAT_STALE_SECONDS = 180
# Process-wide cap on concurrent full crawls (the free tier is a single, small box).
MAX_CONCURRENT_JOBS = 2
# Cooldown after a hard failure before the job is retried.
FAILURE_BACKOFF = timedelta(minutes=30)
# Minimum gap between opportunistic incremental refreshes of a completed sweep.
INCREMENTAL_MIN_INTERVAL = timedelta(hours=6)

_job_sem = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
_running: set[int] = set()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def is_running(user_id: int) -> bool:
    return user_id in _running


def job_needs_full_sweep(job: dict | None) -> bool:
    """True when no full sweep has ever completed for this user."""
    if not job:
        return True
    if job.get("scope") != "full":
        return True
    return job.get("state") != "done"


def job_is_resumable(job: dict | None, *, now: datetime | None = None) -> bool:
    """True when a queued/running job should be (re)started in this process."""
    if not job or job.get("state") not in ("queued", "running"):
        return False
    now = now or _now()
    backoff = _parse_ts(job.get("backoff_until"))
    if backoff and backoff > now:
        return False
    if job.get("state") == "queued":
        return True
    heartbeat = _parse_ts(job.get("heartbeat_at"))
    return (
        heartbeat is None
        or (now - heartbeat).total_seconds() > HEARTBEAT_STALE_SECONDS
    )


def incremental_due(job: dict | None, *, now: datetime | None = None) -> bool:
    """True when a completed full sweep is stale enough for a cheap refresh."""
    if not job or job.get("state") != "done" or job.get("scope") != "full":
        return False
    now = now or _now()
    last = _parse_ts(job.get("updated_at"))
    return last is None or (now - last) >= INCREMENTAL_MIN_INTERVAL


def progress_of(job: dict | None) -> dict | None:
    if not job:
        return None
    state = job.get("state") or "queued"
    total = int(job.get("films_total") or 0)
    processed = int(job.get("films_processed") or 0)
    if state == "done":
        percent = 100
    elif total > 0:
        percent = min(99, round(processed / total * 100))
    else:
        percent = 0
    return {
        "state": state,
        "phase": job.get("phase") or "diary",
        "scope": job.get("scope") or "full",
        "processed": processed,
        "total": total,
        "percent": percent,
        "error": job.get("last_error") or "",
    }


async def ensure_started(
    pipeline, service, account, *, scope: str = "full", force: bool = False
) -> dict | None:
    """Create/queue the job row when needed and spawn the runner if idle.

    ``force`` re-queues a completed sweep from scratch (explicit "refresh").
    Returns the current (possibly freshly created) job row.
    """
    job = await asyncio.to_thread(service.get_sync_job, account.id)
    if (
        not force
        and scope == "full"
        and job
        and job.get("state") == "done"
        and job.get("scope") == "full"
    ):
        return job  # a full sweep already finished

    if force or job is None or job.get("state") in ("done", "failed"):
        job = await asyncio.to_thread(
            service.upsert_sync_job,
            account.id,
            state="queued",
            phase="diary",
            scope=scope,
            cursor_page=1,
            films_processed=0,
            films_total=0,
            attempts=0,
            last_error="",
            backoff_until=None,
        )

    if not is_running(account.id) and job_is_resumable(job):
        start(pipeline, service, account)
    return job


def start(pipeline, service, account) -> None:
    if is_running(account.id):
        return
    asyncio.create_task(run_job(pipeline, service, account))


async def run_job(pipeline, service, account) -> None:
    uid = account.id
    if uid in _running:
        return
    _running.add(uid)
    try:
        async with _job_sem:
            await _crawl(pipeline, service, account)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # keep the last good snapshot; retry after a cooldown
        log.warning("profile_sync job FAILED user=%s: %s", uid, exc)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(
                service.touch_sync_job,
                uid,
                state="failed",
                last_error=str(exc)[:400],
                backoff_until=(_now() + FAILURE_BACKOFF).isoformat(),
            )
    finally:
        _running.discard(uid)


async def _crawl(pipeline, service, account) -> None:
    uid = account.id
    job = await asyncio.to_thread(service.get_sync_job, uid) or {}
    if job.get("scope") == "incremental":
        await _incremental(pipeline, service, account)
        return
    phase = job.get("phase") or "diary"
    cursor = int(job.get("cursor_page") or 1)
    processed = int(job.get("films_processed") or 0)
    attempts = int(job.get("attempts") or 0) + 1
    await asyncio.to_thread(
        service.touch_sync_job, uid, state="running", attempts=attempts, last_error=""
    )

    known: set[str] = set(await asyncio.to_thread(service.get_watched_slugs, uid))

    # ── Phase 1 · walk the /films/ grid, search-enrich + persist each window ──
    while phase == "diary":
        window = await pipeline.scrape_watched_window(account.username, cursor)
        fresh: list[dict] = []
        for film in window:
            slug = (film.get("slug") or "").strip()
            if not slug or slug in known:
                continue
            # watched_rank is a running position: page order is "recently added"
            # first, so lower rank == more recent.
            film["watched_rank"] = processed + len(fresh)
            fresh.append(film)
            known.add(slug)
        if not fresh:
            phase = "enrich"
            break
        enriched = await pipeline.enrich_search(fresh)
        await asyncio.to_thread(service.save_watched_films, uid, enriched)
        processed += len(fresh)
        cursor += WATCHED_WINDOW_PAGES
        await asyncio.to_thread(
            service.touch_sync_job,
            uid,
            cursor_page=cursor,
            films_processed=processed,
            films_total=processed,
        )
        if processed >= FULL_MAX_FILMS:
            phase = "enrich"

    # ── Phase 2 · director/keyword details for rows still missing them ─────
    await asyncio.to_thread(service.touch_sync_job, uid, phase="enrich")
    rows = await asyncio.to_thread(service.get_watched_films, uid)
    pending = [r for r in rows if r.get("tmdb_id") and not r.get("details_loaded")]
    for offset in range(0, len(pending), ENRICH_BATCH):
        batch = pending[offset : offset + ENRICH_BATCH]
        detailed = await pipeline.enrich_details(batch)
        if detailed:
            await asyncio.to_thread(service.save_watched_films, uid, detailed)
        await asyncio.to_thread(service.touch_sync_job, uid, films_processed=processed)

    # ── Phase 3 · aggregate the full history into the snapshot ────────────
    await asyncio.to_thread(service.touch_sync_job, uid, phase="aggregate")
    total = await pipeline.rebuild_snapshot(account)
    await asyncio.to_thread(
        service.touch_sync_job,
        uid,
        state="done",
        phase="done",
        scope="full",
        films_total=total,
        films_processed=total,
        last_error="",
    )
    log.warning("profile_sync job DONE user=%s films=%d", uid, total)


async def _incremental(pipeline, service, account) -> None:
    """Cheap refresh of a completed sweep: only the last ~50 diary entries.

    New films are enriched and prepended (negative watched_rank keeps them
    ahead of the existing history); changed ratings are patched in place. The
    snapshot is only rebuilt when something actually changed.
    """
    uid = account.id
    await asyncio.to_thread(
        service.touch_sync_job, uid, state="running", phase="diary", last_error=""
    )
    known: set[str] = set(await asyncio.to_thread(service.get_watched_slugs, uid))
    existing = {
        row.get("film_slug"): row
        for row in await asyncio.to_thread(service.get_watched_films, uid)
    }
    recent = await pipeline.scrape_recent(account.username)

    new_films = [f for f in recent if f.get("slug") and f["slug"] not in known]
    rating_updates = [
        {"slug": f["slug"], "user_rating": f["user_rating"]}
        for f in recent
        if f.get("slug") in existing
        and f.get("user_rating") is not None
        and existing[f["slug"]].get("user_rating") != f["user_rating"]
    ]

    if new_films:
        for offset, film in enumerate(new_films):
            film["watched_rank"] = -(len(new_films) - offset)
        enriched = await pipeline.enrich_search(new_films)
        await asyncio.to_thread(service.save_watched_films, uid, enriched)
        detailed = await pipeline.enrich_details(enriched)
        if detailed:
            await asyncio.to_thread(service.save_watched_films, uid, detailed)
    if rating_updates:
        await asyncio.to_thread(service.save_watched_films, uid, rating_updates)

    if new_films or rating_updates:
        await asyncio.to_thread(service.touch_sync_job, uid, phase="aggregate")
        total = await pipeline.rebuild_snapshot(account)
    else:
        total = len(known)

    await asyncio.to_thread(
        service.touch_sync_job,
        uid,
        state="done",
        phase="done",
        scope="full",
        films_total=total,
        films_processed=total,
        last_error="",
    )
    log.warning(
        "profile_sync incremental user=%s new=%d rating_changes=%d",
        uid,
        len(new_films),
        len(rating_updates),
    )
