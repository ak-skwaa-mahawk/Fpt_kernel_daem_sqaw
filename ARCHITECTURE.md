# Architecture: Homeostatic Security via Feedback Processor Theory

## 1. Theoretical Grounding

Traditional computational security models rely on static boundaries: fixed access control lists, immutable rate limits, and deterministic syscall filters. In real-world multi-agent systems, operational errors, process hangs, and adversarial probing produce systemic drift.

**Feedback Processor Theory (FPT)** asserts that pure sequential policy logic degrades without an active observer and continuous state feedback. Security is not an immovable wall; it is a **homeostatic equilibrium** that stiffens under entropy and relaxes under stability.

┌────────────────────────────────────────────────────────┐
│                Agent Execution Request                 │
└──────────────────────────┬─────────────────────────────┘
│ ActionProposal
▼
┌────────────────────────────────────────────────────────┐
│                  fpt_kernel_daem_sqaw                  │
│                   (The FPT Observer)                   │
│                                                        │
│  [Sensor]    w_sec(1.0) | w_time(0.6) | w_proc(0.25)  │
│  [PID Plant] e_t = Penalty - Target                    │
│  [Damping]   σ(u_t) = Sigmoid(u_t)                     │
└──────────────┬───────────────────────────▲─────────────┘
│ Dynamic Actuation Bounds   │ Telemetry
▼                           │
┌──────────────────────────────────────────┴─────────────┐
│                     admission-gate                     │
│                   (The Security Plant)                 │
│                                                        │
│  • argv[0] Allow/Deny Resolution                       │
│  • Partitioned Read / Write Root Enforcement           │
│  • Burst Tokens & Tier Cooldown Enforcement            │
│  • Cryptographic Hash-Chain Audit Logging              │
└──────────────────────────┬─────────────────────────────┘
│ Subprocess Execution
▼
┌────────────────────────────────────────────────────────┐
│                     OS Environment                     │
└────────────────────────────────────────────────────────┘

## 2. Multi-Surface Actuation Spectrum

The daemon modulates four physical operational dimensions in `admission-gate` based on the sigmoidal damping factor $\sigma \in [0.0, 1.0]$:

$$\sigma(u_t) = \frac{1}{1 + e^{-(u_t - 0.4) \cdot 2.5}}$$

1. **Token Headroom & Cooldown Rates**:
   $$\text{Burst}_{\text{active}} = \max(1, \text{round}(\text{Burst}_{\text{base}} \cdot (1 - 0.8\sigma)))$$
   $$\text{Cooldown}_{\text{active}} = \text{Cooldown}_{\text{base}} \cdot (1 + 5.0\sigma)$$
2. **Process Execution Lifetimes**:
   $$\text{Timeout}_{\text{active}} = \max(2.0, \text{Timeout}_{\text{base}} \cdot (1 - 0.75\sigma))$$
3. **Autonomy Gating (Human-in-the-loop Fallback)**:
   $$\text{RequireConfirm} = \begin{cases} \text{true} & \text{if } \sigma > 0.85 \\ \text{false} & \text{otherwise} \end{cases}$$
4. **Filesystem Boundary Containment**:
   $$\text{WriteRoots} = \begin{cases} [\text{"./scratch"}] & \text{if } \sigma > 0.92 \\ [\text{"./workspace"}, \text{"./scratch"}] & \text{otherwise} \end{cases}$$

## 3. Sensor Classification

The observer isolates distinct failure modes to prevent benign operational errors (e.g., failed unit tests) from tripping catastrophic system containment:

* **Policy Refusal ($w = 1.0$)**: Subprocess denied before invocation (path escape, illegal binary). Immediate, sharp control escalation.
* **Execution Timeout ($w = 0.60$)**: Runaway process execution exceeding dynamic bounds.
* **Process Fault ($w = 0.25$)**: Subprocess returned exit code $\neq 0$. Gradual, mild backpressure.
* **Nominal Execution ($w = 0.0$)**: Error-free execution; decay back toward baseline equilibrium.

## 4. State Persistence

The controller continuously snapshots state to `~/.fpt_daemon_state.json` via atomic rename operations. If the daemon process is terminated or rebooted, it restores:
* Sliding window telemetry history ($W = 12$)
* Accumulated integral error state (with anti-windup clamping)
* Damping coefficient $\sigma$

This prevents "reboot-to-clear" exploits where an adversary intentionally crashes the supervisory daemon to reset its security constraints.
