//! What a netlist leaves untimed (RFC 0048 9.8): chips with no
//! description, outputs nothing times, checks the data hasn't the figures
//! for; and every check by index, which each branch's `evaluated` names.

use serde::Serialize;

use crate::design::{CheckKind, Design, Kind, Source};

#[derive(Serialize, Clone, Debug)]
pub struct Coverage {
    /// Every check, as (chip, kind, what), in the order the branches'
    /// `evaluated` indices count them.
    pub checks: Vec<(String, String, String)>,
    /// Chips that drive a net but have no description.
    pub undescribed: Vec<String>,
    /// Described chips' driving pins on a net that no output times, as
    /// "U_X.PIN".
    pub untimed: Vec<String>,
    /// (chip, what): checks a description has but the part's data hasn't
    /// the figures for.
    pub unchecked: Vec<(String, String)>,
    /// Crossings by structure (RFC 0048 9.7): the chips whose clears or
    /// presets an asynchronous source reaches through combinatorial logic
    /// (RESET_n's release), with that source: (chip, source).
    pub async_forces: Vec<(String, String)>,
}

/// The netlist's coverage, before any case.
pub fn coverage(d: &Design) -> Coverage {
    let pins = |ci: u32, ps: &[u32]| -> String {
        let c = &d.chips[ci as usize];
        ps.iter()
            .map(|&p| c.pins[p as usize].as_str())
            .collect::<Vec<_>>()
            .join(" ")
    };
    let checks = d
        .checks
        .iter()
        .map(|ch| {
            let c = &d.chips[ch.chip as usize];
            let pin = |p: u32| c.pins[p as usize].clone();
            let (kind, what) = match &ch.kind {
                CheckKind::Setup {
                    pins: ps, clock, ..
                } => ("setup", format!("{} to {}", pins(ch.chip, ps), pin(*clock))),
                CheckKind::Width { pin: p, level, .. } => (
                    "width",
                    format!("{} {}", pin(*p), if *level == 1 { "high" } else { "low" }),
                ),
                CheckKind::Period { pin: p, .. } => ("period", pin(*p)),
                CheckKind::Recovery { clock, .. } => {
                    ("recovery", format!("clears to {}", pin(*clock)))
                }
                CheckKind::Strobe { eq, .. } => ("strobe", eq.clone()),
            };
            (c.reference.clone(), kind.to_string(), what)
        })
        .collect();
    let mut undescribed = Vec::new();
    let mut untimed = Vec::new();
    let mut unchecked = Vec::new();
    for c in &d.chips {
        let driving: Vec<u32> = c
            .out_pins
            .iter()
            .copied()
            .filter(|&p| c.nets.get(p as usize).copied().flatten().is_some())
            .collect();
        if driving.is_empty() {
            continue;
        }
        if !c.described && c.model != "osc" {
            undescribed.push(c.reference.clone());
            continue;
        }
        for p in driving {
            if !c.outs.iter().any(|&o| d.outs[o as usize].pin == p) {
                untimed.push(format!("{}.{}", c.reference, c.pins[p as usize]));
            }
        }
        for u in &c.unchecked {
            unchecked.push((c.reference.clone(), u.clone()));
        }
    }
    Coverage {
        checks,
        undescribed,
        untimed,
        unchecked,
        async_forces: async_forces(d),
    }
}

/// The chips whose registers' clears or presets read a net that an
/// asynchronous output reaches through combinatorial outputs.
fn async_forces(d: &Design) -> Vec<(String, String)> {
    // each net's asynchronous source, by structure alone
    let mut src: Vec<Option<u32>> = vec![None; d.nets.len()];
    for (oi, o) in d.outs.iter().enumerate() {
        if let (Kind::Async, Some(n)) = (&o.kind, o.net) {
            src[n as usize] = Some(oi as u32);
        }
    }
    let reads = |oi: usize, src: &[Option<u32>]| -> Option<u32> {
        let o = &d.outs[oi];
        let c = &d.chips[o.chip as usize];
        d.reads_of[oi].iter().find_map(|&p| match c.source(p) {
            Source::Net(n) => src[n as usize],
            _ => None,
        })
    };
    loop {
        let mut changed = false;
        for (oi, o) in d.outs.iter().enumerate() {
            if let (Kind::Comb { .. }, Some(n)) = (&o.kind, o.net)
                && src[n as usize].is_none()
                && let Some(s) = reads(oi, &src)
            {
                src[n as usize] = Some(s);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    let mut out: Vec<(String, String)> = Vec::new();
    for o in &d.outs {
        let Kind::Reg { clear, preset, .. } = &o.kind else {
            continue;
        };
        let c = &d.chips[o.chip as usize];
        for f in [clear, preset].into_iter().flatten() {
            for p in crate::logic::support(&f.f) {
                if let Source::Net(n) = c.source(p)
                    && let Some(s) = src[n as usize]
                {
                    let e = (c.reference.clone(), d.out_name(s));
                    if !out.contains(&e) {
                        out.push(e);
                    }
                }
            }
        }
    }
    out
}
