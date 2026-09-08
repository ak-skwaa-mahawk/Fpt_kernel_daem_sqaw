Control-Theoretic Note: Stability, Anti-Windup Bounds, and Sigmoidal Actuation
System Component: Fpt_kernel_daem_sqaw (The Living Territory / Damping Regulator)
Target Invariants: Bounded Input Bounded State (BIBS), Anti-Windup Invariance, Finite Damping Bounds \sigma_k \in (0, 1), Monotonic Actuator Saturation.
1. Dynamical System Formulation
The admission controller samples telemetry events over discrete decision epochs k \in \mathbb{N}. Let p_k \in [0, 1] denote the aggregate policy error penalty at epoch k, where p_k = 0 denotes a clean nominal execution and p_k = 1 denotes a boundary violation, unhandled fault, or blocked action.
With setpoint r = 0, the instantaneous tracking error is:

The control signal u_k is governed by a discrete-time proportional-integral-derivative (PID) filter:

The raw control signal u_k is projected onto the damping factor \sigma_k via a generalized logistic activation function:


where \alpha > 0 represents sensitivity gain and u_0 defines the nominal inflection threshold.
2. Integral Accumulator and Anti-Windup Clamping
To prevent integration windup under sustained adversarial bursts (e_k = 1, \, \forall k), the integrator state I_k is updated via a leaky accumulator with a hard saturation clamp:
where \gamma \in (0, 1) is the memory decay constant, \Delta t is the epoch interval, and the saturation operator is defined as:

Invariant 1 (Integral Boundedness)
For any arbitrary sequence of error penalties \{e_k\}_{k=0}^\infty with e_k \in [0, 1], the integrator state remains uniformly bounded:

Proof:
Immediate from the definition of \mathrm{sat}_{[-I_{\max}, I_{\max}]}(\cdot). Even if \gamma = 1 and e_k = 1 persistently, I_k cannot exceed I_{\max}, precluding integrator windup. \blacksquare
3. State Space Boundedness (BIBS Stability)
Theorem 1 (Bounded Control Effort)
Given e_k \in [0, 1], \vert{}I_k\vert{} \le I_{\max}, and finite gains (K_p, K_i, K_d) \in \mathbb{R}_{>0}^3, the control signal u_k is bounded in a compact interval [u_{\min}, u_{\max}] for all k \ge 1:

Proof:
Evaluating extrema across the admissible inputs:


Summing the individual maximal terms:


Thus, u_k \in [u_{\min}, u_{\max}] for all k. \blacksquare
Corollary 1.1 (Damping Bounds)
The damping factor \sigma_k = S(u_k) satisfies:


Because u_{\min} > -\infty and u_{\max} < \infty, the open interval bounds hold strictly:


The system cannot degenerate into \sigma_k = 0 (unbounded free run) or \sigma_k = 1 (irreversible singularity).
4. Discrete Lyapunov Stability Under Nominal Relaxation
Consider the autonomous relaxation regime where no further policy violations occur (e_k = 0 for all k \ge k_0). Let the state vector be x_k = [I_k, \, e_{k-1}]^T. For k \ge k_0, e_k = 0, giving:

Define the quadratic Lyapunov candidate function:


Clearly, V(x_k) > 0 for all I_k \ne 0, and V(0) = 0.
Computing the forward difference \Delta V(x_k) = V(x_{k+1}) - V(x_k):

Since \gamma \in (0, 1), (\gamma^2 - 1) < 0. Therefore:

The unforced error accumulator is exponentially stable and converges asymptotically to the origin I^* = 0. Consequently, the steady-state control signal relaxes to:

5. Actuation Saturation Mapping
The physical actuators map the continuous damping metric \sigma_k to concrete execution constraints:
| Actuation Variable | Mapping Function | Physical Bounds |
|---|---|---|
| Burst Allowance (B_k) | \max\left(1, \text{round}\left(B_{\text{base}} \cdot (1 - 0.8 \sigma_k)\right)\right) | [1, B_{\text{base}}] |
| Cooldown Sec (\tau_{\text{cool}}) | \tau_{\min} + (\tau_{\max} - \tau_{\min})\sigma_k | [\tau_{\min}, \tau_{\max}] |
| Timeout Sec (\tau_{\text{exec}}) | \tau_{\text{exec,base}} \cdot (1.0 - 0.7 \sigma_k) | [0.3 \tau_{\text{base}}, \tau_{\text{base}}] |
| Sovereign Confirm | \mathbf{1}_{(\sigma_k > 0.85)} | \{\text{False}, \text{True}\} |
| Write Isolation | \mathbf{1}_{(\sigma_k > 0.92)} \implies \text{Roots} = \{\text{"./scratch"}\} | Restrictive Root Set |
Because \sigma_k \in [\sigma_{\min}, \sigma_{\max}] \subset (0, 1), every derived actuation variable remains within strict operational limits. Under worst-case adversarial bombardment, execution burst contracts to 1, timeouts reduce to safe non-zero floors, and execution halts at the out-of-band clearance boundary without runtime panic or arithmetic overflow.
