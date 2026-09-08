cat << 'EOF' > README.md
# Fpt_kernel_daem_sqaw

A homeostatic Feedback Processor Theory (FPT) daemon that acts as a closed-loop dynamic controller for [Admission Gate](https://github.com/ak-skwaa-mahawk/admission-gate).

## Dynamic Control Architecture

Rather than enforcing static rate limits, the daemon continuously measures runtime telemetry and applies non-linear damping to the admission gate's execution parameters.

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
python3 fpt_daemon.py

Telemetry Metrics

MetricDescription
FailRateRunning ratio of policy refusals and non-zero exit codes over sliding window W.
DampingSigmoidal response factor (0.0 \le \sigma \le 1.0) driving throttle intensity.
BurstClamped burst headroom dynamically scaled: \text{Burst}_{\text{clamped}} = \max(1, \text{Burst}_{\text{base}} \cdot (1 - 0.8\sigma)).
CooldownPenalty duration dynamically scaled: \text{Cooldown}_{\text{active}} = \text{Cooldown}_{\text{base}} \cdot (1 + 4.0\sigma).

EOF



