"""Protocol model tests."""

from app.models.protocol import JointCommand


def test_joint_command_shape() -> None:
    """Joint command must include at least one value."""
    payload = JointCommand(arm="arm_a", target_angles_deg=[0, 1, 2, 3, 4, 5])
    assert len(payload.target_angles_deg) == 6
