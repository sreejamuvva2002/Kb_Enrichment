from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
METADATA_DIR = DATA_DIR / "metadata"
OUTPUT_DIR = REPO_ROOT / "outputs"
CHECKPOINT_DIR = REPO_ROOT / "checkpoints"


def iso_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


__all__ = [
    "CHECKPOINT_DIR",
    "CONFIG_DIR",
    "DATA_DIR",
    "METADATA_DIR",
    "OUTPUT_DIR",
    "PACKAGE_ROOT",
    "RAW_DATA_DIR",
    "REPO_ROOT",
    "iso_now",
    "load_yaml",
]
