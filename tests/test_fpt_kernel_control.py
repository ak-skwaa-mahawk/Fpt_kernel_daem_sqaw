import json
import math
import pytest
from fpt_daemon import FPTController

def test_pid_damping_bounds():
    ctrl = FPTController()
    
    # Under zero error, damping should sit well below escalation threshold
    err, i_err, d_err, u_sig, damping = ctrl.compute_damping(0.0)
    assert 0.0 <= damping <= 0.60
    assert not ctrl.actuate(damping)["require_confirm"]

    # Under maximum penalty, control signal spikes and damping exceeds escalation ceiling
    for _ in range(4):
        err, i_err, d_err, u_sig, damping = ctrl.compute_damping(1.0)
    
    assert damping > 0.85
    actuation = ctrl.actuate(damping)
    assert actuation["require_confirm"] is True
    assert actuation["active_burst"] == 1
    assert actuation["active_cooldown_sec"] > 5.0

def test_quarantine_activation():
    ctrl = FPTController()
    # Force extreme damping
    actuation = ctrl.actuate(0.95)
    assert actuation["active_write_roots"] == ["./scratch"]

def test_handshake_sovereign_clearance():
    ctrl = FPTController()
    
    # Plain text matching authority pattern
    assert ctrl.verify_handshake("authority:human_in_the_loop") is True
    assert ctrl.verify_handshake("random_untrusted_token") is False

    # Structured Nullrose JSON token
    valid_token = json.dumps({
        "protocol_version": "v1.0",
        "sovereign_id": "99733-Q",
        "authority_tag": "authority:human_in_the_loop"
    })
    assert ctrl.verify_handshake(valid_token) is True
