"""Runtime plugin manager with auto-discovery and hot-reload."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any

from app.core.config import read_active_plugin
from app.plugins.base import RobotPlugin
from app.plugins.loader import (
    get_plugin_config_toml_text,
    get_plugin_file_config,
    list_builtin_plugins,
    load_plugin,
    set_plugin_config_toml_text,
    set_plugin_file_config,
)


@dataclass(slots=True)
class PluginRuntimeInfo:
    """Runtime plugin metadata returned to API handlers.

    Attributes:
        name: Plugin alias.
        description: Short plugin description.
    """

    name: str
    description: str


class PluginManager:
    """Manage active plugin instance with auto-discovery.

    The manager discovers plugins via config.toml files and the
    ``@register_plugin`` decorator, selects the active
    plugin from persisted state or first discovered, and supports runtime
    hot-reload.
    """

    def __init__(self) -> None:
        """Initialize manager and load active plugin via auto-discovery."""
        self._lock = RLock()
        plugins = list_builtin_plugins()
        if not plugins:
            raise RuntimeError("no plugins discovered")

        persisted = read_active_plugin()
        plugin_names = [p.alias for p in plugins]
        if persisted and persisted in plugin_names:
            active_name = persisted
        else:
            active_name = plugin_names[0]

        self._active_name = active_name
        self._active = load_plugin(active_name)

    def get_active_plugin(self) -> RobotPlugin:
        """Return active plugin instance.

        Returns:
            RobotPlugin: Current active plugin.
        """
        with self._lock:
            return self._active

    def get_active_name(self) -> str:
        """Return active plugin alias.

        Returns:
            str: Active plugin alias.
        """
        with self._lock:
            return self._active_name

    def switch_plugin(self, plugin_name: str) -> None:
        """Switch active plugin instance.

        Args:
            plugin_name: Target plugin alias.
        """
        with self._lock:
            self._active = load_plugin(plugin_name)
            self._active_name = plugin_name

    def list_plugins(self) -> list[PluginRuntimeInfo]:
        """Return API-facing metadata for available plugins.

        Returns:
            List[PluginRuntimeInfo]: Built-in plugin metadata list.
        """
        return [PluginRuntimeInfo(name=item.alias, description=item.description) for item in list_builtin_plugins()]

    def get_plugin_config(self, plugin_name: str) -> dict[str, Any]:
        """Get plugin config snapshot from config.toml.

        Args:
            plugin_name: Plugin alias.

        Returns:
            Dict[str, Any]: Plugin config.
        """
        return get_plugin_file_config(plugin_name)

    def get_plugin_config_toml(self, plugin_name: str) -> str:
        """Get plugin config as TOML text.

        Args:
            plugin_name: Plugin alias.

        Returns:
            str: TOML-serialized config.
        """
        return get_plugin_config_toml_text(plugin_name)

    def set_plugin_config(self, plugin_name: str, config: dict[str, Any]) -> None:
        """Update plugin config and reload active plugin when needed.

        Args:
            plugin_name: Plugin alias.
            config: New plugin config.
        """
        with self._lock:
            set_plugin_file_config(plugin_name, dict(config))
            if plugin_name == self._active_name:
                self._active = load_plugin(plugin_name)

    def set_plugin_config_toml(self, plugin_name: str, raw_toml: str) -> dict[str, Any]:
        """Update plugin TOML config and reload active plugin when needed.

        Args:
            plugin_name: Plugin alias.
            raw_toml: Raw TOML text.

        Returns:
            Dict[str, Any]: Parsed config dict.
        """
        with self._lock:
            parsed = set_plugin_config_toml_text(plugin_name, raw_toml)
            if plugin_name == self._active_name:
                self._active = load_plugin(plugin_name)
            return parsed
