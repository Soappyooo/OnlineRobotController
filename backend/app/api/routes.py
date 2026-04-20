"""API routes for Online Robot Controller."""

from __future__ import annotations

import asyncio
from pathlib import Path
import time
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi import HTTPException

from app.core.config import persist_active_plugin
from app.models.protocol import (
    Ack,
    CartesianJogCommand,
    EeTargetSetCommand,
    EStopCommand,
    JointCommand,
    ModeStatus,
    ModeSwitchCommand,
    PluginCatalog,
    PluginConfigPayload,
    PluginConfigUpdateCommand,
    PluginOption,
    PluginSelectCommand,
    RobotState,
)
from app.plugins.manager import PluginManager

router = APIRouter()
plugin_manager = PluginManager()


@router.get("/health")
def health() -> dict[str, str]:
    """Health endpoint."""
    return {"status": "ok", "plugin": plugin_manager.get_active_name()}


@router.get("/profile")
def runtime_profile(request: Request) -> dict[str, object]:
    """Runtime profile consumed by frontend at startup."""
    origin = str(request.base_url).rstrip("/")
    ws_scheme = "wss" if request.url.scheme == "https" else "ws"
    active_plugin = plugin_manager.get_active_name()
    active_plugin_instance = plugin_manager.get_active_plugin()
    mode_status = active_plugin_instance.get_mode_status()
    active_config = plugin_manager.get_plugin_config(active_plugin)
    active_mode = str(mode_status.get("mode", active_config.get("mode", "simulation")))
    metadata = (
        active_plugin_instance.get_robot_metadata() if hasattr(active_plugin_instance, "get_robot_metadata") else {}
    )
    camera_names = active_config.get("camera_names", [])

    if not isinstance(camera_names, list):
        camera_names = []

    chains_meta = metadata.get("chains", []) if isinstance(metadata, dict) else []
    profile_chain_name_map: dict[str, str] = {}
    profile_chain_ids = [str(item.get("id", "")).strip() for item in chains_meta if isinstance(item, dict)]
    profile_chain_ids = [item for item in profile_chain_ids if item]
    if not profile_chain_ids:
        profile_chain_ids = (
            [c.id for c in active_plugin_instance._chains] if hasattr(active_plugin_instance, "_chains") else []
        )

    profile_joint_map: dict[str, list[str]] = {}
    profile_joint_offsets: dict[str, list[float]] = {}
    profile_tip_links: dict[str, str] = {}
    for chain in chains_meta:
        if not isinstance(chain, dict):
            continue
        chain_id = str(chain.get("id", "")).strip()
        if not chain_id:
            continue
        chain_name = str(chain.get("name", "")).strip()
        if chain_name:
            profile_chain_name_map[chain_id] = chain_name
        map_raw = chain.get("joint_map", [])
        if isinstance(map_raw, list):
            profile_joint_map[chain_id] = [str(item) for item in map_raw if str(item).strip()]
        offsets_raw = chain.get("joint_offsets_deg", [])
        if isinstance(offsets_raw, list):
            raw_floats: list[float] = []
            for item in offsets_raw:
                try:
                    raw_floats.append(float(item))
                except (TypeError, ValueError):
                    raw_floats.append(0.0)
            profile_joint_offsets[chain_id] = (raw_floats + [0.0] * 6)[:6]
        tip_link = str(chain.get("tip_link", "")).strip()
        if tip_link:
            profile_tip_links[chain_id] = tip_link

    if not profile_joint_map:
        profile_joint_map = {cid: [] for cid in profile_chain_ids}
    if not profile_joint_offsets:
        profile_joint_offsets = {cid: [0.0] * 6 for cid in profile_chain_ids}
    if not profile_tip_links:
        profile_tip_links = {cid: "" for cid in profile_chain_ids}

    profile_camera_names = metadata.get("camera_names", camera_names) if isinstance(metadata, dict) else camera_names
    if not isinstance(profile_camera_names, list):
        profile_camera_names = camera_names
    profile_camera_name_map = metadata.get("camera_name_map", {}) if isinstance(metadata, dict) else {}
    if not isinstance(profile_camera_name_map, dict):
        profile_camera_name_map = {}

    urdf_url = f"/api/robot/urdf?v={int(time.time())}"
    active_plugin_for_urdf = plugin_manager.get_active_plugin()
    _get_urdf_fn = getattr(active_plugin_for_urdf, "get_urdf_path", None)
    if callable(_get_urdf_fn):
        _path_raw = _get_urdf_fn()
        if _path_raw:
            _urdf_abs = Path(str(_path_raw)).resolve()
            _project_root = Path(__file__).resolve().parents[3]
            try:
                _proj_rel = _urdf_abs.relative_to(_project_root)
                urdf_url = f"/api/robot/meshes/{_proj_rel.as_posix()}?v={int(time.time())}"
            except ValueError:
                pass

    plugin_options = [item.name for item in plugin_manager.list_plugins()]

    return {
        "appTitle": "Online Robot Controller",
        "apiBase": "/api",
        "wsBase": "/api/ws",
        "urdfUrl": urdf_url,
        "cameraNames": [str(item) for item in profile_camera_names if str(item).strip()],
        "chains": profile_chain_ids,
        "chainNameMap": profile_chain_name_map,
        "jointMap": profile_joint_map,
        "jointOffsetsDeg": profile_joint_offsets,
        "tipLinks": profile_tip_links,
        "cameraNameMap": {str(key): str(value) for key, value in profile_camera_name_map.items()},
        "activePlugin": active_plugin,
        "pluginOptions": plugin_options,
        "mode": active_mode if active_mode in {"real", "simulation"} else "real",
        "commandHz": active_config.get("general", {}).get("command_hz", 60),
        "stateHz": active_config.get("general", {}).get("state_hz", 60),
        "cameraHz": active_config.get("general", {}).get("camera_hz", 15),
        "defaultAngleStepDeg": active_config.get("general", {}).get("default_angle_step_deg", 1.0),
        "defaultLengthStepM": active_config.get("general", {}).get("default_length_step_m", 0.005),
    }


