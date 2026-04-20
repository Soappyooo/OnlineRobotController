"""Core plugin abstractions with built-in URDF simulation.

RobotPlugin owns the simulation engine, profile metadata, and API-facing
command dispatch. Plugin authors typically only override the real-mode hooks
documented near the end of this file.
"""

from __future__ import annotations

import base64
import math
import time
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from trac_ik.trac_ik import TracIK
import numpy as np
from typing import Literal


# ── Math utilities ────────────────────────────────────────────────────────


def _rpy_to_matrix(rpy: list[float]) -> np.ndarray:
    """Convert xyz-euler angles (radians) to 3x3 rotation matrix."""
    roll, pitch, yaw = rpy
    cx, sx = math.cos(roll), math.sin(roll)
    cy, sy = math.cos(pitch), math.sin(pitch)
    cz, sz = math.cos(yaw), math.sin(yaw)
    return np.array(
        [
            [cy * cz, -cy * sz, sy],
            [sx * sy * cz + cx * sz, -sx * sy * sz + cx * cz, -sx * cy],
            [-cx * sy * cz + sx * sz, cx * sy * sz + sx * cz, cx * cy],
        ],
        dtype=np.float64,
    )


def _matrix_to_rpy(matrix: np.ndarray) -> list[float]:
    """Convert 3x3 rotation matrix to xyz-euler angles (radians)."""
    sy = float(matrix[0, 2])
    pitch = math.asin(max(-1.0, min(1.0, sy)))
    cy = math.cos(pitch)
    if abs(cy) < 1e-8:
        roll = 0.0
        yaw = math.atan2(float(-matrix[1, 0]), float(matrix[1, 1]))
    else:
        roll = math.atan2(float(-matrix[1, 2]), float(matrix[2, 2]))
        yaw = math.atan2(float(-matrix[0, 1]), float(matrix[0, 0]))
    return [roll, pitch, yaw]


def _pose_to_transform(xyzrpy: list[float]) -> np.ndarray:
    """Convert [x, y, z, roll, pitch, yaw] to 4x4 homogeneous transform."""
    t = np.eye(4, dtype=np.float64)
    t[:3, :3] = _rpy_to_matrix(xyzrpy[3:6])
    t[:3, 3] = np.array(xyzrpy[:3], dtype=np.float64)
    return t


def _transform_to_pose(transform: np.ndarray) -> list[float]:
    """Convert 4x4 homogeneous transform to [x, y, z, roll, pitch, yaw]."""
    rpy = _matrix_to_rpy(transform[:3, :3])
    p = transform[:3, 3]
    return [float(p[0]), float(p[1]), float(p[2]), rpy[0], rpy[1], rpy[2]]


def _inverse_transform(transform: np.ndarray) -> np.ndarray:
    """Compute inverse of a rigid-body homogeneous transform."""
    r = transform[:3, :3]
    t = transform[:3, 3]
    inv = np.eye(4, dtype=np.float64)
    inv[:3, :3] = r.T
    inv[:3, 3] = -r.T @ t
    return inv


# ── Chain configuration ───────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class ChainConfig:
    """Parsed chain configuration for one kinematic chain."""

    id: str
    name: str
    world_link: str
    base_link: str
    tip_link: str
    joints: list[str]
    joint_offsets_deg: list[float]
    initial_joints_deg: list[float]


# ── Base plugin class ─────────────────────────────────────────────────────


