//! The event-driven core on small circuits: delays, the latest-arrival
//! rule, bus contention, and setup and hold checks.

use std::collections::HashMap;

use hwsim::machine::{ChipDesc, Netlist, build};
use hwsim::rng::Rng;
use hwsim::sim::Sim;

/// A netlist under construction: nets are named, "-" is unconnected.
#[derive(Default)]
struct Circuit {
    nets: Vec<String>,
    chips: Vec<ChipDesc>,
}

impl Circuit {
    fn net(&mut self, name: &str) -> i64 {
        if name == "-" {
            return -1;
        }
        let i = self.nets.iter().position(|n| n == name).unwrap_or_else(|| {
            self.nets.push(name.to_string());
            self.nets.len() - 1
        });
        i as i64
    }

    /// pins: (name, kind, net)
    fn chip(
        &mut self,
        reference: &str,
        model: &str,
        pins: &[(&str, &str, &str)],
        delays: &[(&str, i64)],
    ) {
        let nets = pins.iter().map(|&(_, _, n)| self.net(n)).collect();
        self.chips.push(ChipDesc {
            reference: reference.into(),
            model: model.into(),
            part: model.into(),
            pins: pins.iter().map(|p| p.0.to_string()).collect(),
            kinds: pins.iter().map(|p| p.1.to_string()).collect(),
            nets,
            delays: delays.iter().map(|&(k, v)| (k.to_string(), v)).collect(),
        });
    }

    /// Sources the test drives by hand: a clock generator's outputs.
    fn sources(&mut self, nets: &[&str]) {
        let pins: Vec<_> = nets.iter().map(|&n| (n, "out", n)).collect();
        self.chip("SRC", "clockgen", &pins, &[]);
    }

    fn rails(&mut self) {
        self.chip(
            "RAIL",
            "const",
            &[("LO", "out", "lo"), ("HI", "out", "hi")],
            &[],
        );
    }

    fn build(self) -> Sim {
        let nl = Netlist {
            nets: self.nets,
            chips: self.chips,
        };
        let mut sim = build(&nl, &HashMap::new(), &mut Rng::new(1)).unwrap();
        sim.run(1);
        sim
    }
}

fn val(sim: &Sim, net: &str) -> (u8, i64) {
    let n = &sim.state.nets[sim.net(net).unwrap() as usize];
    (n.val, n.last)
}

/// Drive source `pin` to v at time t.
fn set(sim: &mut Sim, pin: &str, t: i64, v: u8) {
    let src = &sim.chips[sim.chip("SRC").unwrap()].info;
    let o = src.outs[src.pin_names.iter().position(|p| p == pin).unwrap()].unwrap();
    sim.state.schedule(o, t, v, true);
}

/// Delays for a 541: (A->Y, OE->Y en, OE->Y dis).
const BUF541: (i64, i64, i64) = (5000, 10_000, 8000);

fn buf541(c: &mut Circuit, reference: &str, oe1: &str, a1: &str, y1: &str, d: (i64, i64, i64)) {
    let mut pins = vec![("OE1", "in", oe1), ("OE2", "in", "-")];
    let names: Vec<(String, String)> = (1..=8)
        .map(|i| (format!("A{i}"), format!("Y{i}")))
        .collect();
    for (i, (a, _)) in names.iter().enumerate() {
        pins.push((a, "in", if i == 0 { a1 } else { "-" }));
    }
    for (i, (_, y)) in names.iter().enumerate() {
        pins.push((y, "tri", if i == 0 { y1 } else { "-" }));
    }
    c.chip(
        reference,
        "buf541",
        &pins,
        &[("A->Y", d.0), ("OE->Y en", d.1), ("OE->Y dis", d.2)],
    );
}

#[test]
fn changes_propagate_with_each_gates_delay() {
    let mut c = Circuit::default();
    c.sources(&["a"]);
    let nand = [
        ("1A", "in", "a"),
        ("1B", "in", "a"),
        ("1Y", "out", "b"),
        ("2A", "in", "b"),
        ("2B", "in", "b"),
        ("2Y", "out", "c"),
    ];
    c.chip("U1", "nand", &nand, &[("A->Y", 10_000)]);
    let mut sim = c.build();
    sim.run(50_000);
    assert_eq!(val(&sim, "b"), (1, 0));
    assert_eq!(val(&sim, "c"), (0, 10_000));
    set(&mut sim, "a", 100_000, 1);
    sim.run(200_000);
    assert_eq!(val(&sim, "b"), (0, 110_000));
    assert_eq!(val(&sim, "c"), (1, 120_000));
}

