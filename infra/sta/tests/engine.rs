//! The engine on small netlists, with slacks worked out by hand.

use std::collections::HashMap;

use sta::input::{ArcIn, CheckIn, CheckKindIn, ChipIn, Desc, End, OutIn, RegIn, Sop};
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
        est: 0,
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
            outputs: vec![0],
            in_delays: Vec::new(),
            load: Vec::new(),
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
                est: 0,
                clear: None,
                clear_value: 0,
                clear_arcs: vec![],
                preset: None,
                preset_arcs: vec![],
                enable: None,
                on: vec![],
                off: vec![],
                feedback: None,
                fb_est: 0,
            }],
            checks: vec![CheckIn {
                kind: CheckKindIn::Setup {
                    pins: vec![1],
                    clock: 2,
                    edge: 1,
                    setup: su,
                    hold: h,
                    names: vec!["setup".into(), "hold".into()],
                },
                estimated: vec![],
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
        before: HashMap::new(),
        branch: vec![],
        forced: vec![],
        skip: vec![],
        exceptions: vec![],
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

#[test]
fn setup_and_hold() {
    // Q toggles through an inverter as slow as 25 ns and as quick as 1 ns:
    // at the edge at 20 ns, D is late from the edge at 0 (setup: 20 - 3 -
    // 29 = -12 ns) and early from this one (hold: 22 - 20 - 3 = -1 ns);
    // each is a check of its own
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.reg("R1", "Q", "D", "MCLK", [1000, 4000, 3000, 3000]);
    b.gate("U1", "D", &["Q"], not(1), 1000, 25_000);
    let r = analyse(&b.design(), &case(&[("Q", 0, 1)], "Q"), &Options::default()).unwrap();
    let at = |kind: &str| {
        r[0].worst
            .iter()
            .find(|c| c.chip == "R1" && c.check == kind && c.event == 2)
            .map(|c| c.slack)
    };
    assert_eq!(at("setup"), Some(-12_000), "{:?}", r[0].worst);
    assert_eq!(at("hold"), Some(-1000), "{:?}", r[0].worst);
}

fn arc_d(from: &[u32], lo: i64, hi: i64, name: &str) -> ArcIn {
    ArcIn {
        name: name.into(),
        ..arc(from, lo, hi)
    }
}

impl Build {
    /// A three-state buffer: Y (pin 0) = A (pin 1) while E (pin 2) is high,
    /// on and off in [lo, hi].
    fn buf_en(&mut self, r: &str, y: &str, a: &str, e: &str, on: (i64, i64), off: (i64, i64)) {
        let desc = Desc {
            outputs: vec![OutIn {
                pin: 0,
                func: Some(vec![vec![(1, 1)]]),
                inv: false,
                arcs: vec![arc(&[1], 1000, 2000)],
                enable: Some(vec![vec![(2, 1)]]),
                on: vec![arc_d(&[2], on.0, on.1, "on")],
                off: vec![arc_d(&[2], off.0, off.1, "off")],
            }],
            ..Desc::default()
        };
        self.chip(r, "buf", &[("Y", y), ("A", a), ("E", e)], Some(desc));
    }

    /// An output on a clock of its chip's own.
    fn async_src(&mut self, r: &str, y: &str) {
        let desc = Desc {
            asynchronous: vec![0],
            ..Desc::default()
        };
        self.chip(r, "async", &[("Y", y)], Some(desc));
    }

    fn last_desc(&mut self) -> &mut Desc {
        self.chips.last_mut().unwrap().desc.as_mut().unwrap()
    }
}

#[test]
fn wire_per_receiver() {
    // the toggle with a wire of 1 to 2 ns into R1's D: setup 8 - 2, hold
    // 2 + 1
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.reg("R1", "Q", "D", "MCLK", [1000, 4000, 3000, 0]);
    b.gate("U1", "D", &["Q"], not(1), 1000, 5000);
    b.chips[1].in_delays = vec![[0, 0], [1000, 2000], [0, 0]];
    let r = analyse(&b.design(), &case(&[("Q", 0, 1)], "Q"), &Options::default()).unwrap();
    let at = |kind: &str| {
        r[0].worst
            .iter()
            .filter(|c| c.chip == "R1" && c.check == kind)
            .map(|c| c.slack)
            .min()
    };
    assert_eq!(at("hold"), Some(3000), "{:?}", r[0].worst);
    assert!(r[0].min_slack.unwrap() >= 3000);
}

#[test]
fn jitter() {
    // the toggle, MCLK's edges within 0.5 ns: a setup across edges loses
    // 1 ns; a hold at one edge doesn't
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.chips[0].params.insert("jitter_ps".into(), 500);
    b.reg("R1", "Q", "D", "MCLK", [1000, 4000, 3000, 0]);
    b.gate("U1", "D", &["Q"], not(1), 1000, 5000);
    let o = Options {
        paths: 50,
        marginal: 100_000,
        ..Options::default()
    };
    let r = analyse(&b.design(), &case(&[("Q", 0, 1)], "Q"), &o).unwrap();
    let at = |kind: &str| {
        r[0].worst
            .iter()
            .filter(|c| c.chip == "R1" && c.check == kind && c.event == 2)
            .map(|c| c.slack)
            .min()
    };
    assert_eq!(at("setup"), Some(7000), "{:?}", r[0].worst);
    assert_eq!(at("hold"), Some(2000), "{:?}", r[0].worst);
}

#[test]
fn handover() {
    // A toggles; two buffers drive BUS, B1 while A is high, B2 while AN
    // (A through an inverter, 1 to 2 ns) is: at A's rise B1 turns on in
    // [2, 5] ns and B2 off in [3, 9]: 7 ns both may be on, less A's own
    // spread (1 ns), against a tolerance of 1 ns
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.reg("RA", "A", "AN", "MCLK", [1000, 2000, 1000, 0]);
    b.gate("UA", "AN", &["A"], not(1), 1000, 2000);
    b.buf_en("B1", "BUS", "VCC", "A", (1000, 3000), (1000, 5000));
    b.buf_en("B2", "BUS", "GND", "AN", (1000, 3000), (1000, 5000));
    let o = Options {
        marginal: 100_000,
        ..Options::default()
    };
    let r = analyse(&b.design(), &case(&[("A", 0, 1)], "A"), &o).unwrap();
    let h: Vec<&sta::CheckOut> = r[0]
        .worst
        .iter()
        .filter(|c| c.check == "handover" && c.event == 0)
        .collect();
    assert_eq!(
        h.iter().map(|c| c.slack).min(),
        Some(1000 - 7001 + 1000),
        "{:?}",
        r[0].worst
    );
}

#[test]
fn crossings() {
    // an asynchronous net captured: a failing crossing, unless the
    // register is a synchroniser
    for sync in [false, true] {
        let mut b = Build::new();
        b.osc("MCLK", 20_000);
        b.reg("RT", "T", "TN", "MCLK", [1000, 2000, 1000, 0]);
        b.gate("UT", "TN", &["T"], not(1), 1000, 2000);
        b.async_src("XA", "ASYNC");
        b.reg("RS", "S", "ASYNC", "MCLK", [1000, 2000, 1000, 0]);
        b.chips.last_mut().unwrap().nocheck = sync;
        let r = analyse(&b.design(), &case(&[("T", 0, 1)], "T"), &Options::default()).unwrap();
        let failing = r[0].worst.iter().any(|c| c.check == "crossing");
        assert_eq!(failing, !sync, "{:?}", r[0].worst);
        assert_eq!(!r[0].crossings.is_empty(), sync, "{:?}", r[0].crossings);
    }
}

#[test]
fn recovery_and_removal() {
    // T toggles and clears R (while high) through 2 to 4 ns: released in
    // [22, 24] ns, it's 1 ns after the edge at 20 (removal 1 ns: 22 - 21)
    // and 13 ns before the one at 40 (recovery 3 ns: 40 - 3 - 24)
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.reg("RT", "T", "TN", "MCLK", [1000, 2000, 1000, 0]);
    b.gate("UT", "TN", &["T"], not(1), 1000, 2000);
    b.reg("R", "Q", "GND", "MCLK", [1000, 2000, 1000, 0]);
    b.chips.last_mut().unwrap().pins.push("CLR".into());
    let t = b.net("T");
    b.chips.last_mut().unwrap().nets.push(t);
    let d = b.last_desc();
    d.regs[0].clear = Some(vec![vec![(3, 1)]]);
    d.regs[0].clear_arcs = vec![arc(&[3], 1000, 2000)];
    d.checks.push(CheckIn {
        kind: CheckKindIn::Recovery {
            clock: 2,
            edge: 1,
            recovery: Some(3000),
            removal: Some(1000),
            width: None,
            names: vec![],
        },
        estimated: vec![],
    });
    let o = Options {
        marginal: 100_000,
        ..Options::default()
    };
    let r = analyse(&b.design(), &case(&[("T", 0, 1)], "T"), &o).unwrap();
    let at = |kind: &str, ev: i32| {
        r[0].worst
            .iter()
            .filter(|c| c.chip == "R" && c.check == kind && c.event == ev)
            .map(|c| c.slack)
            .min()
    };
    assert_eq!(at("removal", 2), Some(1000), "{:?}", r[0].worst);
    assert_eq!(at("recovery", 4), Some(13000), "{:?}", r[0].worst);
}

#[test]
fn exceptions() {
    // the toggle's hold turned off, and its setup's path through Q taken
    // as a false path
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.reg("R1", "Q", "D", "MCLK", [1000, 4000, 3000, 0]);
    b.gate("U1", "D", &["Q"], not(1), 1000, 5000);
    let mut c = case(&[("Q", 0, 1)], "Q");
    c.exceptions = vec![
        sta::input::Exception {
            reason: "a test".into(),
            chip: Some("R1".into()),
            check: Some("hold".into()),
            ..Default::default()
        },
        sta::input::Exception {
            reason: "a false path".into(),
            chip: Some("R1".into()),
            check: Some("setup".into()),
            through: Some("Q".into()),
            ..Default::default()
        },
    ];
    let r = analyse(&b.design(), &c, &Options::default()).unwrap();
    assert!(
        !r[0].worst.iter().any(|c| c.chip == "R1"),
        "{:?}",
        r[0].worst
    );
    assert!(
        r[0].excepted[0] > 0 && r[0].excepted[1] > 0,
        "{:?}",
        r[0].excepted
    );
}

#[test]
fn coverage() {
    // a chip that drives a net with no description
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.chip("U9", "mystery", &[("Y", "Z9")], None);
    let cov = sta::coverage(&b.design());
    assert_eq!(cov.undescribed, vec!["U9".to_string()]);
}

#[test]
fn latch() {
    // a transparent latch, Q = LE·D + /LE·Q + D·Q (pins Q, LE, D), its D
    // checked against LE's fall: it holds as LE falls, and D's setup to
    // that fall is evaluated
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.reg("RL", "LE", "LEN", "MCLK", [1000, 2000, 1000, 0]);
    b.gate("UL", "LEN", &["LE"], not(1), 1000, 2000);
    b.reg("RD", "D", "DN", "MCLK", [1000, 2000, 1000, 0]);
    b.gate("UD", "DN", &["D"], not(1), 1000, 2000);
    let desc = Desc {
        outputs: vec![OutIn {
            pin: 0,
            func: Some(vec![
                vec![(1, 1), (2, 1)],
                vec![(1, 0), (0, 1)],
                vec![(2, 1), (0, 1)],
            ]),
            inv: false,
            arcs: vec![arc(&[2], 1000, 3000), arc(&[1], 1000, 4000)],
            enable: None,
            on: vec![],
            off: vec![],
        }],
        checks: vec![CheckIn {
            kind: CheckKindIn::Setup {
                pins: vec![2],
                clock: 1,
                edge: 0,
                setup: 1000,
                hold: 0,
                names: vec![],
            },
            estimated: vec![],
        }],
        ..Desc::default()
    };
    b.chip(
        "UQ",
        "latch",
        &[("Q", "Q"), ("LE", "LE"), ("D", "D")],
        Some(desc),
    );
    let r = analyse(
        &b.design(),
        &case(&[("LE", 0, 1), ("D", 0, 1)], "LE"),
        &Options::default(),
    )
    .unwrap();
    assert!(!r[0].evaluated.is_empty(), "{:?}", r[0]);
    assert!(
        !r[0].worst.iter().any(|c| c.check == "loop"),
        "{:?}",
        r[0].worst
    );
}

#[test]
fn tails_and_pairs() {
    // the toggle through a 25 ns inverter: launched at the edge at 20 ns,
    // D may still change until 49 ns, 9 past the window's end at 40
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.reg("R1", "Q", "D", "MCLK", [1000, 4000, 3000, 0]);
    b.gate("U1", "D", &["Q"], not(1), 1000, 25_000);
    let r = analyse(&b.design(), &case(&[("Q", 0, 1)], "Q"), &Options::default()).unwrap();
    let tail = r[0].tails.iter().find(|t| t.0 == "D").cloned();
    assert_eq!(tail.map(|t| t.2), Some(9000), "{:?}", r[0].tails);
    // carried into the start, D is changing there; before 0 it was the
    // pair's 1
    let o = Options {
        tails: vec![("D".into(), -15_000, 9000)],
        trace: vec!["D".into()],
        ..Options::default()
    };
    let mut c = case(&[("Q", 0, 1)], "Q");
    c.before.insert("D".into(), 1);
    let r = analyse(&b.design(), &c, &o).unwrap();
    let (_, init, tr) = &r[0].traces[0];
    assert_eq!(*init, 2, "a tail leaves the start unknown");
    assert_eq!(tr[0].0, -15_000);
}

#[test]
fn repeats() {
    // T toggles and nothing ends the window: the state at 60 ns is the one
    // at 20, so the branch ends there
    let mut b = Build::new();
    b.osc("MCLK", 20_000);
    b.reg("RT", "T", "TN", "MCLK", [1000, 2000, 1000, 0]);
    b.gate("UT", "TN", &["T"], not(1), 1000, 2000);
    b.net("GND");
    let r = analyse(
        &b.design(),
        &case(&[("T", 0, 1)], "GND"),
        &Options::default(),
    )
    .unwrap();
    assert_eq!(r[0].repeats, Some(2));
    assert_eq!(r[0].end, 6);
}