class RobotPlugin(ABC):
    """Base class providing URDF simulation and real-robot dispatch.

    Subclasses override the real-mode contract methods, while this class keeps
    simulation, profile metadata, camera placeholders, and shared API behavior
    consistent across plugins.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize plugin with parsed config.toml contents.

        Args:
            config: Full plugin config dict with 'general', 'sim', 'real' sections.
        """
        self._config = config
        general = config.get("general", {})
        sim = config.get("sim", {})

        # General rates
        self._command_hz: float = float(general.get("command_hz", 60))
        self._state_hz: float = float(general.get("state_hz", 60))
        self._camera_hz: float = float(general.get("camera_hz", 15))

        # Parse chains
        self._chains: list[ChainConfig] = self._parse_chains(sim)
        self._chain_map: dict[str, ChainConfig] = {c.id: c for c in self._chains}

        # Resolve URDF path
        self._urdf_path: str = self._resolve_urdf_path(str(sim.get("urdf_path", "")))

        # Mode and safety
        self._mode: str = "simulation"
        self._estop_state: bool = False
        self._init_error: str | None = None

        # Simulation state
        self._sim_joints: dict[str, list[float]] = {}
        self._sim_ik: dict[str, Any] = {}
        self._sim_world_ik: dict[str, Any] = {}
        self._se3_base_in_world: dict[str, np.ndarray] = {}
        self._se3_world_in_base: dict[str, np.ndarray] = {}
        self._joint_limits_by_name: dict[str, tuple[float, float]] = {}
        self._sim_joint_limits: dict[str, list[tuple[float, float] | None]] = {}
        # Maintained world-frame EE target for each chain.
        # Updated by joint commands (via FK) and by cartesian jog (via delta).
        # Decoupled from current joint state so that IK errors do not accumulate.
        self._sim_ee_target: dict[str, np.ndarray] = {}
        # Real-mode maintained EE target, analogous to _sim_ee_target.
        # Prevents drift from real robot motion delays during cartesian jog.
        self._real_ee_target: dict[str, np.ndarray] = {}
        # Last commanded joint-level logical targets in real mode.
        # Reported in the state payload so the frontend can display the
        # target vs. current difference during cartesian jog.
        self._real_joint_targets: dict[str, list[float]] = {}
        self._real_joint_currents: dict[str, list[float]] = {}

        self._init_simulation()
        for chain in self._chains:
            self._get_ik_solver(chain.id)
            self._get_world_ik_solver(chain.id)
            self._get_world_to_base_transform(chain.id)
        # Eagerly initialize EE targets from FK so that the first cartesian
        # jog command has a correct starting pose.  This runs after solvers
        # are created above to ensure FK is available.
        for chain in self._chains:
            self._refresh_ee_target_from_fk(chain.id)

    @property
    def mode(self) -> Literal["simulation", "real"]:
        """Current mode of the plugin, either 'simulation' or 'real'."""
        return self._mode

    # ── Chain parsing ─────────────────────────────────────────────────

    @staticmethod
    def _parse_float_list(raw: Any, size: int) -> list[float]:
        """Convert a raw list to ``size`` floats, padding with zeros."""
        items = raw if isinstance(raw, list) else []
        result: list[float] = []
        for v in items:
            try:
                result.append(float(v))
            except (TypeError, ValueError):
                result.append(0.0)
        while len(result) < size:
            result.append(0.0)
        return result[:size]

    @staticmethod
    def _parse_chains(sim_config: dict[str, Any]) -> list[ChainConfig]:
        """Parse chain configurations from sim config section.

        Args:
            sim_config: The [sim] section of config.toml.

        Returns:
            List[ChainConfig]: Parsed chain configurations.
        """
        raw = sim_config.get("chains", [])
        if not isinstance(raw, list):
            return []
        chains: list[ChainConfig] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            chain_id = str(item["id"]).strip()
            joints = [str(j).strip() for j in item.get("joints", []) if str(j).strip()]
            n = len(joints)
            chains.append(
                ChainConfig(
                    id=chain_id,
                    name=str(item.get("name", chain_id)),
                    world_link=str(item.get("world_link", "")).strip(),
                    base_link=str(item.get("base_link", "")).strip(),
                    tip_link=str(item.get("tip_link", "")).strip(),
                    joints=joints,
                    joint_offsets_deg=RobotPlugin._parse_float_list(item.get("joint_offsets_deg"), n),
                    initial_joints_deg=RobotPlugin._parse_float_list(item.get("initial_joints_deg"), n),
                )
            )
        return chains

    # ── URDF path resolution ──────────────────────────────────────────

    @staticmethod
    def _resolve_urdf_path(configured: str) -> str:
        """Resolve URDF path to absolute path.

        Args:
            configured: Raw URDF path string from config.

        Returns:
            str: Resolved absolute path, or empty string if not configured.
        """
        if not configured.strip():
            return ""
        p = Path(configured).expanduser()
        if p.is_absolute():
            return str(p.resolve())
        backend_dir = Path(__file__).resolve().parents[2]
        project_dir = backend_dir.parent
        for root in (Path.cwd(), project_dir, backend_dir):
            candidate = (root / configured).resolve()
            if candidate.exists():
                return str(candidate)
        return str((project_dir / configured).resolve())

    # ── Simulation initialization ─────────────────────────────────────

    def _init_simulation(self) -> None:
        """Initialize simulation state from URDF and chain configs."""
        if self._urdf_path:
            self._joint_limits_by_name = self._load_urdf_joint_limits()
        for chain in self._chains:
            n = len(chain.joints)
            initial_actual = [chain.initial_joints_deg[i] + chain.joint_offsets_deg[i] for i in range(n)]
            self._sim_joints[chain.id] = initial_actual
            self._sim_joint_limits[chain.id] = self._resolve_chain_limits(chain)

    # ── Joint limit handling ──────────────────────────────────────────

    def _load_urdf_joint_limits(self) -> dict[str, tuple[float, float]]:
        """Parse URDF for revolute/prismatic joint limits in degrees.

        Returns:
            Dict[str, Tuple[float, float]]: Joint name to (min_deg, max_deg).
        """
        limits: dict[str, tuple[float, float]] = {}
        try:
            root = ET.parse(self._urdf_path).getroot()
            for joint in root.findall("joint"):
                name = str(joint.attrib.get("name", "")).strip()
                jtype = str(joint.attrib.get("type", "")).strip().lower()
                if not name or jtype in {"continuous", "fixed", "floating", "planar"}:
                    continue
                limit_node = joint.find("limit")
                if limit_node is None:
                    continue
                lower_t = limit_node.attrib.get("lower")
                upper_t = limit_node.attrib.get("upper")
                if lower_t is None or upper_t is None:
                    continue
                lo = math.degrees(float(lower_t))
                hi = math.degrees(float(upper_t))
                if lo > hi:
                    lo, hi = hi, lo
                limits[name] = (lo, hi)
        except Exception:
            return {}
        return limits

    def _resolve_chain_limits(self, chain: ChainConfig) -> list[tuple[float, float] | None]:
        """Build per-joint limit list for one chain.

        Args:
            chain: Chain configuration.

        Returns:
            List[Tuple[float, float] | None]: Per-joint limit entries.
        """
        return [self._joint_limits_by_name.get(name) for name in chain.joints]

    def _clamp_joints(self, chain_id: str, actual_angles: list[float]) -> list[float]:
        """Clamp actual joint angles to URDF limits.

        Args:
            chain_id: Chain identifier.
            actual_angles: Joint angles in URDF frame.

        Returns:
            List[float]: Clamped angles.
        """
        limits = self._sim_joint_limits.get(chain_id, [])
        result: list[float] = []
        for i, val in enumerate(actual_angles):
            bound = limits[i] if i < len(limits) else None
            if bound is None:
                result.append(float(val))
            else:
                result.append(float(max(bound[0], min(bound[1], val))))
        return result

    # ── Angle conversion ──────────────────────────────────────────────

    def _logical_to_actual(self, chain_id: str, logical: list[float]) -> list[float]:
        """Convert logical (user-facing) angles to actual (URDF) angles.

        Args:
            chain_id: Chain identifier.
            logical: Logical joint angles in degrees.

        Returns:
            List[float]: Actual URDF joint angles.
        """
        chain = self._chain_map[chain_id]
        n = len(chain.joints)
        return [logical[i] + chain.joint_offsets_deg[i] for i in range(min(len(logical), n))]

    def _actual_to_logical(self, chain_id: str, actual: list[float]) -> list[float]:
        """Convert actual (URDF) angles to logical (user-facing) angles.

        Args:
            chain_id: Chain identifier.
            actual: Actual URDF joint angles in degrees.

        Returns:
            List[float]: Logical joint angles.
        """
        chain = self._chain_map[chain_id]
        n = len(chain.joints)
        return [actual[i] - chain.joint_offsets_deg[i] for i in range(min(len(actual), n))]

    # ── IK/FK solver management ───────────────────────────────────────

    def _get_world_to_base_transform(self, chain_id: str) -> np.ndarray:
        """Compute or retrieve the static world->base transform for a chain.

        Args:
            chain_id: Chain identifier.

        Returns:
            np.ndarray: 4x4 homogeneous transform from world to chain base.
        """
        if chain_id in self._se3_base_in_world:
            return self._se3_base_in_world[chain_id]

        chain = self._chain_map[chain_id]
        if chain.world_link == chain.base_link or not chain.world_link:
            identity = np.eye(4, dtype=np.float64)
            self._se3_base_in_world[chain_id] = identity
            self._se3_world_in_base[chain_id] = identity.copy()
            return identity

        seed_deg = list(self._sim_joints[chain_id])
        t_world_tip = self._fk_se3(chain_id, seed_deg, in_world=True)
        t_arm_tip = self._fk_se3(chain_id, seed_deg, in_world=False)

        if t_world_tip is None or t_arm_tip is None:
            identity = np.eye(4, dtype=np.float64)
            self._se3_base_in_world[chain_id] = identity
            self._se3_world_in_base[chain_id] = identity.copy()
            return identity

        t_world_base = t_world_tip @ _inverse_transform(t_arm_tip)

        self._se3_base_in_world[chain_id] = t_world_base
        self._se3_world_in_base[chain_id] = _inverse_transform(t_world_base)
        return t_world_base

    def _get_ik_solver(self, chain_id: str) -> TracIK | None:
        """Get or lazily initialize arm-frame IK solver (base_link -> tip_link).

        Args:
            chain_id: Chain identifier.

        Returns:
            TracIK solver or None if not available.
        """
        if chain_id in self._sim_ik:
            return self._sim_ik[chain_id]
        chain = self._chain_map.get(chain_id)
        if chain is None or not chain.base_link or not chain.tip_link or not self._urdf_path:
            return None

        solver = TracIK(
            base_link_name=chain.base_link,
            tip_link_name=chain.tip_link,
            urdf_path=self._urdf_path,
            solver_type="Distance",
        )
        self._sim_ik[chain_id] = solver
        return solver

    def _get_world_ik_solver(self, chain_id: str) -> TracIK | None:
        """Get or lazily initialize world-frame solver (world_link -> tip_link).

        Args:
            chain_id: Chain identifier.

        Returns:
            TracIK solver or None if not available.
        """
        if chain_id in self._sim_world_ik:
            return self._sim_world_ik[chain_id]
        chain = self._chain_map.get(chain_id)
        if chain is None or not chain.world_link or not chain.tip_link or not self._urdf_path:
            return None

        solver = TracIK(
            base_link_name=chain.world_link,
            tip_link_name=chain.tip_link,
            urdf_path=self._urdf_path,
            solver_type="Distance",
        )
        self._sim_world_ik[chain_id] = solver
        return solver

    def _fit_seed(self, seed_deg: list[float], solver: TracIK, prepend: bool) -> np.ndarray:
        """Resize seed vector to match solver DoF and convert to radians.

        Args:
            seed_deg: Joint seed values in degrees.
            solver: TracIK solver instance.
            prepend: Place extra placeholder joints before known joints.

        Returns:
            np.ndarray: Seed array in radians matching solver DoF.
        """
        seed = np.array(seed_deg, dtype=np.float64)
        target_dof = int(solver.dof)
        n = int(seed.shape[0])
        if n < target_dof:
            pad = np.zeros(target_dof - n, dtype=np.float64)
            seed = np.concatenate([pad, seed]) if prepend else np.concatenate([seed, pad])
        elif n > target_dof:
            seed = seed[-target_dof:] if prepend else seed[:target_dof]
        return np.deg2rad(seed)

    # ── FK / IK computation ───────────────────────────────────────────

    def _fk_se3(self, chain_id: str, actual_angles_deg: list[float], in_world: bool = False) -> np.ndarray | None:
        """Forward kinematics returning a 4x4 homogeneous transform directly.

        Unlike ``_fk_pose``, this avoids the rotation-matrix → RPY → rotation-matrix
        round-trip, which can lose information near gimbal-lock orientations.

        Args:
            chain_id: Chain identifier.
            actual_angles_deg: Joint angles in URDF frame (degrees).
            in_world: Use world-frame solver when True.

        Returns:
            Optional[np.ndarray]: 4x4 SE3 transform, or None when solver unavailable.
        """
        solver = self._get_world_ik_solver(chain_id) if in_world else self._get_ik_solver(chain_id)
        if solver is None:
            return None
        if in_world:
            maybe_padded_angles_deg = [0.0] * (solver.dof - len(actual_angles_deg)) + actual_angles_deg
        else:
            maybe_padded_angles_deg = actual_angles_deg
        pos, rot = solver.fk(np.deg2rad(np.array(maybe_padded_angles_deg)))
        se3 = np.eye(4, dtype=np.float64)
        se3[:3, :3] = rot
        se3[:3, 3] = pos
        return se3

    def _fk_pose(self, chain_id: str, actual_angles_deg: list[float], in_world: bool = False) -> list[float] | None:
        """Forward kinematics returning [x, y, z, roll, pitch, yaw].

        Args:
            chain_id: Chain identifier.
            actual_angles_deg: Joint angles in URDF frame (degrees).
            in_world: Use world-frame solver when True.

        Returns:
            Optional[List[float]]: TCP pose, or None when solver unavailable.
        """
        se3 = self._fk_se3(chain_id, actual_angles_deg, in_world)
        if se3 is None:
            return None
        rpy = _matrix_to_rpy(se3[:3, :3])
        return [float(se3[0, 3]), float(se3[1, 3]), float(se3[2, 3]), rpy[0], rpy[1], rpy[2]]

    # ── Internal API (called by routes, NOT overridden by user) ───────

    def read_state(self) -> dict[str, Any]:
        """Read unified robot state payload.

        Returns:
            Dict[str, Any]: State with chains, e_stop, timestamp.
        """
        if self._mode == "simulation":
            return self._read_sim_state()
        return self._read_real_state()

    def _read_sim_state(self) -> dict[str, Any]:
        """Build state payload from simulation joints."""
        chains: dict[str, Any] = {}
        for chain in self._chains:
            actual = self._sim_joints[chain.id]
            logical = self._actual_to_logical(chain.id, actual)
            joints = [{"joint_id": i + 1, "angle_deg": float(logical[i])} for i in range(len(logical))]
            chains[chain.id] = {
                "enabled": not self._estop_state,
                "joints": joints,
                "joint_targets": joints,
                "ee_target": self._get_ee_target_for_state(chain.id),
            }
        return {
            "timestamp": time.perf_counter(),
            "e_stop": self._estop_state,
            "motion_enabled": not self._estop_state,
            "chains": chains,
        }

    def _read_real_state(self) -> dict[str, Any]:
        """Build state payload from real robot."""
        chains: dict[str, Any] = {}
        estop = False
        try:
            estop = self.get_estop()
        except Exception as exc:
            raise RuntimeError(f"failed to read estop state: {exc}") from exc
        self._estop_state = estop
        for chain in self._chains:
            try:
                logical = list(self.get_joint_states(chain.id))
                self._real_joint_currents[chain.id] = logical
            except Exception:
                cached = self._real_joint_currents.get(chain.id)
                logical = cached if cached is not None else [0.0] * len(chain.joints)
                self._real_joint_currents[chain.id] = logical
            ee_target = self._compute_real_ee_target(chain.id, logical)
            target_logical = self._real_joint_targets.get(chain.id, logical)
            chains[chain.id] = {
                "enabled": not estop,
                "joints": [{"joint_id": i + 1, "angle_deg": float(logical[i])} for i in range(len(logical))],
                "joint_targets": [
                    {"joint_id": i + 1, "angle_deg": float(target_logical[i])} for i in range(len(target_logical))
                ],
                "ee_target": ee_target,
            }
        payload: dict[str, Any] = {
            "timestamp": time.perf_counter(),
            "e_stop": estop,
            "motion_enabled": not estop,
            "chains": chains,
        }
        if self._init_error is not None:
            payload["plugin_warning"] = self._init_error
        return payload

    def move_joint(self, chain_id: str, target_logical_deg: list[float]) -> str:
        """Execute joint-space command, dispatching to sim or real.

        Args:
            chain_id: Chain identifier.
            target_logical_deg: Target logical angles in degrees.

        Returns:
            str: "ok" on success, error message otherwise.
        """
        if self._estop_state:
            return "blocked: estop active"
        chain = self._chain_map.get(chain_id)
        if chain is None:
            return f"invalid chain: {chain_id}"
        n = len(chain.joints)
        if len(target_logical_deg) != n:
            return f"expected {n} joints, got {len(target_logical_deg)}"
        if self._mode == "simulation":
            actual = self._logical_to_actual(chain_id, target_logical_deg)
            self._sim_joints[chain_id] = self._clamp_joints(chain_id, actual)
            self._sync_shared_joints(chain_id)
            # Refresh the maintained EE target from FK so the next cartesian
            # jog command starts from the correct pose rather than an outdated target.
            self._refresh_ee_target_from_fk(chain_id)
            return "ok"
        try:
            # for safety, we also clamp the real robot command to URDF limits.
            actual = self._logical_to_actual(chain_id, target_logical_deg)
            target_actual_deg_clamped = self._clamp_joints(chain_id, actual)
            target_logical_deg_clamped = self._actual_to_logical(chain_id, target_actual_deg_clamped)
            self.set_joint_targets(chain_id, target_logical_deg_clamped)
            self._real_joint_targets[chain_id] = list(target_logical_deg_clamped)
            # Reset the real-mode cartesian target so the next jog starts
            # from the actual pose after this joint command completes.
            self._real_ee_target.pop(chain_id, None)
            return "ok"
        except Exception as exc:
            return f"real command failed: {exc}"

    def _sync_shared_joints(self, source_chain_id: str) -> None:
        """Propagate joint values to other chains that share the same joint names.

        When multiple chains include the same physical joint (e.g. wrist joints
        shared by finger chains), the simulation must stay consistent so that the
        3-D renderer always applies the same angle to a given URDF joint regardless
        of which chain it queries.

        Args:
            source_chain_id: The chain whose joints were just updated.
        """
        source_chain = self._chain_map.get(source_chain_id)
        if source_chain is None:
            return
        source_actual = self._sim_joints[source_chain_id]
        # Build a mapping: joint_name -> updated actual angle from the source chain.
        updated: dict[str, float] = {name: source_actual[i] for i, name in enumerate(source_chain.joints)}
        for other in self._chains:
            if other.id == source_chain_id:
                continue
            other_actual = list(self._sim_joints[other.id])
            changed = False
            for j_idx, j_name in enumerate(other.joints):
                if j_name in updated:
                    other_actual[j_idx] = updated[j_name]
                    changed = True
            if changed:
                self._sim_joints[other.id] = other_actual

    def move_cartesian(self, chain_id: str, delta_xyzrpy: list[float], frame: str = "tool") -> str:
        """Execute cartesian-space command, dispatching to sim or real.

        Args:
            chain_id: Chain identifier.
            delta_xyzrpy: Cartesian delta [dx, dy, dz, droll, dpitch, dyaw].
            frame: Reference frame, 'tool' or 'world'.

        Returns:
            str: "ok" on success, error message otherwise.
        """
        if self._estop_state:
            return "blocked: estop active"
        if frame not in {"tool", "world"}:
            return f"invalid frame: {frame}"
        chain = self._chain_map.get(chain_id)
        if chain is None:
            return f"invalid chain: {chain_id}"
        if len(delta_xyzrpy) != 6:
            return "invalid cartesian delta"

        if self._mode != "simulation":
            return self._move_cartesian_real(chain_id, delta_xyzrpy, frame)

        # ── Simulation path: IK against a maintained EE target matrix ──
        # The target matrix is updated by the delta each step, but a FK
        # error from a previous IK call does NOT feed back into the target.
        # This prevents the "drifting base" problem that caused branch-flipping
        # in the original approach (FK(q_solved) ≠ T_ideal by ε each step).
        result = self._sim_jog_cartesian(chain_id, delta_xyzrpy, frame)
        if result is None:
            return "IK: no cartesian solver available for this chain"
        if isinstance(result, str):
            return result
        # Apply directly to _sim_joints to avoid _refresh_ee_target_from_fk
        # overwriting the maintained EE target we just advanced.
        actual = self._logical_to_actual(chain_id, result)
        self._sim_joints[chain_id] = self._clamp_joints(chain_id, actual)
        self._sync_shared_joints(chain_id)
        return "ok"

    def _get_ee_target_for_state(self, chain_id: str) -> list[list[float]] | None:
        """Return the maintained EE target as a 4x4 row-major list, or None.

        Args:
            chain_id: Chain identifier.

        Returns:
            Optional[List[List[float]]]: 4x4 matrix rows, or None.
        """
        mat = self._sim_ee_target.get(chain_id)
        if mat is None:
            return None
        return mat.tolist()

    def _compute_real_ee_target(self, chain_id: str, logical_angles: list[float]) -> list[list[float]] | None:
        """Compute the world-frame EE pose for real mode via base-class FK.

        This uses the base-class FK (not the plugin's ``get_ee_pose``) so that
        real-mode state always includes an ee_target without requiring plugins
        to implement extra methods.

        Args:
            chain_id: Chain identifier.
            logical_angles: Current logical joint angles in degrees.

        Returns:
            Optional[List[List[float]]]: 4x4 matrix rows, or None on FK failure.
        """
        actual = self._logical_to_actual(chain_id, logical_angles)
        se3_in_base = self._fk_se3(chain_id, actual, in_world=False)
        if se3_in_base is None:
            return None
        t_world_base = self._se3_base_in_world.get(chain_id)
        if t_world_base is None:
            return se3_in_base.tolist()
        se3_in_world: np.ndarray = t_world_base @ se3_in_base
        return se3_in_world.tolist()

    def _refresh_ee_target_from_fk(self, chain_id: str) -> None:
        """Update the maintained EE target using current joint angles and FK.

        Called after a joint command so that the next cartesian jog starts
        from the actual current pose rather than a stale target.
        Uses ``_fk_se3`` to avoid the RPY round-trip that can corrupt the
        rotation matrix near gimbal-lock orientations.

        Args:
            chain_id: Chain identifier.
        """
        actual = self._sim_joints[chain_id]
        world_se3 = self._fk_se3(chain_id, actual, in_world=True)
        if world_se3 is None:
            return
        self._sim_ee_target[chain_id] = world_se3

    def _get_or_init_ee_target(self, chain_id: str) -> np.ndarray:
        """Return the maintained EE target, initialising from FK if absent.

        Args:
            chain_id: Chain identifier.

        Returns:
            np.ndarray: 4x4 world-frame homogeneous transform.
        """
        if chain_id not in self._sim_ee_target:
            self._refresh_ee_target_from_fk(chain_id)
        mat = self._sim_ee_target.get(chain_id)
        if mat is None:
            # FK unavailable (no solver yet); fall back to identity.
            return np.eye(4, dtype=np.float64)
        return mat

    def _sim_jog_cartesian(
        self,
        chain_id: str,
        delta_xyzrpy: list[float],
        frame: str,
    ) -> list[float] | str | None:
        """Apply delta to EE target then solve IK, returning logical joint angles.

        The EE target is maintained independently of the current joint state so
        that IK inaccuracies do not accumulate.  When IK finds no solution the
        EE target is rolled back to its value before the delta was applied so
        that subsequent jog commands start from the last reachable pose.

        Args:
            chain_id: Chain identifier.
            delta_xyzrpy: Cartesian delta [dx, dy, dz, droll, dpitch, dyaw].
            frame: 'tool' or 'world'.

        Returns:
            List[float] with new logical joint angles on success;
            str with an error message when IK has no solution;
            None when no solver is available.
        """

        # ── Step 1: advance EE target by delta ───────────────────────────
        t_current = self._get_or_init_ee_target(chain_id)
        delta_pos = np.array(delta_xyzrpy[:3], dtype=np.float64)
        delta_rot = _rpy_to_matrix(delta_xyzrpy[3:6])

        if frame == "tool":
            # Delta expressed in EE frame → compose on the right.
            t_target = t_current @ _pose_to_transform(delta_xyzrpy)
        else:
            # Delta expressed in world frame.
            t_target = t_current.copy()
            t_target[:3, :3] = delta_rot @ t_current[:3, :3]
            t_target[:3, 3] = t_current[:3, 3] + delta_pos

        # Speculatively update the target.  Roll back to t_current on IK failure
        # so the edge of the reachable workspace never shifts further out.
        self._sim_ee_target[chain_id] = t_target

        # ── Step 2: convert world-frame target to base-frame ─────────────
        t_target_in_base = self._se3_world_in_base[chain_id] @ t_target
        # target_xyzrpy = _transform_to_pose(t_target_in_base)

        # ── Step 3: IK with current joints as seed ───────────────────────
        seed_actual_deg = np.deg2rad(self._sim_joints[chain_id])
        try:
            solver = self._get_ik_solver(chain_id)
            solved_actual_rad = solver.ik(
                t_target_in_base[:3, 3],
                t_target_in_base[:3, :3],
                seed_actual_deg,
            )
            if solved_actual_rad is None:
                raise ValueError("IK: no solution found.")
            if np.max(np.abs(np.rad2deg(solved_actual_rad - seed_actual_deg))) > 25:
                raise ValueError(
                    f"IK: solution (diff: {(np.rad2deg(solved_actual_rad) - seed_actual_deg).round(0)}) too far from seed (>25°)."
                )
            solved_actual_deg = list(np.rad2deg(solved_actual_rad))
        except Exception as exc:
            # IK failed — roll back the EE target so the next attempt can retry.
            self._sim_ee_target[chain_id] = t_current
            return str(exc)

        if solved_actual_deg is None:
            self._sim_ee_target[chain_id] = t_current
            return "IK: solver not available"

        return self._actual_to_logical(chain_id, solved_actual_deg)

    def set_ee_target_from_mat(self, chain_id: str, world_matrix: list[list[float]]) -> str:
        """Set the EE target to an absolute world-frame pose and solve IK.

        Called when the user directly types a 4x4 matrix in the frontend.
        In real mode delegates to ``set_ee_pose_target``.

        Args:
            chain_id: Chain identifier.
            world_matrix: 4x4 row-major homogeneous transform (world frame).

        Returns:
            str: "ok" on success, error message otherwise.
        """
        if self._estop_state:
            return "blocked: estop active"
        chain = self._chain_map.get(chain_id)
        if chain is None:
            return f"invalid chain: {chain_id}"

        try:
            mat = np.array(world_matrix, dtype=np.float64)
            if mat.shape != (4, 4):
                return "matrix must be 4x4"
        except Exception as exc:
            return f"invalid matrix: {exc}"

        # ── Legalize matrix ───────────────────────────────────────────────
        # Orthogonalize the rotation part via SVD so that non-orthonormal
        # user input (e.g. from rounding) does not confuse downstream code.
        R = mat[:3, :3]
        U, _, Vt = np.linalg.svd(R)
        R_ortho = U @ Vt
        # Ensure proper rotation (det = +1); correct reflection if needed.
        if np.linalg.det(R_ortho) < 0:
            U[:, -1] *= -1
            R_ortho = U @ Vt
        mat[:3, :3] = R_ortho
        # Enforce homogeneous bottom row [0, 0, 0, 1].
        mat[3] = np.array([0.0, 0.0, 0.0, 1.0])

        if self._mode != "simulation":
            # Real mode: delegate to the plugin-overrideable cartesian target setter.
            try:
                self.set_ee_pose_target(chain_id, mat)
                # Sync the maintained real-mode cartesian target so subsequent
                # jog commands start from this absolute pose.
                self._real_ee_target[chain_id] = mat.copy()
                return "ok"
            except Exception as exc:
                return f"cartesian command failed: {exc}"

        # ── Simulation path: IK + rollback on failure ─────────────────────

        prev_target = self._sim_ee_target.get(chain_id)
        self._sim_ee_target[chain_id] = mat

        t_target_in_base = self._se3_world_in_base[chain_id] @ mat

        seed_actual_deg = np.deg2rad(self._sim_joints[chain_id])
        try:
            solver = self._get_ik_solver(chain_id)
            solved_actual_rad = solver.ik(
                t_target_in_base[:3, 3],
                t_target_in_base[:3, :3],
                seed_actual_deg,
            )
            if solved_actual_rad is None:
                raise ValueError("IK: no solution found.")
            if np.max(np.abs(np.rad2deg(solved_actual_rad - seed_actual_deg))) > 25:
                raise ValueError(
                    f"IK: solution (diff: {(np.rad2deg(solved_actual_rad) - seed_actual_deg).round(0)}) too far from seed (>25°)."
                )
            solved_actual_deg = list(np.rad2deg(solved_actual_rad))
        except ValueError as exc:
            # Roll back EE target to previous value so state reflects reality.
            if prev_target is not None:
                self._sim_ee_target[chain_id] = prev_target
            else:
                self._sim_ee_target.pop(chain_id, None)
            return str(exc)

        if solved_actual_deg is None:
            if prev_target is not None:
                self._sim_ee_target[chain_id] = prev_target
            else:
                self._sim_ee_target.pop(chain_id, None)
            return "IK: solver not available"

        logical = self._actual_to_logical(chain_id, solved_actual_deg)
        actual = self._logical_to_actual(chain_id, logical)
        self._sim_joints[chain_id] = self._clamp_joints(chain_id, actual)
        self._sync_shared_joints(chain_id)
        return "ok"

    def _get_or_init_real_ee_target(self, chain_id: str) -> np.ndarray:
        """Return the maintained real-mode EE target, initialising from current pose if absent.

        Args:
            chain_id: Chain identifier.

        Returns:
            np.ndarray: 4x4 world-frame homogeneous transform.
        """
        if chain_id not in self._real_ee_target:
            try:
                self._real_ee_target[chain_id] = self.get_ee_pose(chain_id).copy()
            except Exception:
                raise RuntimeError(f"cannot initialise real EE target for {chain_id}")
        return self._real_ee_target[chain_id]

    def _refresh_real_ee_target(self, chain_id: str) -> None:
        """Reset the maintained real-mode EE target from the current real pose.

        Called after joint commands or other operations so the next cartesian
        jog starts from the actual robot pose.

        Args:
            chain_id: Chain identifier.
        """
        try:
            self._real_ee_target[chain_id] = self.get_ee_pose(chain_id).copy()
        except Exception:
            # If reading fails, discard the stale target so it re-initialises.
            self._real_ee_target.pop(chain_id, None)

    def _move_cartesian_real(self, chain_id: str, delta_xyzrpy: list[float], frame: str) -> str:
        """Real-mode cartesian jog against a maintained EE target.

        The target is maintained independently of the actual robot pose so
        that motion delays do not cause the commanded trajectory to drift.
        """
        try:
            t_current = self._get_or_init_real_ee_target(chain_id)
        except Exception as exc:
            return f"get_ee_pose failed: {exc}"

        delta_pos = np.array(delta_xyzrpy[:3], dtype=np.float64)
        delta_rot = _rpy_to_matrix(delta_xyzrpy[3:6])

        if frame == "tool":
            se3_target = t_current @ _pose_to_transform(delta_xyzrpy)
        else:
            se3_target = t_current.copy()
            se3_target[:3, :3] = delta_rot @ t_current[:3, :3]
            se3_target[:3, 3] = t_current[:3, 3] + delta_pos

        try:
            self.set_ee_pose_target(chain_id, se3_target)
            # Only advance the maintained target after the command succeeds.
            self._real_ee_target[chain_id] = se3_target
            # Update joint targets for state reporting so the display shows the
            # IK-solved target (not stale joint-command targets from a previous
            # move_joint call).  Plugins that override set_ee_pose_target without
            # calling super() should override resolve_cartesian_joint_targets so
            # this value is available.
            resolved = self.resolve_cartesian_joint_targets(chain_id, se3_target)
            if resolved is not None:
                self._real_joint_targets[chain_id] = resolved
            return "ok"
        except Exception as exc:
            return f"cartesian command failed: {exc}"

    def estop(self, trigger: bool) -> str:
        """Trigger or release emergency stop.

        Args:
            trigger: True to trigger, False to release.

        Returns:
            str: Human-readable status message.
        """
        if self._mode == "simulation":
            self._estop_state = trigger
            return "estop triggered" if trigger else "estop released"
        try:
            self.set_estop(trigger)
            self._estop_state = trigger

            # clear the maintained real-mode EE and joint targets
            for chain in self._chains:
                self._real_ee_target.pop(chain.id, None)
                self._real_joint_targets.pop(chain.id, None)

        except Exception as exc:
            raise RuntimeError(f"estop command failed: {exc}") from exc
        return "estop triggered" if trigger else "estop released"

    def get_mode_status(self) -> dict[str, Any]:
        """Read runtime mode and connection status.

        Returns:
            Dict[str, Any]: Mode status payload.
        """
        return {
            "mode": self._mode,
            "available_modes": ["simulation", "real"],
            "connected": True,
            "message": self._init_error,
        }

    def switch_mode(self, mode: str) -> str:
        """Switch between simulation and real mode.

        Args:
            mode: Target mode ('simulation' or 'real').

        Returns:
            str: "ok" on success, error message otherwise.
        """
        target = str(mode).strip().lower()
        if target not in {"simulation", "real"}:
            return f"invalid mode: {mode}"
        if target == self._mode:
            return "ok"
        if target == "simulation":
            self.on_mode_exit_real()
            self._mode = "simulation"
            self._init_error = None
            # Discard real-mode cartesian targets; simulation uses its own.
            self._real_ee_target.clear()
            self._real_joint_targets.clear()
            return "ok"
        result = self.on_mode_enter_real()
        if result == "ok":
            self._mode = "real"
            self._init_error = None
            # Clear stale targets so they re-initialise from the real robot.
            self._real_ee_target.clear()
            self._real_joint_targets.clear()
            return "ok"
        return f"failed to enter real mode: {result}"

    def get_urdf_path(self) -> str | None:
        """Return resolved URDF file path when available.

        Returns:
            Optional[str]: Absolute URDF path, or None.
        """
        if self._urdf_path and Path(self._urdf_path).exists():
            return self._urdf_path
        return None

    def get_robot_metadata(self) -> dict[str, Any]:
        """Return plugin metadata for frontend rendering.

        Returns:
            Dict[str, Any]: Chains, camera info, and display names.
        """
        real_cfg = self._config.get("real", {})
        camera_list = real_cfg.get("cameras", [])
        if not isinstance(camera_list, list):
            camera_list = []
        camera_names = [str(c["id"]) for c in camera_list if isinstance(c, dict)]
        camera_name_map = {str(c["id"]): str(c.get("name", c["id"])) for c in camera_list if isinstance(c, dict)}
        return {
            "chains": [
                {
                    "id": c.id,
                    "name": c.name,
                    "joint_map": list(c.joints),
                    "joint_offsets_deg": list(c.joint_offsets_deg),
                    "base_link": c.base_link,
                    "tip_link": c.tip_link,
                }
                for c in self._chains
            ],
            "camera_names": camera_names,
            "camera_name_map": camera_name_map,
        }

    # ── Virtual hooks for mode switching ──────────────────────────────

    def on_mode_enter_real(self) -> str:
        """Prepare real mode resources such as workers, sockets, or hardware sessions.

        Returns:
            str: "ok" on success, otherwise an error message exposed through the API.
        """
        return "ok"

    def on_mode_exit_real(self) -> None:
        """Release real mode resources before returning to simulation mode."""

    def on_client_connected(self, channel: Literal["camera", "state"], key: str | None = None) -> None:
        """Handle first active client for a channel.

        Args:
            channel: Logical channel name, e.g. 'camera' or 'state'.
            key: Optional channel key, e.g. camera id.
        """

    def on_client_disconnected(self, channel: Literal["camera", "state"], key: str | None = None) -> None:
        """Handle transition to no active client for a channel.

        Args:
            channel: Logical channel name, e.g. 'camera' or 'state'.
            key: Optional channel key, e.g. camera id.
        """

    # ── Abstract methods: real robot (user implements) ────────────────

    @abstractmethod
    def get_joint_states(self, chain_id: str) -> list[float]:
        """Read current logical joint angles from the real implementation.

        Args:
            chain_id: Chain identifier.

        Returns:
            List[float]: Joint angles in degrees, expressed in the plugin's logical frame.
        """

    @abstractmethod
    def set_joint_targets(self, chain_id: str, target_angles_deg: list[float]) -> None:
        """Send a logical joint target command to the real implementation.

        Args:
            chain_id: Chain identifier.
            target_angles_deg: Target joint angles in degrees, in logical coordinates.
        """

    @abstractmethod
    def get_estop(self) -> bool:
        """Read the current emergency-stop state from the real implementation.

        Returns:
            bool: True when e-stop is active.
        """

    @abstractmethod
    def set_estop(self, trigger: bool) -> None:
        """Trigger or release the emergency-stop state in the real implementation.

        Args:
            trigger: True to trigger, False to release.
        """

    @abstractmethod
    def get_ee_pose(self, chain_id: str) -> np.ndarray:
        """Return the current end-effector pose for one chain.

        Args:
            chain_id: Chain identifier.

        Returns:
            np.ndarray: 4x4 homogeneous transform (tip in world).
        """
        raise NotImplementedError("get_ee_pose must be overridden by plugin implementations")

    @abstractmethod
    def set_ee_pose_target(self, chain_id: str, se3_target_in_world: np.ndarray) -> None:
        """Accept a world-frame end-effector target for one chain.

        Args:
            chain_id: Chain identifier.
            se3_target_in_world: 4x4 homogeneous target transform (tip in world).
        """
        raise NotImplementedError("set_ee_pose_target must be overridden by plugin implementations")

    def resolve_cartesian_joint_targets(self, chain_id: str, se3_target_in_world: np.ndarray) -> list[float]:
        """Return the IK-solved joint targets used by the last set_ee_pose_target call.

        The dilemma is that the base class needs to report joint targets for error and target
        display in the frontend (joint control section), but it has no way to know how a
        plugin's custom set_ee_pose_target implementation resolves the target pose to joints.
        This method is a hook that plugins can override to return the resolved joint targets.

        The default implementation returns joint targets from sim IK solver given target se3
        and current joint angles.

        Args:
            chain_id: Chain identifier.
            se3_target_in_world: World-frame target pose (same value that was
                passed to ``set_ee_pose_target``).

        Returns:
            Logical joint angles in degrees.
        """
        solver = self._get_ik_solver(chain_id)
        se3_target_in_base = self._se3_world_in_base[chain_id] @ se3_target_in_world
        seed_actual_rad = np.deg2rad(self._logical_to_actual(chain_id, self._real_joint_currents[chain_id]))
        solved_actual_rad = solver.ik(
            se3_target_in_base[:3, 3],
            se3_target_in_base[:3, :3],
            seed_actual_rad,
        )
        if solved_actual_rad is None:
            return (np.array(self._real_joint_currents[chain_id]) * 0.0).tolist()
        solved_logical = self._actual_to_logical(chain_id, list(np.rad2deg(solved_actual_rad)))
        return list(solved_logical)

    def get_camera_frame(self, camera_id: str) -> tuple[str, float] | None:
        """Get one camera frame as (data_url, timestamp_ms) or None.

        Simulation mode returns a placeholder frame immediately.
        Real mode delegates to ``get_real_camera_frame``, which should be overridden
        by real-hardware plugins and may return None on internal timeout.

        Args:
            camera_id: Camera identifier.

        Returns:
            Tuple of (data_url str, timestamp_ms float), or None (real mode only).
        """
        if self._mode == "simulation":
            data_url = self._camera_placeholder_data_url(camera_id, "Simulation mode: no physical camera")
            ts_ms = time.perf_counter_ns() / 1_000_000.0
            return data_url, ts_ms
        return self.get_real_camera_frame(camera_id)

    def get_real_camera_frame(self, camera_id: str) -> tuple[str, float] | None:
        """Fetch one frame from real hardware.

        Subclasses must override this in real-hardware plugins. The implementation
        should block until a new frame is available or an internal deadline expires,
        returning None on timeout.

        Args:
            camera_id: Camera identifier.

        Returns:
            Tuple of (data_url str, timestamp_ms float), or None on timeout.
        """
        raise NotImplementedError(f"Real camera {camera_id!r} not implemented by this plugin")

    def get_camera_receive_fps(self, camera_id: str) -> float:
        """Return hardware frame receive FPS for camera_id.

        Override in real-hardware plugins that track receive cadence.

        Args:
            camera_id: Camera identifier.

        Returns:
            float: Frames per second received from hardware, or 0.0.
        """
        return 0.0

    # ── Camera placeholder ────────────────────────────────────────────

    @staticmethod
    def _camera_placeholder_data_url(camera_name: str, text: str) -> str:
        """Build a placeholder SVG image as a data URL.

        Args:
            camera_name: Camera alias (unused in SVG, kept for signature symmetry).
            text: Placeholder message to render.

        Returns:
            str: SVG data URL.
        """
        svg = (
            f"<svg xmlns='http://www.w3.org/2000/svg' width='640' height='480'>"
            f"<rect width='100%' height='100%' fill='#1f2a44'/>"
            f"<text x='24' y='58' font-size='30' fill='#f4f5f7'>{text}</text>"
            f"</svg>"
        )
        b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{b64}"


# ── Plugin registry ───────────────────────────────────────────────────────

_plugin_registry: dict[type, tuple[str, str]] = {}


def register_plugin(*, name: str, description: str = "") -> type:
    """Class decorator that registers a RobotPlugin subclass.

    Args:
        name: Human-readable plugin name.
        description: Short plugin description.

    Returns:
        The decorated class, unmodified.
    """

    def _decorator(cls: type[RobotPlugin]) -> type[RobotPlugin]:
        _plugin_registry[cls] = (name, description)
        return cls

    return _decorator  # type: ignore[return-value]


def get_plugin_registration(cls: type) -> tuple[str, str] | None:
    """Look up registry entry for a plugin class.

    Args:
        cls: Plugin class.

    Returns:
        (name, description) tuple, or None if unregistered.
    """
    return _plugin_registry.get(cls)
