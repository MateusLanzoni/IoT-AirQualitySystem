from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def load_env_file(path: str | os.PathLike[str] = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def expand_env_values(data: Any) -> Any:
    if isinstance(data, dict):
        return {key: expand_env_values(value) for key, value in data.items()}
    if isinstance(data, list):
        return [expand_env_values(item) for item in data]
    if isinstance(data, str):
        return os.path.expandvars(data)
    return data