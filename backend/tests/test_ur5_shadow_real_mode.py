"""Real-mode behavior tests for the UR5 Shadow demo plugin."""

from __future__ import annotations

import time

import numpy as np

from app.plugins.loader import get_plugin_file_config
from app.plugins.ur5_shadow.plugin import UR5ShadowPlugin


def _make_plugin() -> UR5ShadowPlugin:
    """Create a UR5 Shadow plugin instance for tests."""
    config = get_plugin_file_config("ur5_shadow")
    return UR5ShadowPlugin(config=config)


def test_virtual_real_robot_thread_lifecycle() -> None:
    """Real mode should start and stop the virtual hardware thread."""
    plugin = _make_plugin()
    try:
        assert plugin.switch_mode("real") == "ok"
        assert plugin._virtual_robot_thread is not None
        assert plugin._virtual_robot_thread.is_alive()

        assert plugin.switch_mode("simulation") == "ok"
        assert plugin._virtual_robot_thread is None
    finally:
        plugin.on_mode_exit_real()


def test_virtual_real_robot_joint_motion_is_rate_limited() -> None:
    """Joint commands in real mode should move toward the target over time."""
    plugin = _make_plugin()
    target = [24.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    try:
        assert plugin.switch_mode("real") == "ok"
        assert plugin.move_joint("ur5", target) == "ok"

        early_state = plugin.get_joint_states("ur5")
        assert early_state[0] < target[0]

        time.sleep(0.12)
        mid_state = plugin.get_joint_states("ur5")
        assert 0.0 < mid_state[0] < target[0]

        time.sleep(0.75)
        final_state = plugin.get_joint_states("ur5")
        assert final_state[0] == np.float64(final_state[0])
        assert np.isclose(final_state[0], target[0], atol=1.5)
    finally:
        plugin.on_mode_exit_real()


def test_real_absolute_ee_target_updates_virtual_joint_targets() -> None:
    """Absolute EE target commands should move the virtual robot gradually."""
    plugin = _make_plugin()
    try:
        assert plugin.switch_mode("real") == "ok"
        initial_pose = plugin.get_ee_pose("ur5")
        target_pose = initial_pose.copy()
        target_pose[0, 3] += 0.01

        assert plugin.set_ee_target_from_mat("ur5", target_pose.tolist()) == "ok"

        immediate_state = plugin.get_joint_states("ur5")
        time.sleep(0.15)
        moved_state = plugin.get_joint_states("ur5")

        assert moved_state != immediate_state
        assert np.allclose(plugin._real_ee_target["ur5"], target_pose)
    finally:
        plugin.on_mode_exit_real()
