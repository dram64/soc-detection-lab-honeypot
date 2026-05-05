"""pytest configuration: ensure dashboard/ is importable; default AWS region.

Setting AWS_DEFAULT_REGION at module import time lets tests import
`functions.ingest.handler` (which constructs boto3 clients at module level)
without needing a per-test fixture. Tests that mock_aws regions still take
precedence via their own fixtures.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DASHBOARD_ROOT = Path(__file__).resolve().parents[2]
if str(DASHBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_ROOT))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
