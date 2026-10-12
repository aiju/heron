"""A small 2D field solver for the per-length L and C of coupled microstrip.

Finite differences on a square grid over the cross-section: a ground plane
at the bottom, a dielectric layer of height h, rectangular traces on top of
it, air above, a grounded lid far away and zero-flux sides. For each trace
at 1 V (others at 0) the charge on every conductor gives a column of the
capacitance matrix. Doing it once with the dielectric and once in vacuum
gives L = μ0·ε0·C0⁻¹.
"""

import numpy as np

EPS0 = 8.8541878128e-12
C_LIGHT = 299792458.0


def _cg(apply, b, x0, tol=1e-9, maxit=20000):
    x = x0.copy()
    r = b - apply(x)
    p = r.copy()
    rr = np.vdot(r, r)
    nb = np.sqrt(np.vdot(b, b)) or 1.0
    for _ in range(maxit):
        ap = apply(p)
        a = rr / np.vdot(p, ap)
        x += a * p
        r -= a * ap
        rr2 = np.vdot(r, r)
        if np.sqrt(rr2) < tol * nb:
            break
        p = r + (rr2 / rr) * p
        rr = rr2
    return x


def capacitance(w, t, h, pitch, n, er, d=10e-6, air=2.5e-3, margin=2.5e-3, er_cells=None):
    """Capacitance matrix (F/m) of n traces of width w, thickness t, at the
    given pitch, on a dielectric of height h and relative permittivity er
    (er=1 for vacuum) over a ground plane."""
    width = (n - 1) * pitch + w + 2 * margin
    nx = int(round(width / d)) + 1
    jh = int(round(h / d))
    jt = max(1, int(round(t / d)))
    ny = jh + jt + int(round(air / d)) + 1
    # permittivity of each cell (between nodes): (nx-1) x (ny-1)
    ec = np.ones((nx - 1, ny - 1))
    ec[:, :jh] = er
    # edge permittivities: horizontal edges (i,j)-(i+1,j) and vertical (i,j)-(i,j+1)
    ex = np.ones((nx - 1, ny))
    ex[:, 1:-1] = 0.5 * (ec[:, :-1] + ec[:, 1:])
    ex[:, 0] = ec[:, 0]
    ex[:, -1] = ec[:, -1]
    ey = np.ones((nx, ny - 1))
    ey[1:-1, :] = 0.5 * (ec[:-1, :] + ec[1:, :])
    ey[0, :] = ec[0, :]
    ey[-1, :] = ec[-1, :]

    cond = np.full((nx, ny), -1, dtype=int)     # -1 free, -2 ground, k trace k
    cond[:, 0] = -2
    cond[:, -1] = -2
    x0 = margin
    for k in range(n):
        i0 = int(round((x0 + k * pitch) / d))
        i1 = int(round((x0 + k * pitch + w) / d))
        cond[i0:i1 + 1, jh:jh + jt + 1] = k
    free = cond == -1

    def lap(phi):
        # sum over edges of eps * (phi - phi_nb), at every node
        out = np.zeros_like(phi)
        gx = ex * (phi[:-1, :] - phi[1:, :])
        out[:-1, :] += gx
        out[1:, :] -= gx
        gy = ey * (phi[:, :-1] - phi[:, 1:])
        out[:, :-1] += gy
        out[:, 1:] -= gy
        return out

    def apply_free(v):
        phi = np.zeros((nx, ny))
        phi[free] = v
        return lap(phi)[free]

    C = np.zeros((n, n))
    guess = np.zeros(int(free.sum()))
    for k in range(n):
        fixed = np.zeros((nx, ny))
        fixed[cond == k] = 1.0
        b = -lap(fixed)[free]
        sol = _cg(apply_free, b, guess)
        phi = fixed.copy()
        phi[free] = sol
        q = lap(phi)
        for m in range(n):
            C[m, k] = EPS0 * q[cond == m].sum()
    return C


def coupled_lines(w, t, h, pitch, n, er, d=10e-6):
    """L and C matrices (H/m, F/m) of n coupled microstrip lines."""
    c = capacitance(w, t, h, pitch, n, er, d=d)
    c0 = capacitance(w, t, h, pitch, n, 1.0, d=d)
    L = np.linalg.inv(c0) / C_LIGHT ** 2
    return L, c


def single_line(w, t, h, er, d=10e-6):
    """Z0 (ohm) and delay (s/m) of one microstrip."""
    L, C = coupled_lines(w, t, h, 1.0, 1, er, d=d)
    return float(np.sqrt(L[0, 0] / C[0, 0])), float(np.sqrt(L[0, 0] * C[0, 0]))


def hammerstad(w, t, h, er):
    """Closed-form microstrip Z0 and delay (Hammerstad-Jensen, with the
    usual thickness correction), as a check on the solver."""
    if t > 0:
        dw = t / np.pi * np.log(1 + 4 * np.e / (t / h * (1 / np.tanh(np.sqrt(6.517 * w / h))) ** 2))
        dwr = 0.5 * (1 + 1 / np.cosh(np.sqrt(er - 1))) * dw
    else:
        dw = dwr = 0
    def z(u, e):
        f = 6 + (2 * np.pi - 6) * np.exp(-(30.666 / u) ** 0.7528)
        return 60 / np.sqrt(e) * np.log(f / u + np.sqrt(1 + (2 / u) ** 2))
    def eeff(u):
        a = 1 + np.log((u ** 4 + (u / 52) ** 2) / (u ** 4 + 0.432)) / 49 + np.log(1 + (u / 18.1) ** 3) / 18.7
        b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
        return (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / u) ** (-a * b)
    u1 = (w + dw) / h
    ur = (w + dwr) / h
    z01 = z(u1, 1.0)
    z0r = z(ur, 1.0)
    ee = eeff(ur) * (z01 / z0r) ** 2
    z0 = z0r / np.sqrt(eeff(ur))
    return float(z0), float(np.sqrt(ee) / C_LIGHT)
