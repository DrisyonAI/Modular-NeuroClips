"""
Unit tests for the n8n alert dispatch service.
"""
from unittest.mock import patch, MagicMock
import requests
from src.services.alert_dispatcher import (
    dispatch_security_alert,
    dispatch_threat_detection,
    dispatch_pipeline_failure,
)


def test_dispatch_security_alert_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True, "executionId": "123"}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        result = dispatch_security_alert(
            {"event": "test_event", "details": "all clear"},
            webhook_url="https://n8n.mytestbed.tech/webhook/alert-dispatch",
            async_dispatch=False,
        )

        assert result == {"success": True, "executionId": "123"}
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://n8n.mytestbed.tech/webhook/alert-dispatch"
        assert kwargs["json"]["event"] == "test_event"
        assert kwargs["json"]["source"] == "Modular-NeuroClips"
        assert "timestamp" in kwargs["json"]


def test_dispatch_security_alert_request_exception():
    with patch("requests.post", side_effect=requests.exceptions.ConnectTimeout("Timed out")):
        result = dispatch_security_alert(
            {"event": "timeout_test"},
            async_dispatch=False,
        )
        assert result is None


def test_dispatch_security_alert_disabled(monkeypatch):
    import src.services.alert_dispatcher as ad
    monkeypatch.setattr(ad, "N8N_ALERTS_ENABLED", False)

    with patch("requests.post") as mock_post:
        result = ad.dispatch_security_alert({"event": "should_not_run"})
        assert result is None
        mock_post.assert_not_called()


def test_dispatch_threat_detection_helper():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"queued": True}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        result = dispatch_threat_detection(
            threat_type="prompt_injection",
            details={"ip": "1.2.3.4", "input": "ignore instructions"},
            severity="critical",
            async_dispatch=False,
        )

        assert result == {"queued": True}
        kwargs = mock_post.call_args[1]
        assert kwargs["json"]["event_type"] == "threat_detection"
        assert kwargs["json"]["threat_type"] == "prompt_injection"
        assert kwargs["json"]["severity"] == "critical"


def test_dispatch_pipeline_failure_helper():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"acknowledged": True}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        result = dispatch_pipeline_failure(
            job_id="job-abc-123",
            error_msg="CUDA OOM",
            metadata={"vram_used": 15900},
            async_dispatch=False,
        )

        assert result == {"acknowledged": True}
        kwargs = mock_post.call_args[1]
        assert kwargs["json"]["event_type"] == "pipeline_failure"
        assert kwargs["json"]["job_id"] == "job-abc-123"
        assert kwargs["json"]["error"] == "CUDA OOM"


def test_dispatch_async_mode():
    with patch("threading.Thread") as mock_thread_cls:
        mock_thread_instance = MagicMock()
        mock_thread_cls.return_value = mock_thread_instance

        result = dispatch_security_alert({"async": True}, async_dispatch=True)

        assert result == {"status": "dispatched_async"}
        mock_thread_cls.assert_called_once()
        mock_thread_instance.start.assert_called_once()
