import json
import logging
import httpx
from typing import Any
from fastapi.encoders import jsonable_encoder

logger = logging.getLogger(__name__)

async def dispatch_webhook_async(url: str, payload: dict[str, Any]) -> bool:
    """Asynchronously dispatch a webhook payload to the designated URL."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json=jsonable_encoder(payload),
                headers={"Content-Type": "application/json", "User-Agent": "KnowledgeDrift-Webhook/1.0"}
            )
            response.raise_for_status()
            logger.info(f"Webhook dispatched successfully to {url}")
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"Webhook dispatch to {url} failed with status {e.response.status_code}: {e.response.text}")
    except Exception as e:
        logger.error(f"Webhook dispatch to {url} encountered an error: {e}")
    return False

def trigger_alert_webhook(org_id: str, alert_data: dict[str, Any]):
    """Synchronous wrapper for Celery worker webhook dispatch."""
    import os
    import asyncio

    webhook_url = os.getenv("ALERT_WEBHOOK_URL")
    if not webhook_url:
        logger.info(f"No ALERT_WEBHOOK_URL configured. Skipping webhook for Alert: {alert_data.get('id')}")
        return

    logger.info(f"Triggering webhook to {webhook_url} for Alert {alert_data.get('id')}")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(dispatch_webhook_async(webhook_url, alert_data))
        else:
            loop.run_until_complete(dispatch_webhook_async(webhook_url, alert_data))
    except RuntimeError:
        asyncio.run(dispatch_webhook_async(webhook_url, alert_data))