#[test]
fn an_earlier_change_waits_for_a_later_one_pending() {
    let mut c = Circuit::default();
    c.sources(&["a"]);
    let mut sim = c.build();
    set(&mut sim, "a", 200_000, 1);
    set(&mut sim, "a", 100_000, 1);
    sim.run(150_000);
    assert_eq!(val(&sim, "a").0, 0);
    sim.run(250_000);
    assert_eq!(val(&sim, "a"), (1, 200_000));
    // and the pending change takes the newest value
    set(&mut sim, "a", 400_000, 0);
    set(&mut sim, "a", 300_000, 1);
    let events = sim.state.event_count;
    sim.run(500_000);
    assert_eq!(val(&sim, "a"), (1, 200_000));
    assert_eq!(sim.state.event_count, events);
}

#[test]
fn two_drivers_disagreeing_is_contention() {
    let mut c = Circuit::default();
    c.rails();
    c.sources(&["en2"]);
    buf541(&mut c, "U1", "-", "hi", "bus", BUF541);
    buf541(&mut c, "U2", "en2", "lo", "bus", BUF541);
    let mut sim = c.build();
    sim.state.check_on = true;
    sim.run(20_000);
    assert!(sim.state.nets[sim.net("bus").unwrap() as usize].cont_since == Some(5000));
    set(&mut sim, "en2", 30_000, 1);
    sim.run(50_000);
    let cont = &sim.state.contention;
    assert_eq!(
        (cont.count, cont.max, cont.nets["bus"]),
        (1, 33_000, 33_000)
    );
    assert_eq!(cont.hist, [0, 0, 0, 0, 1, 0]);
    assert_eq!(val(&sim, "bus"), (1, 38_000));
}

#[test]
fn contention_for_no_time_is_counted_but_names_no_net() {
    // s enables U1's 1 and disables U2's 0 at the same instant
    let mut c = Circuit::default();
    c.rails();
    c.sources(&["s"]);
    buf541(&mut c, "U1", "-", "s", "bus", (0, 10_000, 0));
    buf541(&mut c, "U2", "s", "lo", "bus", (0, 10_000, 0));
    let mut sim = c.build();
    sim.state.check_on = true;
    set(&mut sim, "s", 1000, 1);
    sim.run(50_000);
    let cont = &sim.state.contention;
    assert_eq!((cont.count, cont.total, cont.hist[0]), (1, 0, 1));
    assert!(cont.nets.is_empty());
    assert_eq!(val(&sim, "bus"), (1, 1000));
}

#[test]
fn setup_and_hold_violations() {
    let mut c = Circuit::default();
    c.rails();
    c.sources(&["d", "clk"]);
    let mut pins = vec![
        ("1D", "in", "d"),
        ("1CLK", "in", "clk"),
        ("1PRE", "in", "hi"),
        ("1CLR", "in", "hi"),
        ("1Q", "out", "q"),
        ("1QN", "out", "-"),
    ];
    pins.extend(
        [
            ("2D", "in"),
            ("2CLK", "in"),
            ("2PRE", "in"),
            ("2CLR", "in"),
            ("2Q", "out"),
            ("2QN", "out"),
        ]
        .map(|(p, k)| (p, k, "-")),
    );
    let delays = [
        ("CLK->Q", 15_000),
        ("PRE/CLR->Q", 12_000),
        ("setup D", 20_000),
        ("hold D", 5000),
    ];
    c.chip("U1", "dff74", &pins, &delays);
    let mut sim = c.build();
    sim.state.check_on = true;
    // clock in a 0 first, so that Q visibly changes later
    set(&mut sim, "clk", 50_000, 1);
    set(&mut sim, "clk", 70_000, 0);
    set(&mut sim, "d", 95_000, 1);
    set(&mut sim, "clk", 100_000, 1);
    set(&mut sim, "d", 102_000, 0);
    sim.run(200_000);
    let v: Vec<_> = sim
        .state
        .violations
        .iter()
        .map(|v| {
            (
                v.chip.as_str(),
                v.pin.as_str(),
                v.net.as_str(),
                v.kind.as_str(),
                v.at_ps,
                v.slack_ps,
            )
        })
        .collect();
    assert_eq!(
        v,
        [
            ("U1", "1D", "d", "setup D", 100_000, -15_000),
            ("U1", "1D", "d", "hold D", 102_000, -3000)
        ]
    );
    assert_eq!(sim.state.violation_stats["U1.1D setup D"], (1, -15_000));
    assert_eq!(val(&sim, "q"), (1, 115_000));
}

#[test]
fn netlist_errors_name_the_chip() {
    let err = |model: &str, pins: &[(&str, &str, &str)]| {
        let mut c = Circuit::default();
        c.chip("U9", model, pins, &[]);
        let nl = Netlist {
            nets: c.nets,
            chips: c.chips,
        };
        build(&nl, &HashMap::new(), &mut Rng::new(1))
            .err()
            .unwrap()
            .0
    };
    assert_eq!(err("nand9", &[]), "U9: unknown model \"nand9\"");
    assert_eq!(err("cmp688", &[("G", "in", "-")]), "U9 (cmp688): no pin P0");
    assert_eq!(
        err("nand", &[("1A", "in", "a"), ("1Y", "out", "b")]),
        "U9 (nand): no timing value \"A->Y\""
    );
}
