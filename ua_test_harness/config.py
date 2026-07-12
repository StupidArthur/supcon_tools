"""config.py:RunConfig 加载与模型。

Go 侧 automation.Service 每次启动任务生成 run-config.json,
Python runner 读取后驱动执行(plan.md 5.2)。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SubjectConfig:
    base_url: str = ""
    tenant_id: str = ""
    username: str = ""
    password: str = ""
    token: str = ""


@dataclass
class Mock