@router.get("/robot/urdf")
def robot_urdf() -> FileResponse:
    """Serve active plugin URDF file."""
    plugin = plugin_manager.get_active_plugin()
    get_urdf_path_fn = getattr(plugin, "get_urdf_path", None)
    if not callable(get_urdf_path_fn):
        raise HTTPException(status_code=404, detail="active plugin does not expose urdf")
    path_raw = get_urdf_path_fn()
    if not path_raw:
        raise HTTPException(status_code=404, detail="urdf path unavailable")
    return FileResponse(path=str(path_raw))


@router.get("/robot/meshes/{mesh_path:path}")
def robot_urdf_mesh(mesh_path: str) -> FileResponse:
    """Serve mesh assets using project-relative paths produced by the URDF rewriter."""
    project_root = Path(__file__).resolve().parents[3]
    target = (project_root / mesh_path).resolve()

    try:
        target.relative_to(project_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid mesh path") from exc

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="mesh not found")

    return FileResponse(path=str(target))


@router.get("/plugins", response_model=PluginCatalog)
def plugin_catalog() -> PluginCatalog:
    """Return available plugins with active selection."""
    options = [
        PluginOption(
            name=item.name,
            description=item.description,
        )
        for item in plugin_manager.list_plugins()
    ]
    return PluginCatalog(active_plugin=plugin_manager.get_active_name(), available_plugins=options)


@router.post("/plugins/select", response_model=Ack)
def plugin_select(command: PluginSelectCommand) -> Ack:
    """Switch active plugin at runtime."""
    plugin_manager.switch_plugin(command.plugin)
    persist_active_plugin(command.plugin)
    return Ack(ok=True, message=f"switched to {command.plugin}")


@router.get("/plugins/config/{plugin_name}", response_model=PluginConfigPayload)
def plugin_config_read(plugin_name: str) -> PluginConfigPayload:
    """Read plugin config payload."""
    return PluginConfigPayload(
        plugin=plugin_name,
        config=plugin_manager.get_plugin_config(plugin_name),
        config_toml=plugin_manager.get_plugin_config_toml(plugin_name),
    )


@router.put("/plugins/config/{plugin_name}", response_model=Ack)
def plugin_config_write(plugin_name: str, command: PluginConfigUpdateCommand) -> Ack:
    """Update plugin config payload and hot-reload if active."""
    if command.config_toml is not None:
        plugin_manager.set_plugin_config_toml(plugin_name, command.config_toml)
    elif command.config is not None:
        plugin_manager.set_plugin_config(plugin_name, command.config)
    else:
        return Ack(ok=False, message="missing config or config_toml")
    return Ack(ok=True, message=f"updated {plugin_name} config")


@router.get("/robot/state", response_model=RobotState)
def robot_state() -> RobotState:
    """Read full unified robot state from plugin."""
    plugin = plugin_manager.get_active_plugin()
    return RobotState.model_validate(plugin.read_state())


@router.get("/robot/mode", response_model=ModeStatus)
def robot_mode_status() -> ModeStatus:
    """Read plugin runtime mode status."""
    plugin = plugin_manager.get_active_plugin()
    return ModeStatus.model_validate(plugin.get_mode_status())


@router.post("/robot/mode", response_model=Ack)
def robot_mode_switch(command: ModeSwitchCommand) -> Ack:
    """Switch plugin runtime mode (e.g. simulation <-> real)."""
    plugin = plugin_manager.get_active_plugin()
    message = plugin.switch_mode(command.mode)
    return Ack(ok=message == "ok", message=message)


@router.post("/robot/estop", response_model=Ack)
def estop(command: EStopCommand) -> Ack:
    """Trigger or release software e-stop."""
    plugin = plugin_manager.get_active_plugin()
    return Ack(ok=True, message=plugin.estop(command.trigger))


