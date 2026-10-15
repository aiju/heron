//! The vector fixture: a script played against a clock, with steps that
//! wait for what the fixture has seen, and the record of its inputs.

use std::collections::HashMap;

use hwsim::machine::{ChipDesc, Netlist, build};
use hwsim::rng::Rng;

fn chip(
    reference: &str,
    model: &str,
    pins: &[(&str, &str, i64)],
    params: &[(&str, i64)],
) -> ChipDesc {
    ChipDesc {
        reference: reference.into(),
        model: model.into(),
        part: model.into(),
        pins: pins.iter().map(|p| p.0.to_string()).collect(),
        kinds: pins.iter().map(|p| p.1.to_string()).collect(),
        nets: pins.iter().map(|p| p.2).collect(),
        delays: HashMap::new(),
        params: params.iter().map(|&(k, v)| (k.to_string(), v)).collect(),
        nocheck: false,
    }
}

#[test]
fn a_step_waits_for_its_condition() {
    // nets: 0 clk, 1 go, 2 o
    let nl = Netlist {
        nets: vec!["clk".into(), "go".into(), "o".into()],
        chips: vec![
            chip(
                "SRC",
                "clockgen",
                &[("CLK", "out", 0), ("GO", "out", 1)],
                &[],
            ),
            chip(
                "V",
                "vector",
                &[
                    ("CLK", "in", 0),
                    ("O0", "tri", 2),
                    ("I0", "in", 2),
                    ("I1", "in", 1),
                ],
                &[("outs", 1), ("ins", 2), ("conds", 1), ("delay_ps", 5000)],
            ),
        ],
    };
    // step 0: o = 0; step 1: o = 1 until go (input 1) is 1; step 2: let go
    let script = vec![0, 0, 1, 1 + 2 + 1, 2, 0];
    let pre = HashMap::from([("V", script)]);
    let mut sim = build(&nl, &pre, &mut Rng::new(1)).unwrap();
    let src = sim.chip("SRC").unwrap();
    let out = |sim: &hwsim::sim::Sim, p: usize| sim.chips[src].info.outs[p].unwrap();
    let (clk, go) = (out(&sim, 0), out(&sim, 1));
    sim.state.schedule(go, 0, 0, true);
    for k in 0..4 {
        sim.state.schedule(clk, 20_000 * k + 10_000, 1, true);
        sim.state.schedule(clk, 20_000 * k + 20_000, 0, true);
    }
    sim.state.schedule(go, 45_000, 1, true);
    sim.run(16_000);
    let o = sim.net("o").unwrap() as usize;
    assert_eq!(sim.state.nets[o].val, 1);
    assert_eq!(sim.state.nets[o].last, 15_000);
    sim.run(100_000);
    let v = sim.chip("V").unwrap();
    // (o, go) at the edges at 10, 30, 50 and 70 ns: step 1 held at 30,
    // moved on at 50
    let log = sim.chips[v].model.dump().unwrap();
    assert_eq!(&log[..6], &[0, 0, 1, 0, 1, 1]);
    assert!(sim.state.nets[o].float);
}
