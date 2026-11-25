"""Bounded periodic physical cleanup; revoked object keys are never reused."""
from __future__ import annotations

import asyncio
import logging

from backend.lib.material_archive import MaterialService, new_client, settings
from backend.lib.material_archive_schema import MaterialError

logger = logging.getLogger("ofe.material_cleanup")


def configured() -> bool:
    try:
        settings(for_storage_cleanup=True)
        return True
    except MaterialError:
        return False


async def cleanup_once() -> dict:
    url, key = settings(for_storage_cleanup=True)
    async with new_client() as client:
        service = MaterialService(client, url, key)
        jobs = [service.cleanup_tracker_versions()]
        try:
            settings()
        except MaterialError:
            pass  # Original-PDF archiving has its own feature switch.
        else:
            jobs.append(service.cleanup())
        results = await asyncio.gather(*jobs, return_exceptions=True)
        counts = {"claimed": 0, "succeeded": 0, "failed": 0}
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                logger.warning("storage_cleanup_source_unavailable")
                continue
            for key in counts:
                counts[key] += result[key]
        return counts


async def run_forever(stop: asyncio.Event) -> None:
    while not stop.is_set():
        # Also makes startup independent of storage availability. Unfinished
        # claims are durable and can be taken over by another worker after expiry.
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
            return
        except TimeoutError:
            pass
        try:
            result = await asyncio.wait_for(cleanup_once(), timeout=45)
            if result["claimed"]:
                logger.info("material_cleanup claimed=%d succeeded=%d failed=%d",
                            result["claimed"], result["succeeded"], result["failed"])
            if result["failed"]:
                logger.warning("material_cleanup_incomplete")
        except asyncio.CancelledError:
            raise
        except Exception:
            # Provider exceptions may contain user/object data or credentials.
            logger.warning("material_cleanup_unavailable")
