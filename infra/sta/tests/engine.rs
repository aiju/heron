//! The engine on small netlists, with slacks worked out by hand.

use std::collections::HashMap;

use sta::input::{ArcIn, CheckIn, ChipIn, Desc, End, OutIn, RegIn, Sop};
use sta::{Case, Design, Netlist, Options, analyse};

struct Build {
    nets: Vec<String>,
    chips: Vec<ChipIn>,
}

fn d(lo: i64, hi: i64) -> [Option<i64>; 3] {
    [Some(lo), Some(hi), Some(hi)]
}

fn arc(from: &[u32], lo: i64, hi: i64) -> ArcIn {
    ArcIn {
        from: from.to_vec(),
        d: d(lo, hi),
        name: "A->Y".into(),
        when: None,
    }
}

impl Build {
    fn new() -> Build {
        Build {
            nets: Vec::new(),
            chips: Vec::new(),
        }
    }

    fn net(&mut self, n: &str) -> i64 {
        if let Some(i) = self.nets.iter().position(|x| x == n) {
            return i as i64;
        }
        self.nets.push(n.into());
        (self.nets.len() - 1) as i64
    }

    fn chip(&mut self, r: &str, model: &str, pins: &[(&str, &str)], desc: Option<Desc>) {
        let nets = pins.iter().map(|(_, n)| self.net(n)).collect();
        self.chips.push(ChipIn {
            reference: r.into(),
            ctype: model.into(),
            model: model.into(),
            family: String::new(),
            part: String::new(),
            pins: pins.iter().map(|(p, _)| p.to_string()).collect(),
            nets,
            params: HashMap::new(),
            nocheck: false,
            desc,
            pin_delays: Vec::new(),
        });
    }

    fn osc(&mut self, net: &str, period: i64) {
        self.chip("X_OSC", "osc", &[("OUT", net)], None);
        self.chips
            .last_mut()
            .unwrap()
            .params
            .insert("period_ps".into(), period);
    }

    /// A gate: Y (pin 0) = func of A, B, ... (pins 1..).
    fn gate(&mut self, r: &str, y: &str, ins: &[&str], func: Sop, lo: i64, hi: i64) {
        let mut pins = vec![("Y", y)];
        let names = ["A", "B", "C", "D"];
        for (i, n) in ins.iter().enumerate() {
            pins.push((names[i], n));
        }
        let from: Vec<u32> = (1..=ins.len() as u32).collect();
        let desc = Desc {
            outputs: vec![OutIn {
                pin: 0,
                func: Some(func),
                inv: false,
                arcs: vec![arc(&from, lo, hi)],
                enable: None,
                on: vec![],
                off: vec![],
            }],
            ..Desc::default()
        };
        self.chip(r, "gate", &pins, Some(desc));
    }

    /// A D register: Q (pin 0) = D (pin 1) at CLK (pin 2) rising; t its
    /// clock-to-output minimum and maximum, setup and hold.
    fn reg(&mut self, r: &str, q: &str, dn: &str, clk: &str, t: [i64; 4]) {
        let (tco, su, h) = ((t[0], t[1]), t[2], t[3]);
        let desc = Desc {
            regs: vec![RegIn {
                pin: 0,
                clock: 2,
                edge: 1,
                next: vec![vec![(1, 1)]],
                inv: false,
                d: d(tco.0, tco.1),
                name: "CLK->Q".into(),
                clear: None,
                clear_value: 0,
                clear_arcs: vec![],
                preset: None,
                preset_arcs: vec![],
                enable: None,
                on: vec![],
                off: vec![],
                feedback: None,
            }],
            checks: vec![CheckIn::Setup {
                pins: vec![1],
                clock: 2,
                edge: 1,
                setup: su,
                hold: h,
                names: vec!["setup".into(), "hold".into()],
            }],
            ..Desc::default()
        };
        self.chip(r, "reg", &[("Q", q), ("D", dn), ("CLK", clk)], Some(desc));
    }

    fn design(&self) -> Design {
        Design::new(&Netlist {
            nets: self.nets.clone(),
            chips: self.chips.clone(),
            pulled: vec![],
        })
        .unwrap()
    }
}

fn not(p: u32) -> Sop {
    vec![vec![(p, 0)]]
}

fn case(start: &[(&str, u8, u8)], end: &str) -> Case {
    Case {
        label: "t".into(),
        clock: "MCLK".into(),
        pins: HashMap::new(),
        constant: HashMap::new(),
        start: start
            .iter()
            .map(|(n, a, b)| (n.to_string(), (*a, *b)))
            .collect(),
        branch: vec![],
        forced: vec![],
        skip: vec![],
        end: End {
            net: end.into(),
            events: 40,
        },
    }
}

