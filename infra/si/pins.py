"""Inductance and capacitance of a connector's pin field.

The contacts of a pin-and-socket connector are short parallel conductors,
so their partial inductances follow from the geometry (Grover's formulas
for parallel filaments), and their mutual capacitances from the 2D
potential of parallel wires. With every pin in the netlist as a coupled
inductor, the ground pins are real return paths: a signal's loop
inductance, its coupling to its neighbours and the bounce of a card's
ground against the backplane's all come out of the same matrix, and depend
on where the ground pins are.

Lengths in metres. A pin field is a list of (x, y) positions.
"""

import numpy as np

MU0 = 4e-7 * np.pi
EPS0 = 8.8541878128e-12


def mutual(length, d):
    """Partial mutual inductance (H) of two parallel filaments of the same
    length, side by side, `d` apart (Grover)."""
    u = length / d
    return MU0 / (2 * np.pi) * length * (np.log(u + np.sqrt(1 + u * u)) - np.sqrt(1 + 1 / (u * u)) + 1 / u)


def self_partial(length, radius):
    """Partial self inductance (H) of a round conductor with its current at
    the surface (high frequency): the mutual inductance at a distance of
    its radius."""
    return mutual(length, radius)


def partial_matrix(positions, length, radius):
    """Partial inductance matrix (H) of parallel round contacts at the
    given positions."""
    p = np.asarray(positions, dtype=float)
    n = len(p)
    m = np.empty((n, n))
    for i in range(n):
        for j in range(n):
            m[i, j] = self_partial(length, radius) if i == j else mutual(length, np.hypot(*(p[i] - p[j])))
    return m


def loop_matrix(lp, signals, grounds):
    """Loop inductance matrix (H) of the signal contacts, each returning
    through the ground contacts, which are connected together at both ends
    and share the return current as their impedances decide."""
    s, g = list(signals), list(grounds)
    lss = lp[np.ix_(s, s)]
    lsg = lp[np.ix_(s, g)]
    lgg = lp[np.ix_(g, g)]
    ng = len(g)
    # ground currents ig for signal currents is: ground voltages equal (v_g)
    # and sum(ig) = -sum(is):  lgs·is + lgg·ig = v_g·1,  1ᵀig = -1ᵀis
    a = np.zeros((ng + 1, ng + 1))
    a[:ng, :ng] = lgg
    a[:ng, ng] = -1.0
    a[ng, :ng] = 1.0
    inv = np.linalg.inv(a)
    # for a unit current in each signal: ig and v_g
    rhs = np.zeros((ng + 1, len(s)))
    rhs[:ng, :] = -lsg.T
    rhs[ng, :] = -1.0
    sol = inv @ rhs
    ig, vg = sol[:ng, :], sol[ng, :]
    # loop voltage of signal k: (lss·is + lsg·ig)_k − v_g
    return lss + lsg @ ig - vg[None, :]


def coupling(lmat):
    """Coupling coefficients of an inductance matrix."""
    d = np.sqrt(np.diag(lmat))
    return lmat / np.outer(d, d)


def capacitance_matrix(positions, radius, grounds, er=1.0):
    """Maxwell capacitance matrix per unit length (F/m) of the non-ground
    wires among parallel round wires, the ground wires held at 0 V. Thin
    wires (each a line charge), in a uniform medium of permittivity er."""
    p = np.asarray(positions, dtype=float)
    n = len(p)
    d = np.hypot(p[:, None, 0] - p[None, :, 0], p[:, None, 1] - p[None, :, 1])
    np.fill_diagonal(d, radius)
    # potential coefficients, with a far reference circle of radius R: the
    # wire array is neutral once the grounds take up the charge, so R drops out
    big = 1.0
    pc = np.log(big / d) / (2 * np.pi * EPS0 * er)
    sig = [i for i in range(n) if i not in set(grounds)]
    gr = list(grounds)
    # charges q for signal voltages v_s, grounds at 0, total charge 0:
    # [P  1][q]   [v]
    # [1ᵀ 0][φ] = [0]   with φ the potential of the far reference
    a = np.zeros((n + 1, n + 1))
    a[:n, :n] = pc
    a[:n, n] = 1.0
    a[n, :n] = 1.0
    inv = np.linalg.inv(a)
    c = np.zeros((len(sig), len(sig)))
    for col, k in enumerate(sig):
        v = np.zeros(n + 1)
        v[k] = 1.0
        q = inv @ v
        c[:, col] = q[sig]
    return (c + c.T) / 2, sig
