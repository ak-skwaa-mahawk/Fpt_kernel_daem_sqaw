#!/usr/bin/env python3
"""
Fpt_kernel_daem_sqaw
A homeostatic Feedback Processor Theory (FPT) daemon listening over a Unix socket.
Controls execution limits dynamically via Admission Gate using a multi-surface PID controller.
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
from dataclasses import dataclass
from typing import Deque, Dict, List, Tuple

from admission_gate import (
    ActionProposal,
    ExecConfig,
    GateConfig,
    ProcessConfig,
    RateLimitConfig,
    gated_shell,
)

SOCKET_PATH = os.path.join(tempfile.gettempdir(), "fpt_kernel.sock")

@dataclass
class FPTState:
    cycle: int
    observed_penalty: float
    running_error: float
    integral_error: float
    derivative_error: float
    control_signal: float
    damping_factor: float
    active_burst: int
    active_cooldown: float
    active_timeout: float
    require_confirm: bool
    active_write_roots: List[str]


class FPTAdmissionController:
    def __init__(
        self,
        base_config: GateConfig,
        window_size: int = 10,
        target_penalty: float = 0.0,
        gain_p: float = 1.2,
        gain_i: float = 0.1,
        gain_d: float = 0.5,
    ):
        self.config = base_config
        self.window_size = window_size
        self.target = target_penalty

        # PID Gains
        self.kp = gain_p
        self.ki = gain_i
        self.kd = gain_d

        # Internal State
        self.history: Deque[float] = collections.deque(maxlen=window_size)
        self.integral_error = 0.0
        self.last_error = 0.0
        self.last_timestamp = time.monotonic()
        self.cycle_count = 0

        # Baseline Parameters
        self.base_burst = base_config.rate_limit.burst_threshold
        self.base_cooldown = base_config.rate_limit.tier3_cooldown_seconds
        self.base_timeout = base_config.process.timeout_seconds
        self.nominal_write_roots = list(base_config.write_roots)

    def observe(self, executed: bool, exit_code: int) -> float:
        """
        Differentiated Weighted Sensor:
        - Security boundary refusal (hard violation): 1.0
        - Timeout / SIGKILL: 0.6
        - Non-zero subprocess exit (operational error): 0.25
        - Clean execution: 0.0
        """
        if not executed:
            penalty = 1.0
        elif exit_code in (124, -9):
            penalty = 0.6
        elif exit_code != 0:
            penalty = 0.25
        else:
            penalty = 0.0

        self.history.append(penalty)
        return sum(self.history) / len(self.history)

    def compute_damping(self, current_penalty: float) -> Tuple[float, float, float, float, float]:
        now = time.monotonic()
        dt = max(1e-3, now - self.last_timestamp)
        self.last_timestamp = now

        error = current_penalty - self.target

        # Discrete integral with anti-windup clamping
        self.integral_error = max(-1.0, min(1.0, self.integral_error + error))
        d_error = error - self.last_error
        self.last_error = error

        control_signal = (self.kp * error) + (self.ki * self.integral_error) + (self.kd * d_error)

        # Sigmoidal non-linear damping: maps control signal to [0.0, 1.0]
        damping = 1.0 / (1.0 + math.exp(-control_signal * 2.5))
        return error, self.integral_error, d_error, control_signal, damping

    def actuate(self, damping: float) -> Tuple[int, float, float, bool, List[str]]:
        # 1. Rate Limiting Actuation
        active_burst = max(1, int(round(self.base_burst * (1.0 - (0.8 * damping)))))
        active_cooldown = self.base_cooldown * (1.0 + (5.0 * damping))

        self.config.rate_limit.burst_threshold = active_burst
        self.config.rate_limit.tier3_cooldown_seconds = active_cooldown

        # 2. Process Lifecycle Actuation
        active_timeout = max(2.0, self.base_timeout * (1.0 - (0.7 * damping)))
        self.config.process.timeout_seconds = active_timeout

        # 3. Autonomy Gate Actuation (Human-in-the-loop fallback)
        require_confirm = damping > 0.88
        self.config.require_confirm = require_confirm

        # 4. Filesystem Boundary Containment Actuation
        if damping > 0.94:
            # Under critical stress, revoke main workspace mutation rights, isolate to scratch
            active_write_roots = [p for p in self.nominal_write_roots if "scratch" in p]
            if not active_write_roots:
                active_write_roots = ["./scratch"]
        else:
            active_write_roots = list(self.nominal_write_roots)

        self.config.write_roots = active_write_roots

        return active_burst, active_cooldown, active_timeout, require_confirm, active_write_roots

    def step(self, proposal: ActionProposal) -> Tuple[bool, str, int, FPTState]:
        self.cycle_count += 1

        executed, result, exit_code = gated_shell(proposal, config=self.config)
        observed_penalty = self.observe(executed, exit_code)
        error, i_err, d_err, u_sig, damping = self.compute_damping(observed_penalty)
        burst, cooldown, timeout, confirm, write_roots = self.actuate(damping)

        state = FPTState(
            cycle=self.cycle_count,
            observed_penalty=observed_penalty,
            running_error=error,
            integral_error=i_err,
            derivative_error=d_err,
            control_signal=u_sig,
            damping_factor=damping,
            active_burst=burst,
            active_cooldown=round(cooldown, 2),
            active_timeout=round(timeout, 2),
            require_confirm=confirm,
            active_write_roots=write_roots,
        )

        return executed, result, exit_code, state


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

        executed, result, exit_code, fpt = controller.step(proposal)

        response = {
            "status": "ok" if executed and exit_code == 0 else "blocked_or_failed",
            "executed": executed,
            "exit_code": exit_code,
            "output": result.strip(),
            "fpt_telemetry": {
                "cycle": fpt.cycle,
                "observed_penalty": round(fpt.observed_penalty, 3),
                "control_signal": round(fpt.control_signal, 3),
                "damping": round(fpt.damping_factor, 3),
                "actuation": {
                    "active_burst": fpt.active_burst,
                    "active_cooldown_sec": fpt.active_cooldown,
                    "active_timeout_sec": fpt.active_timeout,
                    "require_confirm": fpt.require_confirm,
                    "write_roots": fpt.active_write_roots,
                },
            },
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
            allow=["echo", "ls", "python", "python3", "git", "cat", "touch", "pytest"],
            deny=["curl", "wget", "ssh", "nc", "bash", "sh", "sudo"],
        ),
        rate_limit=RateLimitConfig(
            enabled=True,
            max_requests_per_minute=60,
            burst_threshold=5,
            tier3_cooldown_seconds=1.5,
        ),
        process=ProcessConfig(timeout_seconds=15.0, scrub_env=True),
    )

    controller = FPTAdmissionController(config)
    server = await asyncio.start_unix_server(
        lambda r, w: handle_client(r, w, controller),
        path=SOCKET_PATH,
    )
    print(f"[FPT Daemon] Online. Multi-surface PID active on {SOCKET_PATH}")

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


if __name__ == "__main__":
    asyncio.run(main())
