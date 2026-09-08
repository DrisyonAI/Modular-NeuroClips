"""
Alert dispatch service for Modular-NeuroClips.
Sends structured event and security alert payloads to n8n webhook pipelines.
"""
import os
import time
import logging
import threading
from typing import Dict, Any, Optional

try:
    import requests
except ImportError:
    requests = None

from src.config import N8N_ALERT_WEBHOOK_URL, N8N_ALERTS_ENABLED

logger = logging.getLogger(__name__)


def dispatch_security_alert(
    event_data: Dict[str, Any],
    webhook_url: Optional[str] = None,
    timeout: int = 5,
    async_dispatch: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Dispatches a security or operational event payload to the n8n webhook.

    Args:
        event_data: Dict containing event payload, metadata, threat info, or error details.
        webhook_url: Override webhook URL. Defaults to N8N_ALERT_WEBHOOK_URL.
        timeout: Request timeout in seconds (default: 5).
        async_dispatch: If True, fires request in a background daemon thread without blocking.

    Returns:
        Response dictionary if synchronous and successful, or None.
    """
    if not N8N_ALERTS_ENABLED:
        logger.debug("n8n alert dispatch is disabled via N8N_ALERTS_ENABLED.")
        return None

    target_url = webhook_url or N8N_ALERT_WEBHOOK_URL

    payload = dict(event_data)
    if "timestamp" not in payload:
        payload["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if "source" not in payload:
        payload["source"] = "Modular-NeuroClips"

    def _send():
        if requests is None:
            logger.warning("requests package is not installed; cannot dispatch alert.")
            return None
        try:
            response = requests.post(target_url, json=payload, timeout=timeout)
            response.raise_for_status()
            try:
                return response.json()
            except Exception:
                return {"status": "ok", "status_code": response.status_code}
        except Exception as e:
            logger.error(f"Error dispatching to n8n production webhook: {e}")
            return None

    if async_dispatch:
        t = threading.Thread(target=_send, daemon=True)
        t.start()
        return {"status": "dispatched_async"}

    return _send()


def dispatch_threat_detection(
    threat_type: str,
    details: Dict[str, Any],
    severity: str = "high",
    async_dispatch: bool = True,
) -> Optional[Dict[str, Any]]:
    """Helper to dispatch security threat detection events."""
    event = {
        "event_type": "threat_detection",
        "threat_type": threat_type,
        "severity": severity,
        "details": details,
    }
    return dispatch_security_alert(event, async_dispatch=async_dispatch)


def dispatch_pipeline_failure(
    job_id: str,
    error_msg: str,
    metadata: Optional[Dict[str, Any]] = None,
    async_dispatch: bool = True,
) -> Optional[Dict[str, Any]]:
    """Helper to dispatch pipeline failure alarms to n8n."""
    event = {
        "event_type": "pipeline_failure",
        "job_id": job_id,
        "error": error_msg,
        "metadata": metadata or {},
    }
    return dispatch_security_alert(event, async_dispatch=async_dispatch)
