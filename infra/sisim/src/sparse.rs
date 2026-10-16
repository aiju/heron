//! Sparse LU factorisation with a fixed pattern.
//!
//! Nodal matrices are structurally symmetric, and with a capacitor or a
//! line at nearly every node they're strongly diagonal, so the pivots are
//! taken in a fixed order (minimum degree, for little fill) without
//! pivoting. The pattern, the order and where each update lands are worked
//! out once; each factorisation is then a run over flat arrays.

use std::collections::{BTreeSet, HashMap};

/// The filled pattern of an n × n matrix and the storage for its values.
#[derive(Debug, Clone)]
pub struct Lu {
    n: usize,
    /// perm[new] = old, and pos[old] = new
    perm: Vec<usize>,
    pos: Vec<usize>,
    /// For pivot k (new numbering): its later neighbours, ascending, with
    /// the slots of A[k][j] (upper) and A[j][k] (lower).
    adj: Vec<Vec<usize>>,
    upper: Vec<Vec<usize>>,
    lower: Vec<Vec<usize>>,
    /// For pivot k, the slot each l_ik·u_kj update lands in, row-major
    /// over adj[k] × adj[k].
    targets: Vec<Vec<usize>>,
    /// Slot of (old i, old j), and the other way round.
    slots: HashMap<(usize, usize), usize>,
    entries: Vec<(usize, usize)>,
    /// The values: the diagonal in slots 0..n (new numbering), then the
    /// rest. After `factor`, they hold L (unit diagonal, below) and U.
    pub vals: Vec<f64>,
    work: Vec<f64>,
}

impl Lu {
    /// The pattern for an n × n matrix with nonzeros at `entries` (old
    /// numbering), made symmetric; the diagonal is always there.
    pub fn new(n: usize, entries: &[(usize, usize)]) -> Lu {
        let mut graph: Vec<BTreeSet<usize>> = vec![BTreeSet::new(); n];
        for &(i, j) in entries {
            if i != j {
                graph[i].insert(j);
                graph[j].insert(i);
            }
        }
        // minimum degree, eliminating on the graph as we go: the
        // neighbours of an eliminated node become a clique (the fill)
        let mut done = vec![false; n];
        let mut perm = Vec::with_capacity(n);
        let mut later: Vec<Vec<usize>> = vec![Vec::new(); n];
        for _ in 0..n {
            let v = (0..n)
                .filter(|&v| !done[v])
                .min_by_key(|&v| (graph[v].len(), v))
                .unwrap();
            done[v] = true;
            perm.push(v);
            let nb: Vec<usize> = graph[v].iter().copied().collect();
            for &a in &nb {
                graph[a].remove(&v);
                for &b in &nb {
                    if a != b {
                        graph[a].insert(b);
                    }
                }
            }
            later[v] = nb;
        }
        let mut pos = vec![0; n];
        for (k, &v) in perm.iter().enumerate() {
            pos[v] = k;
        }
        let mut adj: Vec<Vec<usize>> = (0..n)
            .map(|k| {
                let mut a: Vec<usize> = later[perm[k]].iter().map(|&o| pos[o]).collect();
                a.sort_unstable();
                a
            })
            .collect();
        // slots, in the new numbering
        let mut slot_new: HashMap<(usize, usize), usize> = HashMap::new();
        let mut next = n;
        let mut upper = vec![Vec::new(); n];
        let mut lower = vec![Vec::new(); n];
        for k in 0..n {
            slot_new.insert((k, k), k);
            for &j in &adj[k] {
                slot_new.insert((k, j), next);
                upper[k].push(next);
                slot_new.insert((j, k), next + 1);
                lower[k].push(next + 1);
                next += 2;
            }
        }
        let mut targets = vec![Vec::new(); n];
        for k in 0..n {
            for &i in &adj[k] {
                for &j in &adj[k] {
                    targets[k].push(slot_new[&(i, j)]);
                }
            }
        }
        let mut slots = HashMap::new();
        let mut entries = vec![(0, 0); next];
        for (&(i, j), &s) in &slot_new {
            slots.insert((perm[i], perm[j]), s);
            entries[s] = (perm[i], perm[j]);
        }
        adj.shrink_to_fit();
        Lu {
            n,
            perm,
            pos,
            adj,
            upper,
            lower,
            targets,
            slots,
            entries,
            vals: vec![0.0; next],
            work: vec![0.0; n],
        }
    }

    pub fn len(&self) -> usize {
        self.vals.len()
    }

    /// The slot of entry (i, j), old numbering; it must be in the pattern.
    pub fn slot(&self, i: usize, j: usize) -> usize {
        self.slots[&(i, j)]
    }

    /// The (row, column) of each slot, old numbering.
    pub fn entries(&self) -> &[(usize, usize)] {
        &self.entries
    }

    /// Factorise `vals` in place. Fails on a zero or non-finite pivot.
    pub fn factor(&mut self) -> Result<(), usize> {
        for k in 0..self.n {
            let p = self.vals[k];
            if !p.is_finite() || p.abs() < 1e-300 {
                return Err(self.perm[k]);
            }
            let m = self.adj[k].len();
            for ii in 0..m {
                let s = self.lower[k][ii];
                self.vals[s] /= p;
            }
            let t = &self.targets[k];
            for ii in 0..m {
                let l = self.vals[self.lower[k][ii]];
                if l == 0.0 {
                    continue;
                }
                for jj in 0..m {
                    let u = self.vals[self.upper[k][jj]];
                    self.vals[t[ii * m + jj]] -= l * u;
                }
            }
        }
        Ok(())
    }

    /// Solve A·x = b with the factorised values; `b` (old numbering) is
    /// overwritten with x.
    pub fn solve(&mut self, b: &mut [f64]) {
        let y = &mut self.work;
        for (old, &new) in self.pos.iter().enumerate() {
            y[new] = b[old];
        }
        for k in 0..self.n {
            let yk = y[k];
            if yk != 0.0 {
                for (ii, &i) in self.adj[k].iter().enumerate() {
                    y[i] -= self.vals[self.lower[k][ii]] * yk;
                }
            }
        }
        for k in (0..self.n).rev() {
            let mut s = y[k];
            for (jj, &j) in self.adj[k].iter().enumerate() {
                s -= self.vals[self.upper[k][jj]] * y[j];
            }
            y[k] = s / self.vals[k];
        }
        for (new, &old) in self.perm.iter().enumerate() {
            b[old] = y[new];
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn solves_a_small_system() {
        // a ladder with one extra coupling, so there is fill
        let a = [
            [4.0, -1.0, 0.0, -1.0],
            [-1.0, 4.0, -1.0, 0.0],
            [0.0, -1.0, 4.0, -1.0],
            [-1.0, 0.0, -1.0, 4.0],
        ];
        let mut entries = Vec::new();
        for (i, row) in a.iter().enumerate() {
            for (j, &v) in row.iter().enumerate() {
                if v != 0.0 {
                    entries.push((i, j));
                }
            }
        }
        let mut lu = Lu::new(4, &entries);
        for (i, row) in a.iter().enumerate() {
            for (j, &v) in row.iter().enumerate() {
                if v != 0.0 {
                    let s = lu.slot(i, j);
                    lu.vals[s] += v;
                }
            }
        }
        lu.factor().unwrap();
        let x = [1.0, 2.0, -3.0, 0.5];
        let mut b: Vec<f64> = (0..4)
            .map(|i| (0..4).map(|j| a[i][j] * x[j]).sum())
            .collect();
        lu.solve(&mut b);
        for i in 0..4 {
            assert!((b[i] - x[i]).abs() < 1e-12, "{b:?}");
        }
    }
}
