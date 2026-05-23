"""
OpenClaw health cache shim for source-based local runs.

The Docker image copies data-service/src/services/health_cache.py into this
path during build. This shim keeps Mac mini/native source runs on the same
implementation without duplicating the service code.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_SERVICE_SRC = _PROJECT_ROOT / "data-service" / "src"
if _DATA_SERVICE_SRC.exists():
    sys.path.insert(0, str(_DATA_SERVICE_SRC))

from services.health_cache import HealthCache  # noqa: E402,F401
