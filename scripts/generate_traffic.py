"""Continuously send deterministic demo traffic to the checkout service."""

import asyncio
import logging
import os
import random

import httpx

TARGET_URL = os.getenv("TRAFFIC_TARGET_URL", "http://localhost:8001/checkout")
REQUESTS_PER_SECOND = float(os.getenv("TRAFFIC_REQUESTS_PER_SECOND", "5"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("TRAFFIC_REQUEST_TIMEOUT_SECONDS", "10"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("traffic-generator")


async def generate_traffic() -> None:
    if REQUESTS_PER_SECOND <= 0:
        raise ValueError("TRAFFIC_REQUESTS_PER_SECOND must be greater than zero")

    interval = 1.0 / REQUESTS_PER_SECOND
    limits = httpx.Limits(max_connections=max(10, int(REQUESTS_PER_SECOND * 2)))
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, limits=limits) as client:
        while True:
            try:
                response = await client.get(TARGET_URL)
                logger.debug("checkout status=%s", response.status_code)
            except httpx.HTTPError as exc:
                logger.warning("checkout request failed: %s", exc)

            jitter = random.uniform(0.9, 1.1)  # noqa: S311
            await asyncio.sleep(interval * jitter)


if __name__ == "__main__":
    asyncio.run(generate_traffic())
