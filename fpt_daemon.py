#!/usr/bin/env python3
"""
Fpt_kernel_daem_sqaw
A homeostatic Feedback Processor Theory (FPT) daemon listening over a Unix socket.
Controls execution limits dynamically via Admission Gate.
"""

import asyncio
import collections
import json
import math
import os
import signal
import sys
from dataclasses import dataclass
from typing import Deque, Tuple

from admission_gate import (
    ActionProposal,
    ExecConfig,
    GateConfig,
    ProcessConfig,
    RateLimitConfig,
    gated_shell,
)

import tempfile
SOCKET_PATH = os.path.join(tempfile.gettempdir(), "fpt_kernel.sock")

@dataclass
class FPTState:
    cycle: int
    observed_failure_rate: float
    error: float
    damping_factor: float
    active_burst: int
    active_cooldown: float

class FPTAdmissionController:
    def __init__(
        self,
        base_config: GateConfig,
        window_size: int = 8,
        target_failure_rate: float = 0.0,
        gain_p: float = 2.5,
        gain_d: float = 1.0,
    ):
        self.config = base_config
        self.window_size = window_size
        self.target = target_failure_rate
        self.kp = gain_p
        self.kd = gain_d

        self.history: Deque[int] = collections.deque(maxlen=window_size)
        self.last_error = 0.0
        self.cycle_count = 0

        self.base_burst = base_config.rate_limit.burst_threshold
        self.base_cooldown = base_config.rate_limit.tier3_cooldown_seconds

    def observe(self, executed: bool, exit_code: int) -> float:
        failed = 1 if (not executed or exit_code != 0) else 0
        self.history.append(failed)
        return sum(self.history) / len(self.history)

    def compute_damping(self, current_failure_rate: float) -> Tuple[float, int, float]:
        error = current_failure_rate - self.target
        d_error = error - self.last_error
        self.last_error = error

        control_signal = (self.kp * error) + (self.kd * d_error)
        damping = 1.0 / (1.0 + math.exp(-control_signal * 3.0))

        clamped_burst = max(1, int(round(self.base_burst * (1.0 - (0.8 * damping)))))
        clamped_cooldown = self.base_cooldown * (1.0 + (4.0 * damping))

        return damping, clamped_burst, clamped_cooldown

    def step(self, proposal: ActionProposal) -> Tuple[bool, str, int, FPTState]:
        self.cycle_count += 1

        executed, result, exit_code = gated_shell(proposal, config=self.config)
        failure_rate = self.observe(executed, exit_code)
        damping, new_burst, new_cooldown = self.compute_damping(failure_rate)

        # Actuation: update running GateConfig
        self.config.rate_limit.burst_threshold = new_burst
        self.config.rate_limit.tier3_cooldown_seconds = new_cooldown

        state = FPTState(
            cycle=self.cycle_count,
            observed_failure_rate=failure_rate,
            error=failure_rate - self.target,
            damping_factor=damping,
            active_burst=new_burst,
            active_cooldown=round(new_cooldown, 2),
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
                "failure_rate": round(fpt.observed_failure_rate, 3),
                "damping": round(fpt.damping_factor, 3),
                "active_burst": fpt.active_burst,
                "active_cooldown": fpt.active_cooldown,
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
        os.remove(SOCKET_PATH)

    os.makedirs("./repo", exist_ok=True)
    os.makedirs("./workspace", exist_ok=True)

    config = GateConfig(
        read_roots=["./repo"],
        write_roots=["./workspace"],
        require_confirm=False,
        exec_policy=ExecConfig(
            allow=["echo", "ls", "python", "python3", "git", "cat", "touch"],
            deny=["curl", "wget", "ssh", "nc", "bash", "sh"],
        ),
        rate_limit=RateLimitConfig(
            enabled=True,
            max_requests_per_minute=60,
            burst_threshold=5,
            tier3_cooldown_seconds=1.5,
        ),
        process=ProcessConfig(timeout_seconds=10.0, scrub_env=True),
    )

    controller = FPTAdmissionController(config)
    server = await asyncio.start_unix_server(
        lambda r, w: handle_client(r, w, controller),
        path=SOCKET_PATH,
    )
    print(f"[FPT Daemon] Online. Listening on {SOCKET_PATH}")

    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set_result, None)

    await stop
    print("\n[FPT Daemon] Shutting down...")
    server.close()
    await server.wait_closed()
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

if __name__ == "__main__":
    asyncio.run(main())
