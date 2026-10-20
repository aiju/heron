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
}
