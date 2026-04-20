"""Minimal in-memory plugin example for Online Robot Controller.

This file is the smallest complete reference implementation for plugin authors.
The base class already handles simulation, so the methods implemented here are
the same real-mode hooks that a hardware-backed plugin would normally override.
"""

from __future__ import annotations

from typing import Any
import numpy as np

from app.plugins.base import RobotPlugin, register_plugin


@register_plugin(
    name="Mock",
    description="In-memory example plugin that demonstrates the minimum plugin contract.",
)
class MockPlugin(RobotPlugin):
    """In-memory plugin demonstrating the smallest useful real-mode contract."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize in-memory state for each configured chain.

        Args:
            config: Parsed plugin config with general, sim, and real sections.
        """
        super().__init__(config)
        self._real_estop = False
        self._real_joint_states: dict[str, list[float]] = {
            chain.id: [0.0] * len(chain.joints) for chain in self._chains
        }
        self._ee_targets: dict[str, np.ndarray] = {
            chain.id: self._sim_ee_target.get(chain.id, np.eye(4, dtype=np.float64)).copy() for chain in self._chains
        }

    def get_joint_states(self, chain_id: str) -> list[float]:
        """Return the last stored logical joint state for one chain.

        Args:
            chain_id: Chain identifier.

        Returns:
            list[float]: Current logical joint angles in degrees.
        """
        return list(self._real_joint_states[chain_id])

    def set_joint_targets(self, chain_id: str, target_angles_deg: list[float]) -> None:
        """Store logical joint targets in memory to demonstrate command flow.

        Args:
            chain_id: Chain identifier.
            target_angles_deg: Target joint angles in degrees.
        """
        self._real_joint_states[chain_id] = list(target_angles_deg)

    def get_estop(self) -> bool:
        """Return the stored emergency-stop state.

        Returns:
            bool: True when the in-memory e-stop is active.
        """
        return self._real_estop

    def set_estop(self, trigger: bool) -> None:
        """Update the stored emergency-stop state.

        Args:
            trigger: True to trigger the e-stop, False to release it.
        """
        self._real_estop = trigger

    def get_ee_pose(self, chain_id: str) -> np.ndarray:
        """Return the last stored world-frame end-effector pose for one chain.

        Args:
            chain_id: Chain identifier.

        Returns:
            np.ndarray: 4x4 world-frame homogeneous transform.
        """
        return self._ee_targets.get(chain_id, np.eye(4, dtype=np.float64)).copy()

    def set_ee_pose_target(self, chain_id: str, se3_target_in_world: np.ndarray) -> None:
        """Store a requested world-frame end-effector target for one chain.

        Args:
            chain_id: Chain identifier.
            se3_target_in_world: 4x4 world-frame target pose.
        """
        self._ee_targets[chain_id] = np.array(se3_target_in_world, dtype=np.float64, copy=True)
