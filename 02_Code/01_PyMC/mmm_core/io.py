"""Common IO helpers for MMM extension workflows.

Responsibilities:
- load small JSON/YAML workflow configs;
- resolve project-relative paths;
- validate required input files;
- write lightweight manifests and run cards.

No heavy MMM math should live here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a workflow config cannot be parsed or validated."""


def project_root() -> Path:
    """Return the MMM project root."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "00_Data").is_dir() and (parent / "02_Code").is_dir():
            return parent
    raise RuntimeError(f"Could not resolve MMM project root from {current}")


def resolve_path(path: str | Path, *, base_dir: str | Path | None = None) -> Path:
    """Resolve absolute, config-relative, or project-relative paths."""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    if base_dir is not None:
        return (Path(base_dir).expanduser() / candidate).resolve()
    return (project_root() / candidate).resolve()


def ensure_dir(path: str | Path) -> Path:
    """Create a directory and return it as a Path."""
    p = Path(path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_json(path: str | Path, default: Any = None) -> Any:
    """Read JSON with UTF-8 encoding."""
    p = Path(path).expanduser()
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path: str | Path, obj: Any) -> None:
    """Write pretty JSON with UTF-8 encoding."""
    p = Path(path).expanduser()
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"", "null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        if any(ch in value for ch in [".", "e", "E"]):
            return float(value)
        return int(value)
    except ValueError:
        return value


def _looks_like_list_child(lines: list[tuple[int, str]], index: int, indent: int) -> bool:
    for next_indent, next_text in lines[index + 1:]:
        if next_indent <= indent:
            return False
        if next_text.startswith("- "):
            return True
        if next_text:
            return False
    return False


def simple_yaml_load(text: str) -> dict[str, Any]:
    """Parse the small YAML subset used by workflow templates.

    Supported syntax is intentionally narrow: nested dictionaries, scalar lists,
    comments, strings, numbers, booleans and nulls. It avoids adding PyYAML as a
    runtime dependency for these lightweight workflow configs.
    """
    raw_lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        content = raw.split(" #", 1)[0].rstrip()
        indent = len(content) - len(content.lstrip(" "))
        raw_lines.append((indent, content.strip()))

    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    for idx, (indent, text_line) in enumerate(raw_lines):
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ConfigError(f"Invalid indentation near line: {text_line}")
        parent = stack[-1][1]

        if text_line.startswith("- "):
            if not isinstance(parent, list):
                raise ConfigError(f"List item without list parent near line: {text_line}")
            parent.append(_parse_scalar(text_line[2:].strip()))
            continue

        if ":" not in text_line:
            raise ConfigError(f"Expected key/value line, got: {text_line}")
        key, value = text_line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not isinstance(parent, dict):
            raise ConfigError(f"Key/value under non-dict parent near line: {text_line}")

        if value == "":
            child: Any = [] if _looks_like_list_child(raw_lines, idx, indent) else {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(value)
    return root


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a JSON or simple YAML workflow config."""
    p = Path(path).expanduser()
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        obj = json.loads(text)
    else:
        obj = simple_yaml_load(text)
    if not isinstance(obj, dict):
        raise ConfigError(f"Config root must be a mapping: {p}")
    return obj


def not_implemented_yet(feature: str) -> None:
    """Raise a clear placeholder error while the workflow is being built."""
    raise NotImplementedError(
        f"{feature} is not implemented yet. "
        "This scaffold fixes the folder/config contract before the modeling logic is promoted from notebooks."
    )
