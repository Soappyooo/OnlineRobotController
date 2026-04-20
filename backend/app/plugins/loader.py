"""Plugin loader for Online Robot Controller.

Discovery scans plugin directories for ``config.toml`` files.  Each directory
that contains one is assumed to house a plugin module at
``app.plugins.<dir_name>.plugin``.  Importing the module triggers the
``@register_plugin`` decorator which registers the plugin class.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import dump_toml_text, parse_toml_text, read_toml_file, write_toml_file
from app.plugins.base import RobotPlugin, get_plugin_registration


@dataclass(slots=True, frozen=True)
class PluginDescriptor:
    """Static metadata for one available plugin.

    Attributes:
        alias: Directory name used as the API-facing plugin identifier.
        name: Human-readable display name from ``@register_plugin``.
        description: Short description from ``@register_plugin``.
        plugin_cls: Plugin class reference.
        plugin_dir: Absolute path to plugin directory.
    """

    alias: str
    name: str
    description: str
    plugin_cls: type[RobotPlugin]
    plugin_dir: Path


def _plugins_root() -> Path:
    """Return the root directory containing all plugin packages."""
    return Path(__file__).resolve().parent


def _discover_plugin_registry() -> dict[str, PluginDescriptor]:
    """Scan plugin directories for config.toml and import plugin modules.

    Importing each ``app.plugins.<dir>.plugin`` module triggers the
    ``@register_plugin`` class decorator, which populates the global
    plugin registry.  We then look up each registered class and build a
    descriptor keyed by directory name (alias).

    Returns:
        Dict[str, PluginDescriptor]: Registry keyed by alias (directory name).
    """
    registry: dict[str, PluginDescriptor] = {}
    for child in _plugins_root().iterdir():
        if not child.is_dir():
            continue
        config_toml = child / "config.toml"
        if not config_toml.exists():
            continue
        module_path = f"app.plugins.{child.name}.plugin"
        try:
            mod = importlib.import_module(module_path)
        except Exception:
            continue
        # Find the registered RobotPlugin subclass in the imported module
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name, None)
            if isinstance(attr, type) and issubclass(attr, RobotPlugin) and attr is not RobotPlugin:
                registration = get_plugin_registration(attr)
                if registration is None:
                    continue
                display_name, description = registration
                registry[child.name] = PluginDescriptor(
                    alias=child.name,
                    name=display_name,
                    description=description,
                    plugin_cls=attr,
                    plugin_dir=child,
                )
                break
    return registry


def _plugin_descriptor(plugin_name: str) -> PluginDescriptor:
    """Look up a plugin descriptor by alias.

    Args:
        plugin_name: Plugin alias (directory name).

    Returns:
        PluginDescriptor: Plugin metadata.

    Raises:
        ValueError: When plugin is not found.
    """
    descriptor = _discover_plugin_registry().get(plugin_name)
    if descriptor is None:
        raise ValueError(f"unknown plugin: {plugin_name}")
    return descriptor


def list_builtin_plugins() -> list[PluginDescriptor]:
    """List known plugins discovered from plugin directories.

    Returns:
        List[PluginDescriptor]: All discovered plugin descriptors.
    """
    return list(_discover_plugin_registry().values())


def _config_toml_path(descriptor: PluginDescriptor) -> Path:
    """Return config.toml path for a plugin.

    Args:
        descriptor: Plugin descriptor.

    Returns:
        Path: Absolute path to config.toml.
    """
    return descriptor.plugin_dir / "config.toml"


def get_plugin_file_config(plugin_name: str) -> dict[str, Any]:
    """Read full config from plugin's config.toml.

    Args:
        plugin_name: Plugin alias.

    Returns:
        Dict[str, Any]: Parsed config.toml contents.
    """
    descriptor = _plugin_descriptor(plugin_name)
    config_path = _config_toml_path(descriptor)
    return dict(read_toml_file(config_path))


def set_plugin_file_config(plugin_name: str, config: dict[str, Any]) -> None:
    """Write config to plugin's config.toml.

    Args:
        plugin_name: Plugin alias.
        config: Config dict to persist.
    """
    descriptor = _plugin_descriptor(plugin_name)
    config_path = _config_toml_path(descriptor)
    write_toml_file(config_path, dict(config))


def get_plugin_config_toml_text(plugin_name: str) -> str:
    """Return plugin config as raw TOML text from the config file.

    Args:
        plugin_name: Plugin alias.

    Returns:
        str: Raw TOML file contents.
    """
    descriptor = _plugin_descriptor(plugin_name)
    config_path = _config_toml_path(descriptor)
    if not config_path.exists():
        return ""
    return config_path.read_text(encoding="utf-8")


def set_plugin_config_toml_text(plugin_name: str, raw_toml: str) -> dict[str, Any]:
    """Validate TOML text and persist it verbatim to the plugin config file.

    The raw text is written as-is to preserve formatting, comments, and any
    extra keys not used by the current code.

    Args:
        plugin_name: Plugin alias.
        raw_toml: Raw TOML text.

    Returns:
        Dict[str, Any]: Parsed config dict.
    """
    parsed = parse_toml_text(raw_toml)
    if not isinstance(parsed, dict):
        raise ValueError("TOML config must be an object")
    descriptor = _plugin_descriptor(plugin_name)
    config_path = _config_toml_path(descriptor)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(raw_toml, encoding="utf-8")
    return dict(parsed)


def load_plugin(plugin_name: str) -> RobotPlugin:
    """Load and instantiate a plugin by alias.

    The plugin class is instantiated with the full config.toml contents.

    Args:
        plugin_name: Plugin alias.

    Returns:
        RobotPlugin: Initialized plugin instance.
    """
    descriptor = _plugin_descriptor(plugin_name)
    config = get_plugin_file_config(plugin_name)
    plugin = descriptor.plugin_cls(config=config)
    if not isinstance(plugin, RobotPlugin):
        raise ValueError("plugin class must produce a RobotPlugin instance")
    return plugin
