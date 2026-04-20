"""Runtime configuration utilities for the Online Robot Controller backend."""

from __future__ import annotations

from pathlib import Path
import tomllib
import tomli_w


_ACTIVE_PLUGIN_PATH = Path(__file__).resolve().parents[2] / ".active_plugin"


def read_toml_file(path: Path) -> dict[str, object]:
    """Read TOML file into a dict.

    Args:
        path: TOML file path.

    Returns:
        Parsed TOML dict. Returns empty dict for missing files.
    """
    if not path.exists():
        return {}
    with path.open("rb") as fp:
        parsed = tomllib.load(fp)
    return parsed if isinstance(parsed, dict) else {}


def write_toml_file(path: Path, payload: dict[str, object]) -> None:
    """Write dict payload into TOML file.

    Args:
        path: Target TOML file path.
        payload: TOML-compatible payload.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fp:
        tomli_w.dump(payload, fp)


def parse_toml_text(raw_text: str) -> dict[str, object]:
    """Parse TOML text payload.

    Args:
        raw_text: Raw TOML text.

    Returns:
        Parsed TOML dict.
    """
    parsed = tomllib.loads(raw_text)
    return parsed if isinstance(parsed, dict) else {}


def dump_toml_text(payload: dict[str, object]) -> str:
    """Serialize TOML dict to text.

    Args:
        payload: TOML-compatible payload.

    Returns:
        Serialized TOML string.
    """
    return tomli_w.dumps(payload)


def read_active_plugin() -> str | None:
    """Read persisted active plugin name.

    Returns:
        Optional[str]: Plugin name, or None if not persisted.
    """
    if not _ACTIVE_PLUGIN_PATH.exists():
        return None
    text = _ACTIVE_PLUGIN_PATH.read_text(encoding="utf-8").strip()
    return text if text else None


def persist_active_plugin(plugin_name: str) -> None:
    """Persist active plugin name to disk.

    Args:
        plugin_name: Selected plugin alias.
    """
    _ACTIVE_PLUGIN_PATH.write_text(plugin_name.strip(), encoding="utf-8")
