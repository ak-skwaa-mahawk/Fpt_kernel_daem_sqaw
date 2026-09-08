#!/usr/bin/env python3
"""
Fpt_kernel_daem_sqaw
Homeostatic Feedback Processor Theory (FPT) daemon listening over a Unix socket.
Controls execution limits dynamically via Admission Gate using a multi-surface PID controller
with atomic state persistence, differentiated telemetry classification, and Living Zero CA3 handshake approval.
"""

import asyncio
import collections
import json
import math
import os
import signal
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from typing import Deque, Dict, List, Optional, Tuple
import numpy as np

from admission_gate import (
    ActionProposal,
    ExecConfig,
    GateConfig,
    ProcessConfig,
    RateLimitConfig,
    gated_shell,
)
from living_zero_core import CA3Dynamics, OwnershipEncoder, OwnershipMemory, OwnershipProjector, normalize

SOCKET_PATH = os.path.join(tempfile.gettempdir(), "fpt_kernel.sock")
STATE_PATH = os.path.join(os.path.expanduser("~"), ".fpt_daemon_state.json")

# Sensor weights
WEIGHT_POLICY_REFUSAL = 1.0     # Hard security boundary violation
WEIGHT_EXEC_TIMEOUT    = 0.60    # Subprocess hung / killed by timeout
WEIGHT_PROCESS_FAULT   = 0.25    # Operational non-zero exit code
WEIGHT_CLEAN_SUCCESS   = 0.0     # Nominal execution

@dataclass
class TelemetryEvent:
    timestamp: float
    category: str
    penalty: float

