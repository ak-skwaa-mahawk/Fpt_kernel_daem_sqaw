"""
living_zero_core.py (Optimized & Hardened)
Core implementation: Ownership Tag Algebra + CA3 dynamics
"""

from __future__ import annotations
import math, hashlib
from typing import Dict, Optional, Tuple
import numpy as np

# ---------- Utilities ----------
def normalize(v: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    return v if n < eps else v / n

# ---------- Ownership Encoder & Projector ----------
class OwnershipEncoder:
    def __init__(self, d: int = 64):
        self.d = int(d)

    def _seed_from_raw(self, raw) -> int:
        h = hashlib.sha256(str(raw).encode("utf-8")).digest()
        return int.from_bytes(h[:8], byteorder="big")

    def encode(self, raw) -> np.ndarray:
        seed = self._seed_from_raw(raw)
        rng = np.random.default_rng(seed)
        v = rng.normal(size=(self.d,))
        return normalize(v)

class OwnershipProjector:
    def __init__(self, N: int, d: int = 64, seed: int = 0):
        self.N = int(N)
        self.d = int(d)
        if self.d > self.N:
            raise ValueError(f"Tag dimension d ({self.d}) cannot exceed state dimension N ({self.N})")

        rng = np.random.default_rng(seed)
        Q_random = rng.normal(size=(self.N, self.d))
        self.Q, _ = np.linalg.qr(Q_random, mode="reduced")

    def get_basis_vector(self, ownership_vector: np.ndarray) -> np.ndarray:
        w = self.Q @ ownership_vector
        return normalize(w)

    def projector(self, ownership_vector: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        w_hat = self.get_basis_vector(ownership_vector)
        Phi = np.outer(w_hat, w_hat)
        return Phi, w_hat

# ---------- Ownership-aware associative memory ----------
class OwnershipMemory:
    def __init__(self, N: int, ownership_projector: OwnershipProjector, eta=1e-3, gamma=1.0, weight_decay=0.0):
        self.N = int(N)
        self.Oproj = ownership_projector
        self.encoder = OwnershipEncoder(d=self.Oproj.d)
        self.W = np.zeros((self.N, self.N), dtype=float)
        self.eta = float(eta)
        self.gamma = float(gamma)
        self.weight_decay = float(weight_decay)
        self._tag_cache: Dict[str, np.ndarray] = {}

    def _get_w_hat(self, raw_tag) -> np.ndarray:
        tag_str = str(raw_tag)
        if tag_str not in self._tag_cache:
            u = self.encoder.encode(raw_tag)
            self._tag_cache[tag_str] = self.Oproj.get_basis_vector(u)
        return self._tag_cache[tag_str]

    def encode(self, s: np.ndarray, raw_tag=None):
        s = np.asarray(s, dtype=float)
        if raw_tag is None:
            v = s
        else:
            w_hat = self._get_w_hat(raw_tag)
            v = s + self.gamma * np.dot(w_hat, s) * w_hat

        Delta = self.eta * np.outer(v, v)
        self.W += Delta

        if self.weight_decay > 0.0:
            self.W *= (1.0 - self.weight_decay)

        self.W = 0.5 * (self.W + self.W.T)

    def recall_iter(self, x0: np.ndarray, steps: int = 10, bias_tag=None, beta: float = 0.0, activation=np.tanh) -> np.ndarray:
        x = np.array(x0, dtype=float)
        w_hat = self._get_w_hat(bias_tag) if (bias_tag is not None and beta != 0.0) else None

        for _ in range(steps):
            u = self.W @ x
            if w_hat is not None:
                u = u + beta * np.dot(w_hat, u) * w_hat
            x = activation(u)
        return x

    def selective_revoke(self, raw_tag, rho: float = 1.0):
        w_hat = self._get_w_hat(raw_tag)
        W_w = self.W @ w_hat
        w_W_w = float(np.dot(w_hat, W_w))

        self.W -= rho * (np.outer(W_w, w_hat) + np.outer(w_hat, W_w))
        self.W += (rho**2 * w_W_w) * np.outer(w_hat, w_hat)
        self.W = 0.5 * (self.W + self.W.T)

    def tag_similarity(self, raw_tag1, raw_tag2) -> float:
        w1 = self._get_w_hat(raw_tag1)
        w2 = self._get_w_hat(raw_tag2)
        return float(np.dot(w1, w2))**2

# ---------- CA3 Dynamics & Living Zero ----------
class CA3Dynamics:
    def __init__(self, N: int, memory: OwnershipMemory, tau: float = 0.1, dt: float = 0.01, alpha_max: float = 2.0):
        self.N = int(N)
        self.memory = memory
        self.tau = float(tau)
        self.dt = float(dt)
        self.alpha_max = float(alpha_max)
        self.alpha: Dict[int, float] = {}
        self.patterns: Dict[int, np.ndarray] = {}
        self.P: float = 0.0

    def energy_grad(self, x: np.ndarray) -> np.ndarray:
        grad = x.copy()
        for mu, alpha_mu in self.alpha.items():
            p = self.patterns[mu]
            grad -= alpha_mu * np.dot(p, x) * p
        return grad

    def step(self, x: np.ndarray, Vd: float = 1.0, R: float = 1.0, b: Optional[np.ndarray] = None, noise_std: float = 0.0) -> np.ndarray:
        g = float(Vd) * float(R)
        gradE = self.energy_grad(x)
        raw_drive = self.memory.W @ x if b is None else (self.memory.W @ x + b)
        drive = np.tanh(raw_drive)

        eta = np.random.normal(scale=noise_std, size=self.N) if noise_std > 0.0 else 0.0
        dx = (-gradE + g * drive + eta) * (self.dt / self.tau)
        return x + dx

    def encode_pattern(self, pid: int, p_vec: np.ndarray, strength: float = 0.1):
        self.patterns[pid] = normalize(p_vec)
        self.alpha[pid] = float(strength)

    def reward_handshake(
        self, x: np.ndarray, target_pid: int, eps: float = 0.03 * math.pi,
        R0: float = 1.0, kappa_r: float = 1e-2, kappa_P: float = 1e-2
    ) -> Tuple[bool, float, float]:
        p = self.patterns[target_pid]
        x_hat = normalize(x)
        dot = float(np.clip(np.dot(x_hat, p), -1.0, 1.0))
        theta = math.acos(dot)

        if theta <= eps:
            r = R0 * math.exp(-theta / eps)
            self.alpha[target_pid] = min(self.alpha_max, self.alpha[target_pid] + kappa_r * r)
            self.P += kappa_P * r
            return True, theta, r
        return False, theta, 0.0

def demo_small_run(seed=0):
    rng = np.random.default_rng(seed)
    N = 256
    d = 64
    Oproj = OwnershipProjector(N=N, d=d, seed=1)
    # Scale eta to balance recurrent drive against linear relaxation
    mem = OwnershipMemory(N=N, ownership_projector=Oproj, eta=0.8, gamma=2.0)
    ca3 = CA3Dynamics(N=N, memory=mem, tau=0.05, dt=0.01)

    p = normalize(rng.normal(size=(N,)))
    tag = "owner:collective"
    # Prime memory with the target attractor basin
    mem.encode(p, raw_tag=tag)
    ca3.encode_pattern(0, p, strength=1.2)

    x = normalize(p + 0.8 * rng.normal(size=(N,)))
    events = 0
    for _ in range(400):
        x = ca3.step(x, Vd=1.0, R=1.0, noise_std=0.01)
        trig, theta, r = ca3.reward_handshake(x, 0, eps=0.15 * math.pi)
        if trig:
            events += 1
            mem.encode(x, raw_tag=tag)
    return {"final_sim": float(np.dot(normalize(x), normalize(p))), "events": events}

if __name__ == "__main__":
    res = demo_small_run()
    print(f"Demo complete: final_similarity={res['final_sim']:.4f}, handshake_events={res['events']}")