#[test]
fn toggle() {
    // Q toggles at every rising edge of a 20 ns clock through an inverter
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.reg("R1", "Q", "D", "MCLK", [1000, 4000, 3000, 0]);
    b.gate("U1", "D", &["Q"], not(1), 1000, 5000);
    let r = analyse(&b.design(), &case(&[("Q", 0, 1)], "Q"), &Options::default()).unwrap();
    assert_eq!(r.len(), 1);
    let br = &r[0];
    assert_eq!(br.end, 4, "Q rises again at the edge at 40 ns");
    assert_eq!(br.failing, 0);
    // setup: D settles by 0 + 4 + 5 = 9 ns, needed by 20 - 3: 8 ns;
    // hold: D changes at 20 + 1 + 1 = 22 ns at the earliest: 2 ns
    assert_eq!(br.min_slack, Some(2000));
    let setups: Vec<i64> = br
        .worst
        .iter()
        .filter(|c| c.check == "setup")
        .map(|c| c.slack)
        .collect();
    assert!(setups.is_empty() || setups.iter().all(|&s| s >= 0));
}

#[test]
fn common_path() {
    // two registers on a buffered clock: the buffer's spread counts once
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.gate("B1", "CK", &["MCLK"], vec![vec![(1, 1)]], 1000, 3000);
    b.reg("R1", "Q1", "D1", "CK", [500, 2000, 1000, 400]);
    b.gate("U1", "D1", &["Q1"], not(1), 1000, 2000);
    b.reg("R2", "Q2", "Q1", "CK", [500, 2000, 1000, 400]);
    let r = analyse(
        &b.design(),
        &case(&[("Q1", 0, 1)], "Q1"),
        &Options::default(),
    )
    .unwrap();
    let br = &r[0];
    assert_eq!(br.failing, 0, "{:?}", br.worst);
    // R2's hold: Q1 changes 0.5 ns after CK at the earliest, CK's spread
    // (2 ns) shared: 0.5 - 0.4 = 0.1 ns
    let hold: Vec<&sta::CheckOut> = br
        .worst
        .iter()
        .filter(|c| c.chip == "R2" && c.check == "hold")
        .collect();
    assert_eq!(br.min_slack, Some(100), "{:?}", br.worst);
    assert!(!hold.is_empty());
}

#[test]
fn glitch_and_cover() {
    // a clock made by a multiplexer whose select changes while both its
    // inputs are 1: a static hazard, unless a term holds it
    for cover in [false, true] {
        let mut b = Build::new();
        b.osc("MCLK", 20_000);
        b.reg("RS", "S", "SN", "MCLK", [1000, 2000, 1000, 0]);
        b.gate("US", "SN", &["S"], not(1), 1000, 2000);
        // Y = /S·A + S·B (+ A·B), A = B = 1
        let mut f: Sop = vec![vec![(1, 0), (2, 1)], vec![(1, 1), (3, 1)]];
        if cover {
            f.push(vec![(2, 1), (3, 1)]);
        }
        b.gate("UM", "CK", &["S", "VCC", "VCC"], f, 1000, 2000);
        b.reg("R", "Q", "QN", "CK", [1000, 2000, 1000, 0]);
        b.gate("UQ", "QN", &["Q"], not(1), 1000, 2000);
        let r = analyse(&b.design(), &case(&[("S", 0, 1)], "S"), &Options::default()).unwrap();
        let glitches = r[0].worst.iter().filter(|c| c.check == "glitch").count();
        assert_eq!(glitches > 0, !cover, "cover {cover}: {:?}", r[0].worst);
    }
}

#[test]
fn race() {
    // an AND of two registers' outputs changing at the same edge, one up and
    // one down: a race, so the clock it makes may pulse
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.reg("RA", "A", "AN", "MCLK", [1000, 2000, 1000, 0]);
    b.gate("UA", "AN", &["A"], not(1), 1000, 2000);
    b.reg("RB", "B", "BN", "MCLK", [1000, 2000, 1000, 0]);
    b.gate("UB", "BN", &["B"], not(1), 1000, 2000);
    b.gate(
        "UK",
        "CK",
        &["A", "B"],
        vec![vec![(1, 1), (2, 1)]],
        1000,
        2000,
    );
    b.reg("R", "Q", "QN", "CK", [1000, 2000, 1000, 0]);
    b.gate("UQ", "QN", &["Q"], not(1), 1000, 2000);
    let r = analyse(
        &b.design(),
        &case(&[("A", 0, 1), ("B", 1, 0)], "A"),
        &Options::default(),
    )
    .unwrap();
    assert!(
        r[0].worst
            .iter()
            .any(|c| c.check == "glitch" && c.chip == "R"),
        "{:?}",
        r[0].worst
    );
}

#[test]
fn branches() {
    // a register named as a branch that would load X splits the case
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.reg("RT", "T", "TN", "MCLK", [1000, 2000, 1000, 0]);
    b.gate("UT", "TN", &["T"], not(1), 1000, 2000);
    b.reg("RX", "XQ", "FLOAT", "MCLK", [1000, 2000, 1000, 0]);
    let mut c = case(&[("T", 0, 1)], "T");
    c.branch = vec!["XQ".into()];
    let r = analyse(&b.design(), &c, &Options::default()).unwrap();
    // it loads X at the edges at 0, 20 and 40 ns, the window's end: no
    // splitting after that
    assert_eq!(r.len(), 8);
    let mut choices: Vec<_> = r.iter().map(|b| b.choices.clone()).collect();
    choices.dedup();
    assert_eq!(choices.len(), 8);
}
