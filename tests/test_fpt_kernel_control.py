import json
import math
import pytest
from admission_gate import GateConfig
from fpt_daemon import FPTAdmissionController

@pytest.fixture
def controller(tmp_path):
    test_state_file = str(tmp_path / "test_state.json")
    config = GateConfig()
    ctrl = FPTAdmissionController(base_config=config)
    
    # Isolate state persistence to the pytest temp path
    if hasattr(ctrl, "state_file"):
        ctrl.state_file = test_state_file
    elif hasattr(ctrl, "state_path"):
        ctrl.state_path = test_state_file
    
    # Zero out in-memory state to ensure isolation
    ctrl.cycle_count = 0
    ctrl.integral_err = 0.0
    ctrl.last_err = 0.0
    if hasattr(ctrl, "penalties"):
        ctrl.penalties.clear()
        
    return ctrl

def test_pid_damping_bounds(controller):
    # Under zero error, damping remains well below escalation threshold
    err, i_err, d_err, u_sig, damping = controller.compute_damping(0.0)
    assert 0.0 <= damping <= 0.60
    assert not controller.actuate(damping)["require_confirm"]

    # Sustained maximum penalty: drive damping into escalation ceiling
    for _ in range(8):
        err, i_err, d_err, u_sig, damping = controller.compute_damping(1.0)

    assert damping > 0.85
    actuation = controller.actuate(damping)
    assert actuation["require_confirm"] is True
    assert actuation["active_burst"] <= 2
    assert actuation["active_cooldown_sec"] > 5.0

def test_quarantine_activation(controller):
    actuation = controller.actuate(0.95)
    assert actuation["active_write_roots"] == ["./scratch"]

def test_handshake_sovereign_clearance(controller):
    assert controller.verify_handshake("authority:human_in_the_loop") is True
    assert controller.verify_handshake("random_untrusted_token") is False

    valid_token = json.dumps({
        "protocol_version": "v1.0",
        "sovereign_id": "99733-Q",
        "authority_tag": "authority:human_in_the_loop"
    })
    assert controller.verify_handshake(valid_token) is True
