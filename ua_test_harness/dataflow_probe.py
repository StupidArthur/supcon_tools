"""最小真实数据流探针：ua_mocker -> TPT 数据源 -> 位号 -> 实时值 -> 清理。"""
from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value