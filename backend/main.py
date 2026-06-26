"""
LUU Q-Console API — Main Entry Point

FastAPI-based logistics monitoring platform with:
- Real-time Oracle metrics
- PostgreSQL persistence
- JWT authentication
- Structured JSON logging
- Health checks
- Automation workers

Architecture:
- /api/v1/metrics   - Metrics endpoints
- /api/v1/auth      - Authentication
- /api/v1/health    - Health checks
- /api/v1/audit     - Audit logs
- /api/v1/automation - Worker automation
- /api/v1/users     - User management
"""

import sys
import os

# Ensure app directory is in Python path for Docker compatibility
_backend_dir = os.path.dirname(os.path.abspath(__file__))
_app_dir = os.path.dirname(_backend_dir)
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)

from backend.api.v1.app import app

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
