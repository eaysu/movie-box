"""Netlify Function entry point — wraps the FastAPI app with Mangum.

Netlify Functions run on AWS Lambda. Mangum translates Lambda events
into ASGI requests that FastAPI can handle.

All /api/* requests are routed here via netlify.toml redirects.
"""

import os
import sys

# Make `app` importable from the project root.
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

# Ensure DATA_DIR resolves correctly inside the Lambda environment.
os.environ.setdefault("DATA_DIR", os.path.join(_root, "data"))

from mangum import Mangum  # noqa: E402
from app.main import app  # noqa: E402

handler = Mangum(app, lifespan="off")
