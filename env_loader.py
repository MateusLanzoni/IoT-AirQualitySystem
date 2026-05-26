from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def parse_env_file(path: str | os.PathLike[str] = ".env") -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}

    parsed: dict[str, str] = {}

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            parsed[key] = value
    return parsed


def load_env_file(path: str | os.PathLike[str] = ".env", overwrite: bool = False) -> None:
    for key, value in parse_env_file(path).items():
        if overwrite or key not in os.environ:
            os.environ[key] = value


def write_env_file(path: str | os.PathLike[str], values: dict[str, str]) -> None:
    env_path = Path(path)
    existing_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    updated_lines: list[str] = []
    seen_keys: set[str] = set()

    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            updated_lines.append(raw_line)
            continue

        key, _ = raw_line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key in values:
            updated_lines.append(f"{normalized_key}={values[normalized_key]}")
            seen_keys.add(normalized_key)
        else:
            updated_lines.append(raw_line)

    for key, value in values.items():
        if key not in seen_keys:
            updated_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def expand_env_values(data: Any) -> Any:
    if isinstance(data, dict):
        return {key: expand_env_values(value) for key, value in data.items()}
    if isinstance(data, list):
        return [expand_env_values(item) for item in data]
    if isinstance(data, str):
        return os.path.expandvars(data)
    return data