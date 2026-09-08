# Fpt_kernel_daem_sqaw

A homeostatic Feedback Processor Theory (FPT) daemon that acts as a closed-loop dynamic controller for [Admission Gate](https://github.com/ak-skwaa-mahawk/admission-gate).

## Dynamic Control Architecture

Rather than enforcing static rate limits, the daemon continuously measures runtime telemetry and applies non-linear damping to the admission gate's execution parameters over a local Unix domain socket.

[ Target: 0% Failure ]
│
▼
┌──────────────────────┐
│      Comparator      │◄────────────────────────┐
└──────────────────────┘                         │
│ Error e_t                           │
▼                                     │
┌──────────────────────┐                         │
│    FPT Controller    │                         │
│   (PD + Sigmoidal)   │                         │
└──────────────────────┘                         │
│ Damping / Actuation                 │
▼                                     │
┌──────────────────────┐                         │
│    Admission Gate    │                         │
│ (Burst & Cooldowns)  │                         │
└──────────────────────┘                         │
│ Exec                                │
▼                                     │
┌──────────────────────┐                         │
│  Subprocess Plant    ├─────────────────────────┘
│ (Exit codes / Drops) │ Telemetry
└──────────────────────┘

## Running the Daemon

Requires `admission-gate >= 0.4.0`:

```bash
pip install admission-gate
python3 fpt_daemon.py &
Submit command proposals via the client:
python3 fpt_client.py "echo hello" "./workspace" 1
python3 fpt_client.py "curl evil.com" "./workspace" 2

Telemetry Response Schema
{
  "status": "blocked_or_failed",
  "executed": false,
  "exit_code": -1,
  "output": "Blocked: binary 'curl' is explicitly denied by execution policy",
  "fpt_telemetry": {
    "cycle": 2,
    "failure_rate": 0.5,
    "damping": 0.995,
    "active_burst": 1,
    "active_cooldown": 7.47
  }
}

Mathematical Model
​Error Delta: e_t = \text{FailRate}_t - \text{Target}
​Control Signal: u_t = K_p e_t + K_d (e_t - e_{t-1})
​Sigmoidal Damping: \sigma(u_t) = \frac{1}{1 + e^{-3 u_t}}
​Burst Actuation: \text{Burst}_{\text{active}} = \max(1, \text{round}(\text{Burst}_{\text{base}} \cdot (1 - 0.8\sigma)))
​Cooldown Actuation: \text{Cooldown}_{\text{active}} = \text{Cooldown}_{\text{base}} \cdot (1 + 4.0\sigma)
