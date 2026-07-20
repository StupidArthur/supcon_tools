"""Load shared runtime_v1 / template / batch fixtures for cross-language acceptance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .workspace import fixture_root

RUNTIME_V1_DIRNAME = "runtime_v1"
REQUIRED_STATUS_FIELDS: tuple[str, ...] = (
    "instance_name",
    "mode",
    "cycle_count",
    "sim_time",
    "cycle_time",
    "safe_state",
    "consecutive_failures",
)
REQUIRED_SNAPSHOT_TOP_FIELDS: tuple[str, ...] = (
    "cycle_count",
    "sim_time",
    "source_flow",
    "valve_1",
    "tank_1",
    "tank_2",
    "pid2",
)
REQUIRED_VALVE_FIELDS: tuple[str, ...] = (
    "target_opening",
    "current_opening",
    "inlet_flow",
    "outlet_flow",
)
REQUIRED_TANK_FIELDS: tuple[str, ...] = ("level", "inlet_flow", "outlet_flow")
REQUIRED_PID_FIELDS: tuple[str, ...] = (
    "PV",
    "SV",
    "CSV",
    "MV",
    "PB",
    "TI",
    "TD",
    "KD",
    "MODE",
    "SWPN",
)


def runtime_v1_dir(verifier_root: Path) -> Path:
    return fixture_root(verifier_root) / RUNTIME_V1_DIRNAME


def load_json_fixture(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_runtime_v1_fixture(verifier_root: Path, name: str) -> Any:
    """Load a named JSON file from fixtures/runtime_v1/."""
    path = runtime_v1_dir(verifier_root) / name
    if not path.is_file():
        raise FileNotFoundError(path)
    return load_json_fixture(path)


def assert_runtime_v1_status_contract(status: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_STATUS_FIELDS if field not in status]
    if missing:
        raise AssertionError(f"status.json missing fields: {missing}")


def assert_runtime_v1_snapshot_contract(snapshot: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_SNAPSHOT_TOP_FIELDS if field not in snapshot]
    if missing:
        raise AssertionError(f"snapshot.json missing top-level fields: {missing}")
    for group, required in (
        ("valve_1", REQUIRED_VALVE_FIELDS),
        ("tank_1", REQUIRED_TANK_FIELDS),
        ("tank_2", REQUIRED_TANK_FIELDS),
        ("pid2", REQUIRED_PID_FIELDS),
    ):
        payload = snapshot[group]
        if not isinstance(payload, dict):
            raise AssertionError(f"{group} must be an object")
        absent = [field for field in required if field not in payload]
        if absent:
            raise AssertionError(f"{group} missing fields: {absent}")
