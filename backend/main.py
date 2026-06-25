"""Backend application entrypoint."""

import sys
import os

# Ensure app directory is in Python path for Docker compatibility
# __file__ = /app/backend/main.py, so dirname(__file__) = /app/backend
# We need /app in the path
_backend_dir = os.path.dirname(os.path.abspath(__file__))
_app_dir = os.path.dirname(_backend_dir)
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)

from backend.api.v1.internal_transport import app

__all__ = ["app"]
