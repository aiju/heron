//! Values and sums of products.
//!
//! A value is 0, 1, X (stable, not known) or Z (no driver on, which logic
//! reads as X). A sum of products is evaluated in three values: a term is
//! 1 if every literal is known true, 0 if one is known false, else X.

use crate::input::Sop;

pub const V0: u8 = 0;
pub const V1: u8 = 1;
pub const X: u8 = 2;
pub const Z: u8 = 3;

/// What logic reads: Z as X.
pub fn read(v: u8) -> u8 {
    if v > 1 { X } else { v }
}

/// Two values that may be either: the value if they agree, else X.
pub fn merge(a: u8, b: u8) -> u8 {
    if a == b && a <= 1 { a } else { X }
}

pub fn known(v: u8) -> bool {
    v <= 1
}

pub fn not(v: u8) -> u8 {
    match v {
        V0 => V1,
        V1 => V0,
        _ => X,
    }
}

/// A term's value with pin values from `get`.
pub fn term(t: &[(u32, u8)], get: &impl Fn(u32) -> u8) -> u8 {
    let mut out = V1;
    for &(p, want) in t {
        let v = read(get(p));
        if v == X {
            out = X;
        } else if v != want {
            return V0;
        }
    }
    out
}

/// A sum of products' value.
pub fn sop(f: &Sop, get: &impl Fn(u32) -> u8) -> u8 {
    let mut out = V0;
    for t in f {
        match term(t, get) {
            V1 => return V1,
            X => out = X,
            _ => {}
        }
    }
    out
}

/// Whether some term is known true with no literal on a pin in `moving`.
pub fn held1(f: &Sop, get: &impl Fn(u32) -> u8, moving: &impl Fn(u32) -> bool) -> bool {
    f.iter().any(|t| {
        t.iter()
            .all(|&(p, want)| !moving(p) && read(get(p)) == want)
    })
}

/// Whether every term has a literal on a pin not in `moving` that is
/// known false.
pub fn held0(f: &Sop, get: &impl Fn(u32) -> u8, moving: &impl Fn(u32) -> bool) -> bool {
    f.iter().all(|t| {
        t.iter().any(|&(p, want)| {
            let v = read(get(p));
            !moving(p) && v != X && v != want
        })
    })
}

/// Whether pin `p` can matter to the function: some term has a literal on
/// it and none on a pin not `moving` that is known false.
pub fn live(f: &Sop, p: u32, get: &impl Fn(u32) -> u8, moving: &impl Fn(u32) -> bool) -> bool {
    f.iter().any(|t| {
        t.iter().any(|&(q, _)| q == p)
            && !t.iter().any(|&(q, want)| {
                let v = read(get(q));
                q != p && !moving(q) && v != X && v != want
            })
    })
}

/// Whether a change of pin `p` can reach the output of a sum of products:
/// some live term has a literal on it (no known-false literal on a pin not
/// moving) that no other live term covers. A term covers it if it has no
/// literal on p or on a moving pin, and its literals not known true are
/// among the first's: whenever the first is true, it is, so it holds the
/// output while p changes.
pub fn matters(f: &Sop, p: u32, get: &impl Fn(u32) -> u8, moving: &impl Fn(u32) -> bool) -> bool {
    let unknown = |q: u32| moving(q) || read(get(q)) == X;
    let is_live = |t: &Vec<(u32, u8)>| {
        !t.iter().any(|&(q, want)| {
            let v = read(get(q));
            q != p && !moving(q) && v != X && v != want
        })
    };
    f.iter().any(|t| {
        if !t.iter().any(|&(q, _)| q == p) || !is_live(t) {
            return false;
        }
        let open: Vec<(u32, u8)> = t
            .iter()
            .copied()
            .filter(|&(q, _)| q != p && unknown(q))
            .collect();
        !f.iter().any(|o| {
            !std::ptr::eq(o, t)
                && is_live(o)
                && !o.iter().any(|&(q, _)| q == p || moving(q))
                && o.iter()
                    .filter(|&&(q, _)| unknown(q))
                    .all(|lit| open.contains(lit))
        })
    })
}

/// Whether the function's value can differ with pin `p` at 0 and at 1, for
/// some values of the pins `get` doesn't know (and those `moving`), the
/// others as `get` has them: exactly, over up to 12 unknown pins; else
/// conservatively yes.
pub fn depends_exact(
    f: &Sop,
    p: u32,
    get: &impl Fn(u32) -> u8,
    moving: &impl Fn(u32) -> bool,
) -> bool {
    let val = |q: u32| if moving(q) { X } else { read(get(q)) };
    let mut terms: Vec<Vec<(u32, u8)>> = Vec::new();
    for t in f {
        let mut keep = Vec::new();
        let mut dead = false;
        for &(q, want) in t {
            if q == p {
                keep.push((q, want));
                continue;
            }
            match val(q) {
                X => keep.push((q, want)),
                v if v != want => {
                    dead = true;
                    break;
                }
                _ => {}
            }
        }
        if !dead {
            terms.push(keep);
        }
    }
    if !terms.iter().any(|t| t.iter().any(|&(q, _)| q == p)) {
        return false;
    }
    let mut vars: Vec<u32> = terms
        .iter()
        .flatten()
        .map(|&(q, _)| q)
        .filter(|&q| q != p)
        .collect();
    vars.sort_unstable();
    vars.dedup();
    if vars.len() > 12 {
        return true;
    }
    let eval = |a: u32, pv: u8| {
        terms.iter().any(|t| {
            t.iter().all(|&(q, want)| {
                let v = if q == p {
                    pv
                } else {
                    (a >> vars.binary_search(&q).unwrap() & 1) as u8
                };
                v == want
            })
        })
    };
    (0..1u32 << vars.len()).any(|a| eval(a, 0) != eval(a, 1))
}

