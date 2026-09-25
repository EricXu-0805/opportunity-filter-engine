"""Bounded periodic physical cleanup; revoked object keys are never reused."""
from __future__ import annotations

import asyncio
import logging

from backend.lib.material_archive import MaterialService, new_client, settings
from backend.lib.material_archive_schema import MaterialError

logger = logging.getLogger("ofe.material_cleanup")


def configured() -> bool:
    try:
        settings()
        return True
    except MaterialError:
        return False


async def cleanup_once() -> dict:
    url, key = settings()
    async with new_client() as client:
        return await MaterialService(client, url, key).cleanup()


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
