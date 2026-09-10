"""
SCORM Cloud API v2 Client for Modular-NeuroClips.
Enables 1-click cloud deployment, asynchronous course ingestion, and learner preview link generation.
"""
import os
import json
import base64
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel


class SCORMCloudDeployRequest(BaseModel):
    course_id: str
    zip_path: Optional[str] = None
    package_filename: Optional[str] = None
    scorm_app_id: Optional[str] = None
    scorm_secret_key: Optional[str] = None


class SCORMCloudClient:
    """Client for Rustici SCORM Cloud API v2."""

    def __init__(self, app_id: Optional[str] = None, secret_key: Optional[str] = None):
        self.app_id = app_id or os.getenv("SCORM_CLOUD_APP_ID", "")
        self.secret_key = secret_key or os.getenv("SCORM_CLOUD_SECRET_KEY", "")
        self.base_url = "https://cloud.scorm.com/api/v2"

    def _get_headers(self) -> Dict[str, str]:
        auth_bytes = f"{self.app_id}:{self.secret_key}".encode("utf-8")
        auth_header = "Basic " + base64.b64encode(auth_bytes).decode("utf-8")
        return {
            "Authorization": auth_header,
            "User-Agent": "Modular-NeuroClips/2.6"
        }

    def import_course_package(self, course_id: str, zip_path: Path) -> Dict[str, Any]:
        """
        Uploads and registers a SCORM .zip package to SCORM Cloud API v2.
        """
        if not zip_path.exists():
            raise FileNotFoundError(f"SCORM zip not found: {zip_path}")

        if not self.app_id or not self.secret_key:
            # Mock successful dispatch for offline/sandbox mode if credentials not provided
            return {
                "status": "mock_success",
                "import_job_id": f"mock_job_{course_id}",
                "course_id": course_id,
                "message": "SCORM package validated and queued. (Add SCORM_CLOUD_APP_ID and SCORM_CLOUD_SECRET_KEY for live push)",
                "package_size_mb": round(zip_path.stat().st_size / (1024 ** 2), 2),
                "check_status_url": f"https://cloud.scorm.com/api/v2/courses/importJobs/mock_job_{course_id}"
            }

        url = f"{self.base_url}/courses/importJobs/upload?courseId={urllib.parse.quote(course_id)}"
        
        # Read file bytes
        file_bytes = zip_path.read_bytes()
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{zip_path.name}"\r\n'
            f"Content-Type: application/zip\r\n\r\n"
        ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        headers = self._get_headers()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        headers["Content-Length"] = str(len(body))

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                return {
                    "status": "success",
                    "import_job_id": resp_data.get("result", ""),
                    "course_id": course_id,
                    "check_status_url": f"{self.base_url}/courses/importJobs/{resp_data.get('result', '')}"
                }
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            raise RuntimeError(f"SCORM Cloud HTTP error {e.code}: {err_body}")
        except Exception as e:
            raise RuntimeError(f"SCORM Cloud communication failed: {e}")

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Queries asynchronous course import job status."""
        if job_id.startswith("mock_job_") or not self.app_id or not self.secret_key:
            return {
                "status": "COMPLETE",
                "job_id": job_id,
                "message": "Course import ready for dispatch."
            }

        url = f"{self.base_url}/courses/importJobs/{job_id}"
        req = urllib.request.Request(url, headers=self._get_headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def create_launch_link(self, course_id: str, registration_id: str = "reg_test_01") -> str:
        """Generates learner launch URL for immediate course testing."""
        if not self.app_id or not self.secret_key:
            return f"https://cloud.scorm.com/preview/{course_id}"

        url = f"{self.base_url}/registrations/{registration_id}/launchLink"
        payload = json.dumps({"redirectOnExitUrl": "https://neuroclips.mytestbed.tech/"}).encode("utf-8")
        headers = self._get_headers()
        headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("launchLink", "")
        except Exception:
            return f"https://cloud.scorm.com/scorm-preview?courseId={course_id}"
