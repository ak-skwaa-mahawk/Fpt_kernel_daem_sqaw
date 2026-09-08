# Fpt_kernel_daem_sqaw

A homeostatic Feedback Processor Theory (FPT) daemon that acts as a closed-loop dynamic controller for [Admission Gate](https://github.com/ak-skwaa-mahawk/admission-gate).

## Architecture

The daemon operates as an async Unix domain socket server, continuously sampling telemetry from gated executions and modulating admission limits across multiple operational surfaces via a tuned PID controller with sigmoidal damping.

[ Target Penalty: 0.0 ]
│
▼
┌──────────────────────┐
│      Comparator      │◄────────────────────────┐
└──────────────────────┘                         │
│ Error e_t                           │
▼                                     │
┌──────────────────────┐                         │
│    PID Controller    │                         │
│  (Anti-windup + D)   │                         │
└──────────────────────┘                         │
│ Control Signal u_t                  │
▼                                     │
┌──────────────────────┐                         │
│  Sigmoidal Damping   │                         │
│   Factor σ(u_t)      │                         │
└──────────────────────┘                         │
│ Multi-Surface Actuation             │
▼                                     │
┌──────────────────────┐                         │
│    Admission Gate    │                         │
│ • Burst / Cooldown   │                         │
│ • Execution Timeout  │                         │
│ • Autonomy Gate      │                         │
│ • Write Root Bounds  │                         │
└──────────────────────┘                         │
│ Subprocess Exec                     │
▼                                     │
┌──────────────────────┐                         │
│  Telemetry Observer  ├─────────────────────────┘
│  (Weighted Penalty)  │
└──────────────────────┘

## Running the Daemon

Requires `admission-gate >= 0.4.0`:

```bash
pip install admission-gate
python3 fpt_daemon.py &
Submit command proposals via the client:
python3 fpt_client.py "echo nominal" "./workspace" 1
python3 fpt_client.py "python3 -c 'import sys; sys.exit(1)'" "./workspace" 1
python3 fpt_client.py "curl evil.com" "./workspace" 2

Multi-Surface Actuation Spectrum
Telemetry StatePenaltyDamping (\sigma)BurstCooldownTimeoutAutonomyWrite Roots
Nominal0.0~0.503~5.2s9.75sUnrestrictedworkspace, scratch
Operational Error0.25~0.642~6.3s8.30sUnrestrictedworkspace, scratch
Security Refusal1.00>0.851>7.8s<6.0sUnrestrictedworkspace, scratch
Sustained Attack>0.75>0.941>10.0s2.00sManual Confirmationscratch (quarantined)
Sensor Weighting
​Hard Security Boundary (Refusal): 1.0
​Process Timeout / SIGKILL: 0.6
​Subprocess Non-Zero Exit: 0.25
​Clean Exit: 0.0
