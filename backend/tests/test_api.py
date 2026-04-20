"""API capability tests for TODO item 8 criteria."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint() -> None:
    """Health endpoint should return status ok."""
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"


def test_runtime_profile_includes_plugin_metadata() -> None:
    """Runtime profile should expose plugin and mode metadata for frontend controls."""
    client = TestClient(app)
    response = client.get("/api/profile")
    assert response.status_code == 200
    payload = response.json()

    assert "activePlugin" in payload
    assert "pluginOptions" in payload
    assert isinstance(payload["pluginOptions"], list)
    assert payload["appTitle"] == "Online Robot Controller"
    assert set(payload["pluginOptions"]) == {"mock", "ur5_shadow"}
    assert "mode" in payload
    assert payload["mode"] in {"real", "simulation"}


def test_joint_and_cartesian_control_endpoints() -> None:
    """Joint and cartesian endpoints should be reachable."""
    client = TestClient(app)

    estop_release = client.post("/api/robot/estop", json={"trigger": False})
    assert estop_release.status_code == 200

    joint_response = client.post(
        "/api/robot/joint-command",
        json={"arm": "arm_a", "target_angles_deg": [0, 1, 2, 3, 4, 5]},
    )
    assert joint_response.status_code == 200

    cartesian_response = client.post(
        "/api/robot/cartesian-jog",
        json={"arm": "arm_b", "delta_xyzrpy": [0.01, 0, 0, 0, 0, 0]},
    )
    assert cartesian_response.status_code == 200


def test_robot_mode_endpoints() -> None:
    """Runtime mode endpoints should expose status and switch behavior."""
    client = TestClient(app)

    status_response = client.get("/api/robot/mode")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["mode"] in {"real", "simulation"}
    assert "available_modes" in status_payload
    assert isinstance(status_payload["connected"], bool)

    switch_response = client.post("/api/robot/mode", json={"mode": "simulation"})
    assert switch_response.status_code == 200
    switch_payload = switch_response.json()
    assert switch_payload["ok"] is True


def test_realtime_stream_endpoints() -> None:
    """State and camera websocket endpoints should stream payloads."""
    client = TestClient(app)

    with client.websocket_connect("/api/ws/state") as ws_state:
        message = ws_state.receive_json()
        assert "chains" in message
        assert isinstance(message["chains"], dict)
        assert len(message["chains"]) > 0

    # Use the first camera name from the active plugin's metadata.
    profile = client.get("/api/profile").json()
    camera_names = profile.get("cameraNames", [])
    if camera_names:
        cam = camera_names[0]
        with client.websocket_connect(f"/api/ws/camera/{cam}") as ws_camera:
            message = ws_camera.receive_json()
            assert message["camera"] == cam
            assert message["data_url"] is None or message["data_url"].startswith("data:image")


def test_plugin_catalog_and_config_endpoints() -> None:
    """Plugin endpoints should expose list, active plugin, and editable config."""
    client = TestClient(app)

    catalog = client.get("/api/plugins")
    assert catalog.status_code == 200
    catalog_payload = catalog.json()
    assert "active_plugin" in catalog_payload
    assert "available_plugins" in catalog_payload
    assert isinstance(catalog_payload["available_plugins"], list)
    assert catalog_payload["available_plugins"]
    assert {item["name"] for item in catalog_payload["available_plugins"]} == {"mock", "ur5_shadow"}

    first_name = catalog_payload["available_plugins"][0]["name"]
    config_read = client.get(f"/api/plugins/config/{first_name}")
    assert config_read.status_code == 200
    config_payload = config_read.json()
    assert config_payload["plugin"] == first_name
    assert isinstance(config_payload["config"], dict)

    config_write = client.put(f"/api/plugins/config/{first_name}", json={"config": config_payload["config"]})
    assert config_write.status_code == 200
    assert config_write.json()["ok"] is True


def test_plugin_select_endpoint() -> None:
    """Plugin select endpoint should switch active plugin."""
    client = TestClient(app)

    catalog = client.get("/api/plugins")
    names = [item["name"] for item in catalog.json()["available_plugins"]]
    assert "mock" in names

    response = client.post("/api/plugins/select", json={"plugin": "mock"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "switched to mock" in payload["message"]
