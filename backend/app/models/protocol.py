"""Pydantic protocol models for Online Robot Controller."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ChainId = str
ModeName = Literal["real", "simulation"]
CartesianFrame = Literal["tool", "world"]


class JointState(BaseModel):
    """Single joint telemetry point."""

    joint_id: int = Field(ge=1)
    angle_deg: float


class ChainState(BaseModel):
    """State of one kinematic chain."""

    enabled: bool
    joints: list[JointState]
    joint_targets: list[JointState] | None = None
    ee_target: list[list[float]] | None = None


class RobotState(BaseModel):
    """Realtime robot state message."""

    timestamp: float
    e_stop: bool
    motion_enabled: bool
    chains: dict[ChainId, ChainState]


class ModeStatus(BaseModel):
    """Runtime mode status payload."""

    mode: ModeName
    available_modes: list[ModeName]
    connected: bool
    message: str | None = None


class ModeSwitchCommand(BaseModel):
    """Runtime mode switch command payload."""

    mode: ModeName


class JointCommand(BaseModel):
    """Joint-space command."""

    arm: ChainId
    target_angles_deg: list[float] = Field(min_length=1)


class CartesianJogCommand(BaseModel):
    """Cartesian jog command."""

    arm: ChainId
    delta_xyzrpy: list[float] = Field(min_length=6, max_length=6)
    frame: CartesianFrame = "tool"


class EStopCommand(BaseModel):
    """Emergency stop command."""

    trigger: bool


class Ack(BaseModel):
    """Generic response."""

    ok: bool
    message: str


class PluginOption(BaseModel):
    """Plugin catalog option model."""

    name: str
    description: str


class PluginCatalog(BaseModel):
    """Plugin catalog payload used by frontend configuration UI."""

    active_plugin: str
    available_plugins: list[PluginOption]


class PluginSelectCommand(BaseModel):
    """Plugin switch command payload."""

    plugin: str


class PluginConfigPayload(BaseModel):
    """Plugin config envelope used in read/write API."""

    plugin: str
    config: dict[str, object]
    config_toml: str


class PluginConfigUpdateCommand(BaseModel):
    """Plugin config update payload."""

    config: dict[str, object] | None = None
    config_toml: str | None = None


class EeTargetPayload(BaseModel):
    """End-effector target matrix payload (world frame)."""

    chain_id: str
    matrix: list[list[float]]  # 4x4 row-major homogeneous transform


class EeTargetSetCommand(BaseModel):
    """Command to set an absolute EE target via a world-frame 4x4 matrix."""

    matrix: list[list[float]]  # 4x4 row-major homogeneous transform
