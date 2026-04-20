"""Reference plugin example using a virtual UR5 arm and Shadow Hand.

This file demonstrates the interfaces plugin authors usually override:
``get_joint_states``, ``set_joint_targets``, ``get_estop``, ``set_estop``,
``get_ee_pose``, ``set_ee_pose_target``, ``get_real_camera_frame``,
``get_camera_receive_fps``, ``on_mode_enter_real``, and ``on_mode_exit_real``.

The base class already handles simulation, profile metadata, joint-space API
dispatch, and websocket payload generation. This example focuses only on the
plugin-specific behavior that a real robot adapter would replace.
"""

from __future__ import annotations

import base64
from threading import Event, RLock, Thread
from typing import Any
import time
import cv2
import numpy as np
from trac_ik.trac_ik import TracIK

from app.plugins.base import RobotPlugin, register_plugin


@register_plugin(
    name="UR5 Shadow",
    description="Reference plugin showing how to implement a virtual robot adapter.",
)
class UR5ShadowPlugin(RobotPlugin):
    """Reference plugin for a UR5 arm with a Shadow Hand end effector."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize virtual hardware state and real-mode helper solvers.

        Args:
            config: Parsed plugin config with chain definitions and demo hardware options.
        """
        super().__init__(config)

        self._joint_states: dict[str, np.ndarray] = {}
        for chain in self._chains:
            chain_id = chain.id
            logical_seed = self._actual_to_logical(chain_id, self._sim_joints[chain_id])
            self._joint_states[chain_id] = np.array(logical_seed, dtype=np.float64)

        self._joint_targets: dict[str, np.ndarray] = {
            chain_id: state.copy() for chain_id, state in self._joint_states.items()
        }

        self._estop: bool = False
        real_config = config.get("real", {})
        self._virtual_robot_worker_hz = max(1.0, float(real_config.get("worker_hz", 100.0)))
        self._virtual_robot_max_speed_deg_s = max(0.0, float(real_config.get("max_joint_speed_deg_s", 60.0)))
        self._virtual_robot_lock = RLock()
        self._virtual_robot_stop = Event()
        self._virtual_robot_thread: Thread | None = None

        self._ik_solvers: dict[str, TracIK] = {
            chain.id: TracIK(
                base_link_name=chain.base_link,
                tip_link_name=chain.tip_link,
                urdf_path=self._urdf_path,
                solver_type="Distance",
            )
            for chain in self._chains
        }

        self._joint_offsets: dict[str, np.ndarray] = {
            chain.id: np.array(chain.joint_offsets_deg, dtype=np.float64) for chain in self._chains
        }

        self._sync_shared_shadow_joints(self._joint_states, None)
        self._sync_shared_shadow_joints(self._joint_targets, None)

    def _sync_shared_shadow_joints(
        self,
        states: dict[str, np.ndarray],
        source_chain_id: str | None,
    ) -> None:
        """Mirror wrist joints shared by the first finger and thumb chains."""
        ff_state = states.get("shadow_hand_ff")
        th_state = states.get("shadow_hand_th")
        if ff_state is None or th_state is None:
            return
        if source_chain_id == "shadow_hand_th":
            ff_state[:2] = th_state[:2]
            return
        th_state[:2] = ff_state[:2]

    def _reset_virtual_robot_from_sim(self) -> None:
        """Initialize virtual real-robot state from the current simulation pose."""
        with self._virtual_robot_lock:
            for chain_id in self._joint_states:
                logical_seed = self._actual_to_logical(chain_id, self._sim_joints[chain_id])
                logical_seed_arr = np.array(logical_seed, dtype=np.float64)
                self._joint_states[chain_id] = logical_seed_arr
                self._joint_targets[chain_id] = logical_seed_arr.copy()
            self._sync_shared_shadow_joints(self._joint_states, None)
            self._sync_shared_shadow_joints(self._joint_targets, None)

    def _virtual_robot_loop(self) -> None:
        """Move current joint state toward the commanded target at bounded speed."""
        period_s = 1.0 / self._virtual_robot_worker_hz
        previous_tick = time.perf_counter()
        while not self._virtual_robot_stop.wait(period_s):
            current_tick = time.perf_counter()
            delta_t = max(0.0, current_tick - previous_tick)
            previous_tick = current_tick
            if self._estop:
                continue
            max_step_deg = self._virtual_robot_max_speed_deg_s * delta_t
            with self._virtual_robot_lock:
                for chain_id, current_state in self._joint_states.items():
                    target_state = self._joint_targets[chain_id]
                    if max_step_deg <= 0.0:
                        current_state[:] = target_state
                        continue
                    delta = target_state - current_state
                    if np.max(np.abs(delta)) == 0.0:
                        continue
                    current_state[:] = current_state + delta / np.max(np.abs(delta)) * min(
                        max_step_deg, np.max(np.abs(delta))
                    )
                self._sync_shared_shadow_joints(self._joint_states, None)

    def _start_virtual_robot(self) -> None:
        """Start the virtual real-robot worker thread if it is not already running."""
        if self._virtual_robot_thread is not None and self._virtual_robot_thread.is_alive():
            return
        self._virtual_robot_stop.clear()
        self._virtual_robot_thread = Thread(
            target=self._virtual_robot_loop,
            name="ur5-shadow-virtual-real",
            daemon=True,
        )
        self._virtual_robot_thread.start()

    def _stop_virtual_robot(self) -> None:
        """Stop and join the virtual real-robot worker thread."""
        thread = self._virtual_robot_thread
        if thread is None:
            return
        self._virtual_robot_stop.set()
        thread.join(timeout=1.0)
        self._virtual_robot_thread = None

    # ── Abstract method implementations (real-robot stubs) ────────────

    def get_joint_states(self, chain_id: str) -> list[float]:
        """Read current logical joint angles from the virtual real robot.

        Args:
            chain_id: Chain identifier.

        Returns:
            list[float]: Current logical joint angles in degrees.
        """
        with self._virtual_robot_lock:
            return list(self._joint_states[chain_id])

    def set_joint_targets(self, chain_id: str, target_angles_deg: list[float]) -> None:
        """Store a logical joint target for the virtual real robot.

        Args:
            chain_id: Chain identifier.
            target_angles_deg: Target logical joint angles in degrees.
        """
        with self._virtual_robot_lock:
            self._joint_targets[chain_id] = np.array(target_angles_deg, dtype=np.float64)
            self._sync_shared_shadow_joints(self._joint_targets, chain_id)

    def get_estop(self) -> bool:
        """Read emergency-stop state from the virtual real robot.

        Returns:
            bool: True when motion is blocked.
        """
        return self._estop

    def set_estop(self, trigger: bool) -> None:
        """Trigger or release the virtual robot emergency-stop state.

        Args:
            trigger: True to trigger the stop, False to release it.
        """
        self._estop = trigger
        if not trigger:
            return
        with self._virtual_robot_lock:
            for chain_id, current_state in self._joint_states.items():
                self._joint_targets[chain_id] = current_state.copy()
            self._sync_shared_shadow_joints(self._joint_targets, None)

    # ── Real-mode cartesian control (custom IK demo) ──────────────────

    def get_ee_pose(self, chain_id: str) -> np.ndarray:
        """Get end-effector pose as 4x4 SE3 matrix in world frame.

        This example uses plugin-level TracIK FK. A hardware-backed plugin would
        typically read the pose from the robot controller instead.

        Args:
            chain_id: Chain identifier.

        Returns:
            np.ndarray: 4x4 world-frame homogeneous transform.
        """
        solver = self._ik_solvers[chain_id]
        with self._virtual_robot_lock:
            logical_state = self._joint_states[chain_id].copy()
        q_actual = np.deg2rad(logical_state + self._joint_offsets[chain_id])
        pos, rot = solver.fk(q_actual)
        se3_tip_in_base: np.ndarray = np.eye(4, dtype=np.float64)
        se3_tip_in_base[:3, :3] = rot
        se3_tip_in_base[:3, 3] = pos
        return self._se3_base_in_world[chain_id] @ se3_tip_in_base

    def set_ee_pose_target(self, chain_id: str, se3_target_in_world: np.ndarray) -> None:
        """Set end-effector target pose (4x4 SE3 in world frame).

        This example resolves the world-frame target with plugin-level TracIK IK.
        A hardware-backed plugin could forward the pose directly to its native
        cartesian command interface.

        Args:
            chain_id: Chain identifier.
            se3_target_in_world: 4x4 world-frame target pose.
        """
        solver = self._ik_solvers[chain_id]
        target_se3_in_base = self._se3_world_in_base[chain_id] @ se3_target_in_world
        target_pos = target_se3_in_base[:3, 3]
        target_rot = target_se3_in_base[:3, :3]
        with self._virtual_robot_lock:
            logical_seed = self._joint_targets[chain_id].copy()
        q_seed = np.deg2rad(logical_seed + self._joint_offsets[chain_id])
        ik_solution = solver.ik(target_pos, target_rot, q_seed)
        if ik_solution is None:
            raise ValueError(f"IK failed for {chain_id} with target pose:\n{se3_target_in_world}")
        if np.max(np.abs(np.rad2deg(ik_solution - q_seed))) > 25.0:
            raise ValueError(f"IK solution (diff: {np.rad2deg(ik_solution - q_seed).round(0)} deg) is too big (>25°)")
        solved_logical = np.rad2deg(ik_solution) - self._joint_offsets[chain_id]
        self.set_joint_targets(chain_id, list(solved_logical))

    def resolve_cartesian_joint_targets(self, chain_id: str, se3_target_in_world: np.ndarray) -> list[float] | None:
        """Expose the already-solved logical joint target for UI feedback.

        Args:
            chain_id: Chain identifier.
            se3_target_in_world: World-frame target pose already consumed by IK.

        Returns:
            list[float] | None: Logical joint angles in degrees for the current target.
        """
        with self._virtual_robot_lock:
            return list(self._joint_targets[chain_id])

    # ── Camera demo ───────────────────────────────────────────────────

    def get_real_camera_frame(self, camera_id: str) -> tuple[str, float] | None:
        """Produce a demo camera frame and timestamp for the requested camera.

        Args:
            camera_id: Camera identifier declared in config.toml.

        Returns:
            tuple[str, float] | None: Data URL and timestamp in milliseconds.
        """
        if camera_id == "dummy_camera_a":
            dummy_image = np.random.randint(0, 127, (480, 640, 3), dtype=np.uint8)
        elif camera_id == "dummy_camera_b":
            dummy_image = np.random.randint(127, 255, (640, 480, 3), dtype=np.uint8)
        _, buffer = cv2.imencode(".jpg", dummy_image)
        ts_ms = time.perf_counter_ns() / 1_000_000.0
        return f"data:image/jpeg;base64,{base64.b64encode(buffer).decode()}", ts_ms

    def get_camera_receive_fps(self, camera_id: str) -> float:
        """Report the demo receive cadence for a configured camera.

        Args:
            camera_id: Camera identifier.

        Returns:
            float: Frames per second received from the virtual hardware stream.
        """
        if camera_id == "dummy_camera_a":
            return 15.0
        if camera_id == "dummy_camera_b":
            return 30.0
        return 0.0

    def on_client_connected(self, channel: str, key: str | None = None) -> None:
        """Hook for stream-client bookkeeping.

        Args:
            channel: Logical stream type such as "camera" or "state".
            key: Optional stream key such as a camera identifier.
        """

    def on_client_disconnected(self, channel: str, key: str | None = None) -> None:
        """Hook for stream-client teardown bookkeeping.

        Args:
            channel: Logical stream type such as "camera" or "state".
            key: Optional stream key such as a camera identifier.
        """

    def on_mode_enter_real(self) -> str:
        """Start the virtual hardware worker before entering real mode.

        Returns:
            str: "ok" when the worker is ready.
        """
        self._reset_virtual_robot_from_sim()
        self._start_virtual_robot()
        return "ok"

    def on_mode_exit_real(self) -> None:
        """Stop the virtual hardware worker when leaving real mode."""
        self._stop_virtual_robot()