class FPTAdmissionController:
    def __init__(
        self,
        base_config: GateConfig,
        window_size: int = 12,
        target_penalty: float = 0.0,
        gain_p: float = 1.6,
        gain_i: float = 0.15,
        gain_d: float = 0.7,
        state_file: str = STATE_PATH,
    ):
        self.config = base_config
        self.window_size = window_size
        self.target = target_penalty
        self.state_file = state_file

        # PID Gains
        self.kp = gain_p
        self.ki = gain_i
        self.kd = gain_d

        # Internal State Registers
        self.history: Deque[TelemetryEvent] = collections.deque(maxlen=window_size)
        self.integral_error = 0.0
        self.last_error = 0.0
        self.last_timestamp = time.monotonic()
        self.cycle_count = 0
        self.current_damping = 0.50

        # Nominal Baselines
        self.base_burst = base_config.rate_limit.burst_threshold
        self.base_cooldown = base_config.rate_limit.tier3_cooldown_seconds
        self.base_timeout = base_config.process.timeout_seconds
        self.nominal_write_roots = list(base_config.write_roots)

        # Initialize Living Zero Handshake Engine (CA3 attractor)
        self.N = 128
        self.d = 32
        self.oproj = OwnershipProjector(N=self.N, d=self.d, seed=42)
        self.memory = OwnershipMemory(N=self.N, ownership_projector=self.oproj, eta=0.8, gamma=2.0)
        self.ca3 = CA3Dynamics(N=self.N, memory=self.memory, tau=0.05, dt=0.01)
        self.encoder = OwnershipEncoder(d=self.d)

        # Baseline Handshake Authority Anchor
        self.human_authority_tag = "authority:human_in_the_loop"
        u_auth = self.encoder.encode(self.human_authority_tag)
        self.authority_pattern = self.oproj.get_basis_vector(u_auth)
        self.memory.encode(self.authority_pattern, raw_tag=self.human_authority_tag)
        self.ca3.encode_pattern(pid=0, p_vec=self.authority_pattern, strength=1.5)

        self.load_state()

    def load_state(self):
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.cycle_count = data.get("cycle_count", 0)
            self.integral_error = float(data.get("integral_error", 0.0))
            self.last_error = float(data.get("last_error", 0.0))
            self.current_damping = float(data.get("damping", 0.50))
            for item in data.get("history", []):
                self.history.append(TelemetryEvent(
                    timestamp=item["timestamp"],
                    category=item["category"],
                    penalty=item["penalty"],
                ))
            self.actuate(self.current_damping)
            print(f"[FPT Daemon] Restored state: cycle={self.cycle_count}, damping={self.current_damping:.3f}")
        except Exception as e:
            print(f"[FPT Daemon] Warning: State restore failed: {e}")

    def save_state(self):
        try:
            temp_target = f"{self.state_file}.tmp"
            payload = {
                "cycle_count": self.cycle_count,
                "integral_error": self.integral_error,
                "last_error": self.last_error,
                "damping": self.current_damping,
                "history": [asdict(ev) for ev in self.history],
                "saved_at": time.time(),
            }
            with open(temp_target, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(temp_target, self.state_file)
        except Exception as e:
            print(f"[FPT Daemon] Error saving state: {e}")

    def verify_handshake(self, token_str: Optional[str]) -> bool:
        """
        Validates an out-of-band authorization token against the CA3 dynamical attractor.
        """
        if not token_str:
            return False
        try:
            # Token format: hex-encoded vector or signed seed
            u = self.encoder.encode(token_str)
            w_hat = self.oproj.get_basis_vector(u)
            trig, theta, r = self.ca3.reward_handshake(w_hat, target_pid=0, eps=0.35 * math.pi)
            return trig
        except Exception:
            return False

    def observe(self, executed: bool, exit_code: int, raw_output: str) -> Tuple[str, float]:
        now = time.time()
        if not executed:
            category = "policy_block"
            penalty = WEIGHT_POLICY_REFUSAL
        elif exit_code in (124, -9) or "timed out" in raw_output.lower():
            category = "timeout"
            penalty = WEIGHT_EXEC_TIMEOUT
        elif exit_code != 0:
            category = "proc_error"
            penalty = WEIGHT_PROCESS_FAULT
        else:
            category = "nominal"
            penalty = WEIGHT_CLEAN_SUCCESS

        self.history.append(TelemetryEvent(timestamp=now, category=category, penalty=penalty))
        running_penalty = sum(ev.penalty for ev in self.history) / len(self.history)
        return category, running_penalty

    def compute_damping(self, current_penalty: float) -> Tuple[float, float, float, float, float]:
        now = time.monotonic()
        dt = max(0.05, now - self.last_timestamp)
        self.last_timestamp = now

        error = current_penalty - self.target
        self.integral_error = max(-1.0, min(1.0, self.integral_error + (error * 0.1)))

        if self.cycle_count <= 1:
            d_error = 0.0
        else:
            d_error = max(-2.0, min(2.0, (error - self.last_error) / dt))
        self.last_error = error

        control_signal = (self.kp * error) + (self.ki * self.integral_error) + (self.kd * d_error)
        damping = 1.0 / (1.0 + math.exp(-(control_signal - 0.4) * 2.5))
        self.current_damping = damping
        return error, self.integral_error, d_error, control_signal, damping

    def actuate(self, damping: float) -> Dict:
        active_burst = max(1, int(round(self.base_burst * (1.0 - (0.8 * damping)))))
        active_cooldown = self.base_cooldown * (1.0 + (5.0 * damping))
        self.config.rate_limit.burst_threshold = active_burst
        self.config.rate_limit.tier3_cooldown_seconds = active_cooldown

        active_timeout = max(2.0, self.base_timeout * (1.0 - (0.75 * damping)))
        self.config.process.timeout_seconds = active_timeout

        require_confirm = damping > 0.85
        self.config.require_confirm = require_confirm

        if damping > 0.92:
            active_write_roots = [p for p in self.nominal_write_roots if "scratch" in p]
            if not active_write_roots:
                active_write_roots = ["./scratch"]
        else:
            active_write_roots = list(self.nominal_write_roots)
        self.config.write_roots = active_write_roots

        return {
            "active_burst": active_burst,
            "active_cooldown_sec": round(active_cooldown, 2),
            "active_timeout_sec": round(active_timeout, 2),
            "require_confirm": require_confirm,
            "active_write_roots": active_write_roots,
        }

    def step(self, proposal: ActionProposal, approval_token: Optional[str] = None) -> Tuple[bool, str, int, Dict]:
        self.cycle_count += 1

        # Check if high damping requires confirmation
        if self.config.require_confirm:
            authorized = self.verify_handshake(approval_token)
            if not authorized:
                # Challenge issued back to client/human
                category, observed_penalty = self.observe(False, -1, "Confirmation required: awaiting Human_inthe_loop token")
                error, i_err, d_err, u_sig, damping = self.compute_damping(observed_penalty)
                actuation = self.actuate(damping)
                self.save_state()
                telemetry = {
                    "cycle": self.cycle_count,
                    "event_category": "challenge_pending",
                    "observed_penalty": round(observed_penalty, 3),
                    "damping": round(damping, 3),
                    "actuation": actuation,
                    "challenge": {
                        "action_id": proposal.action_id,
                        "command": proposal.command,
                        "required_authority": self.human_authority_tag,
                    }
                }
                return False, "E_CHALLENGE_REQUIRED: Provide Human_inthe_loop handshake token", -1, telemetry

            # Single-shot authorization override for this cycle
            self.config.require_confirm = False

        executed, result, exit_code = gated_shell(proposal, config=self.config)
        category, observed_penalty = self.observe(executed, exit_code, result)
        error, i_err, d_err, u_sig, damping = self.compute_damping(observed_penalty)
        actuation = self.actuate(damping)

        self.save_state()

        telemetry = {
            "cycle": self.cycle_count,
            "event_category": category,
            "observed_penalty": round(observed_penalty, 3),
            "control_signal": round(u_sig, 3),
            "damping": round(damping, 3),
            "actuation": actuation,
        }

        return executed, result, exit_code, telemetry


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, controller: FPTAdmissionController):
    data = await reader.readline()
    if not data:
        writer.close()
        await writer.wait_closed()
        return

    try:
        req = json.loads(data.decode("utf-8"))
        proposal = ActionProposal(
            action_id=req.get("action_id", "anon"),
            command=req["command"],
            target_path=req.get("target_path", "./workspace"),
            risk_tier=int(req.get("risk_tier", 1)),
        )
        approval_token = req.get("approval_token")

        executed, result, exit_code, telemetry = controller.step(proposal, approval_token)

        response = {
            "status": "ok" if executed and exit_code == 0 else "blocked_or_failed",
            "executed": executed,
            "exit_code": exit_code,
            "output": result.strip(),
            "fpt_telemetry": telemetry,
        }
    except Exception as e:
        response = {"status": "error", "error": str(e)}

    writer.write((json.dumps(response) + "\n").encode("utf-8"))
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def main():
    if os.path.exists(SOCKET_PATH):
        try:
            os.remove(SOCKET_PATH)
        except OSError:
            pass

    os.makedirs("./repo", exist_ok=True)
    os.makedirs("./workspace", exist_ok=True)
    os.makedirs("./scratch", exist_ok=True)

    config = GateConfig(
        read_roots=["./repo"],
        write_roots=["./workspace", "./scratch"],
        require_confirm=False,
        exec_policy=ExecConfig(
            allow=["echo", "ls", "python", "python3", "git", "cat", "touch", "pytest", "sleep"],
            deny=["curl", "wget", "ssh", "nc", "bash", "sh", "sudo"],
        ),
        rate_limit=RateLimitConfig(
            enabled=True,
            max_requests_per_minute=60,
            burst_threshold=5,
            tier3_cooldown_seconds=1.5,
        ),
        process=ProcessConfig(timeout_seconds=12.0, scrub_env=True),
    )

    controller = FPTAdmissionController(config)
    server = await asyncio.start_unix_server(
        lambda r, w: handle_client(r, w, controller),
        path=SOCKET_PATH,
    )
    print(f"[FPT Daemon] Online. CA3-governed PID running on {SOCKET_PATH}")

    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set_result, None)

    await stop
    print("\n[FPT Daemon] Shutting down...")
    server.close()
    await server.wait_closed()
    if os.path.exists(SOCKET_PATH):
        try:
            os.remove(SOCKET_PATH)
        except OSError:
            pass

def run():
    asyncio.run(main())

if __name__ == "__main__":
    run()