/// Whether inputs changing together, once each (pin, value before,
/// after), move every literal they have in the function the same way: all
/// towards true, or all towards false. A sum of products then changes
/// once at most, whatever their order: each term only turns on, or only
/// off. A literal's way is the value it changes to, or, where that isn't
/// known, away from the value it changes from.
pub fn monotone(f: &Sop, moves: &[(u32, u8, u8)]) -> bool {
    let mut dir = None;
    for &(q, b, a) in moves {
        if b == a && known(b) {
            continue;
        }
        for t in f {
            for &(p, want) in t {
                if p != q {
                    continue;
                }
                let rise = if known(a) {
                    a == want
                } else if known(b) {
                    b != want
                } else {
                    return false;
                };
                if *dir.get_or_insert(rise) != rise {
                    return false;
                }
            }
        }
    }
    true
}

/// Whether a register holds its state: its next state (`f`, inverted if
/// `inv`), with the pins `own` names reading the state, is the state for
/// either value of it and every value of the pins `get` doesn't know (up
/// to 12; else no).
pub fn holds(f: &Sop, inv: bool, own: &impl Fn(u32) -> bool, get: &impl Fn(u32) -> u8) -> bool {
    if !f.iter().flatten().any(|&(q, _)| own(q)) {
        return false;
    }
    // three values answer most: a known result is the result for every
    // value of the unknown pins
    let next = |s: u8| {
        let v = sop(f, &|q| if own(q) { s } else { get(q) });
        if inv { not(v) } else { v }
    };
    match (next(V0), next(V1)) {
        (V0, V1) => return true,
        (V1, _) | (_, V0) => return false,
        _ => {}
    }
    let mut vars: Vec<u32> = support(f)
        .into_iter()
        .filter(|&q| !own(q) && read(get(q)) == X)
        .collect();
    vars.sort_unstable();
    if vars.len() > 12 {
        return false;
    }
    (0..1u32 << vars.len()).all(|a| {
        [V0, V1].into_iter().all(|s| {
            let v = sop(f, &|q| {
                if own(q) {
                    s
                } else if let Ok(i) = vars.binary_search(&q) {
                    (a >> i & 1) as u8
                } else {
                    get(q)
                }
            });
            (if inv { not(v) } else { v }) == s
        })
    })
}

/// Whether the function depends on pin `p` with the others as `get` has
/// them: its value differs, or isn't known, with p at 0 and at 1.
pub fn depends(f: &Sop, p: u32, get: &impl Fn(u32) -> u8) -> bool {
    if !f.iter().any(|t| t.iter().any(|&(q, _)| q == p)) {
        return false;
    }
    let a = sop(f, &|q| if q == p { V0 } else { get(q) });
    let b = sop(f, &|q| if q == p { V1 } else { get(q) });
    a == X || b == X || a != b
}

/// The pins a sum of products reads.
pub fn support(f: &Sop) -> Vec<u32> {
    let mut out: Vec<u32> = f.iter().flatten().map(|&(p, _)| p).collect();
    out.sort_unstable();
    out.dedup();
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn f(terms: &[&[(u32, u8)]]) -> Sop {
        terms.iter().map(|t| t.to_vec()).collect()
    }

    #[test]
    fn three_values() {
        // a·b + /a·c
        let g = f(&[&[(0, 1), (1, 1)], &[(0, 0), (2, 1)]]);
        let vals = [X, V1, V1];
        assert_eq!(sop(&g, &|p| vals[p as usize]), X);
        let vals = [V1, V1, X];
        assert_eq!(sop(&g, &|p| vals[p as usize]), V1);
        let vals = [V0, V1, V0];
        assert_eq!(sop(&g, &|p| vals[p as usize]), V0);
        assert!(depends(&g, 0, &|p| [X, V1, V0][p as usize]));
        assert!(!depends(&g, 2, &|p| [V1, V1, X][p as usize]));
        // with a changing and b = c = 1, no term holds the output
        let vals = [X, V1, V1];
        assert!(!held1(&g, &|p| vals[p as usize], &|p| p == 0));
        let cover = f(&[&[(0, 1), (1, 1)], &[(0, 0), (2, 1)], &[(1, 1), (2, 1)]]);
        assert!(held1(&cover, &|p| vals[p as usize], &|p| p == 0));
        assert!(held0(&g, &|p| [X, V0, V0][p as usize], &|p| p == 0));
    }

    #[test]
    fn monotone_changes() {
        // /a·/b: a and b rising together only turn the term off
        let g = f(&[&[(0, 0), (1, 0)]]);
        assert!(monotone(&g, &[(0, V0, V1), (1, V0, V1)]));
        assert!(!monotone(&g, &[(0, V0, V1), (1, V1, V0)]));
        // b from unknown to 1: its literal falls or stays false
        assert!(monotone(&g, &[(0, V0, V1), (1, X, V1)]));
        assert!(!monotone(&g, &[(0, V0, V1), (1, X, X)]));
        // a·b + /a·c: a is binate
        let g = f(&[&[(0, 1), (1, 1)], &[(0, 0), (2, 1)]]);
        assert!(!monotone(&g, &[(0, V0, V1), (1, V0, V1)]));
    }

    #[test]
    fn hold() {
        // q := d·en + q·/en, q on pin 2
        let g = f(&[&[(0, 1), (1, 1)], &[(2, 1), (1, 0)]]);
        let own = |p: u32| p == 2;
        assert!(holds(&g, false, &own, &|p| [X, V0, X][p as usize]));
        assert!(!holds(&g, false, &own, &|p| [X, X, X][p as usize]));
        assert!(!holds(&g, false, &own, &|p| [V1, V1, X][p as usize]));
    }
}
