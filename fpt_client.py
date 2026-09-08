#!/usr/bin/env python3
import json
import os
import socket
import sys
import tempfile

SOCKET_PATH = os.path.join(tempfile.gettempdir(), "fpt_kernel.sock")

def submit(cmd: str, target_path: str = "./workspace", tier: int = 1, token: str = None):
    payload = {
        "action_id": f"cli-{sys.argv[1] if len(sys.argv) > 1 else 'run'}",
        "command": cmd,
        "target_path": target_path,
        "risk_tier": tier,
        "approval_token": token,
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(SOCKET_PATH)
        s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        res = s.makefile().readline()
    print(json.dumps(json.loads(res), indent=2))

def submit_cli():
    if len(sys.argv) < 2:
        print("Usage: fpt-client <command> [target_path] [tier] [approval_token]")
        sys.exit(1)
    target = sys.argv[2] if len(sys.argv) > 2 else "./workspace"
    tier = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    token = sys.argv[4] if len(sys.argv) > 4 else None
    submit(sys.argv[1], target, tier, token)

if __name__ == "__main__":
    submit_cli()
