#!/usr/bin/env python3
"""Simple wrapper to run uvicorn with proper module discovery."""

import sys

# Add paths to enable module discovery in Docker
# /app - for "from backend..." imports
# / - for "from common..." imports
sys.path.insert(0, "/app")
sys.path.insert(0, "/")

# Now import the app object directly
from backend.main import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False
    )