@router.post("/robot/joint-command", response_model=Ack)
def joint_command(command: JointCommand) -> Ack:
    """Execute joint-space command."""
    plugin = plugin_manager.get_active_plugin()
    message = plugin.move_joint(command.arm, command.target_angles_deg)
    return Ack(ok=message == "ok", message=message)


@router.post("/robot/cartesian-jog", response_model=Ack)
def cartesian_jog(command: CartesianJogCommand) -> Ack:
    """Execute cartesian jog command."""
    plugin = plugin_manager.get_active_plugin()
    message = plugin.move_cartesian(command.arm, command.delta_xyzrpy, command.frame)
    return Ack(ok=message == "ok", message=message)


@router.post("/robot/ee-target/{chain_id}", response_model=Ack)
def set_ee_target_from_mat(chain_id: str, command: EeTargetSetCommand) -> Ack:
    """Set absolute end-effector target (world frame, simulation only)."""
    plugin = plugin_manager.get_active_plugin()
    message = plugin.set_ee_target_from_mat(chain_id, command.matrix)
    return Ack(ok=message == "ok", message=message)


@router.websocket("/ws/state")
async def ws_state(websocket: WebSocket) -> None:
    """Push state stream at configured frequency."""
    plugin = plugin_manager.get_active_plugin()
    await websocket.accept()
    plugin.on_client_connected(channel="state", key=None)
    active_config = plugin_manager.get_plugin_config(plugin_manager.get_active_name())
    state_hz = active_config["general"]["state_hz"]
    period = 1.0 / max(1.0, state_hz)
    try:
        while True:
            # plugin = plugin_manager.get_active_plugin()
            payload = await asyncio.to_thread(plugin.read_state)
            await websocket.send_json(payload)
            await asyncio.sleep(period)
    except WebSocketDisconnect:
        return
    finally:
        plugin.on_client_disconnected(channel="state", key=None)


@router.websocket("/ws/camera/{camera_id}")
async def ws_camera(websocket: WebSocket, camera_id: str) -> None:
    """Push camera frame stream with per-frame metrics.

    The plugin manages its own client counting internally via
    on_client_connected / on_client_disconnected.
    """
    plugin = plugin_manager.get_active_plugin()
    await websocket.accept()
    plugin.on_client_connected(channel="camera", key=camera_id)
    active_config = plugin_manager.get_plugin_config(plugin_manager.get_active_name())
    camera_hz = active_config["general"]["camera_hz"]
    period_s = 1.0 / max(1.0, camera_hz)
    last_frame_ts_ms: float | None = None
    display_fps_ema: float = 0.0
    last_send_s: float = time.perf_counter()
    ema_weight = 0.1
    try:
        while True:
            frame_start = time.perf_counter()
            mode = plugin.get_mode_status().get("mode", "simulation")
            is_sim = str(mode) == "simulation"
            result: tuple[str, float] | None = await asyncio.to_thread(plugin.get_camera_frame, camera_id)
            if result is None:
                # Real mode: timed out – decay display FPS from elapsed time, don't freeze it.
                now = time.perf_counter()
                elapsed_since_last = now - last_send_s
                display_fps_ema = 1.0 / elapsed_since_last if elapsed_since_last > 0 else 0.0
                await websocket.send_json(
                    {
                        "camera": camera_id,
                        "data_url": None,
                        "receive_fps": round(plugin.get_camera_receive_fps(camera_id), 1),
                        "display_fps": round(display_fps_ema, 1),
                        "frame_age_ms": 0.0,
                    }
                )
                continue
            data_url, frame_ts_ms = result
            if is_sim:
                payload: dict[str, object] = {
                    "camera": camera_id,
                    "data_url": data_url,
                    "receive_fps": None,
                    "display_fps": None,
                    "frame_age_ms": None,
                }
            else:
                frame_age_ms = frame_ts_ms - last_frame_ts_ms if last_frame_ts_ms is not None else 0.0
                last_frame_ts_ms = frame_ts_ms
                now = time.perf_counter()
                send_delta = now - last_send_s
                if send_delta > 0:
                    instant = 1.0 / send_delta
                    display_fps_ema = (
                        display_fps_ema * (1 - ema_weight) + instant * ema_weight if display_fps_ema > 0 else instant
                    )
                last_send_s = now
                payload = {
                    "camera": camera_id,
                    "data_url": data_url,
                    "receive_fps": round(plugin.get_camera_receive_fps(camera_id), 1),
                    "display_fps": round(display_fps_ema, 1),
                    "frame_age_ms": round(max(0.0, frame_age_ms), 1),
                }
            await websocket.send_json(payload)
            # Rate-limit to camera_hz for both sim (returns instantly) and real (hardware may be faster).
            elapsed = time.perf_counter() - frame_start
            if elapsed < period_s:
                await asyncio.sleep(period_s - elapsed)
    except WebSocketDisconnect:
        return
    finally:
        plugin.on_client_disconnected(channel="camera", key=camera_id)
