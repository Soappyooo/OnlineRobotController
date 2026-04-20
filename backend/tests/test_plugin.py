"""Plugin discovery and contract tests."""

import numpy as np
import pytest

from app.plugins.loader import list_builtin_plugins, load_plugin
from app.plugins.mock.plugin import MockPlugin
from app.plugins.ur5_shadow.plugin import UR5ShadowPlugin


def test_builtin_plugin_aliases() -> None:
    """Built-in plugin discovery should only expose public example plugins."""
    aliases = {item.alias for item in list_builtin_plugins()}
    assert aliases == {"mock", "ur5_shadow"}


def test_loader_resolves_mock_alias() -> None:
    """Loader should resolve the mock example plugin."""
    plugin = load_plugin("mock")
    assert isinstance(plugin, MockPlugin)


def test_loader_resolves_ur5_shadow_alias() -> None:
    """Loader should resolve the UR5 Shadow example plugin."""
    plugin = load_plugin("ur5_shadow")
    assert isinstance(plugin, UR5ShadowPlugin)


def test_loader_rejects_removed_qmlinker_alias() -> None:
    """Removed private plugins should no longer be loadable by alias."""
    with pytest.raises(ValueError, match="unknown plugin"):
        load_plugin("wuji_qmlinker")


def test_mock_plugin_real_mode_contract_round_trip() -> None:
    """Mock plugin should expose observable state for each required real-mode hook."""
    plugin = load_plugin("mock")

    assert plugin.switch_mode("real") == "ok"

    joint_target = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    plugin.set_joint_targets("arm_a", joint_target)
    assert plugin.get_joint_states("arm_a") == joint_target

    ee_target = np.eye(4, dtype=np.float64)
    ee_target[0, 3] = 0.02
    plugin.set_ee_pose_target("arm_a", ee_target)
    np.testing.assert_allclose(plugin.get_ee_pose("arm_a"), ee_target)

    plugin.set_estop(True)
    assert plugin.get_estop() is True
