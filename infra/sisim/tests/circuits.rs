//! Circuits with answers known in closed form.

use sisim::{Capacitor, Diode, Fixed, Inductor, Line, Netlist, Options, Resistor, Table, run};

fn opts(dt: f64, tstop: f64, probes: Vec<(usize, usize)>) -> Options {
    Options {
        dt,
        tstop,
        probes,
        every: 1,
        max_newton: 50,
        vtol: 1e-9,
        max_seconds: 60.0,
    }
}

/// A 1 V step at t = 0 (well, over the first picosecond) on node `node`.
fn step(node: usize) -> Fixed {
    Fixed {
        node,
        wave: vec![(0.0, 0.0), (1e-12, 1.0)],
    }
}

fn r(a: usize, b: usize, r: f64) -> Resistor {
    Resistor { a, b, r }
}

/// Probe p at time t, interpolated.
fn at(out: &sisim::Output, probes: usize, p: usize, t: f64) -> f64 {
    let i = out
        .time
        .partition_point(|&x| x < t)
        .min(out.time.len() - 1)
        .max(1);
    let (t0, t1) = (out.time[i - 1], out.time[i]);
    let (v0, v1) = (out.data[(i - 1) * probes + p], out.data[i * probes + p]);
    v0 + (v1 - v0) * (t - t0) / (t1 - t0)
}

fn single(a: usize, b: usize, z: f64, delay: f64) -> Line {
    Line {
        end1: vec![a],
        ref1: 0,
        end2: vec![b],
        ref2: 0,
        tv: vec![vec![1.0]],
        z: vec![z],
        delay: vec![delay],
    }
}

#[test]
fn rc_charges_exponentially() {
    let net = Netlist {
        nodes: 3,
        fixed: vec![step(1)],
        resistors: vec![r(1, 2, 1e3)],
        capacitors: vec![Capacitor {
            a: 2,
            b: 0,
            c: 1e-12,
        }],
        ..Default::default()
    };
    let out = run(&net, &opts(1e-12, 5e-9, vec![(2, 0)]), &mut || false).unwrap();
    for t in [0.5e-9, 1e-9, 2e-9, 4e-9] {
        let want = 1.0 - (-(t - 0.5e-12) / 1e-9f64).exp();
        let got = at(&out, 1, 0, t);
        assert!((got - want).abs() < 2e-3, "t = {t:e}: {got} vs {want}");
    }
}

#[test]
fn matched_line_delays_half_the_step() {
    // source, 50 ohm, 1 ns of 50 ohm line, 50 ohm load
    let net = Netlist {
        nodes: 4,
        fixed: vec![step(1)],
        resistors: vec![r(1, 2, 50.0), r(3, 0, 50.0)],
        lines: vec![single(2, 3, 50.0, 1e-9)],
        ..Default::default()
    };
    let out = run(&net, &opts(5e-12, 3e-9, vec![(2, 0), (3, 0)]), &mut || {
        false
    })
    .unwrap();
    assert!((at(&out, 2, 0, 0.5e-9) - 0.5).abs() < 1e-6);
    assert!(at(&out, 2, 1, 0.99e-9).abs() < 1e-6);
    assert!((at(&out, 2, 1, 1.1e-9) - 0.5).abs() < 1e-6);
    assert!((at(&out, 2, 0, 2.9e-9) - 0.5).abs() < 1e-6);
}

#[test]
fn open_line_doubles_and_reflects() {
    let net = Netlist {
        nodes: 4,
        fixed: vec![step(1)],
        resistors: vec![r(1, 2, 50.0)],
        lines: vec![single(2, 3, 50.0, 1e-9)],
        ..Default::default()
    };
    let out = run(&net, &opts(5e-12, 3e-9, vec![(2, 0), (3, 0)]), &mut || {
        false
    })
    .unwrap();
    assert!((at(&out, 2, 0, 1.5e-9) - 0.5).abs() < 1e-6);
    assert!((at(&out, 2, 1, 1.5e-9) - 1.0).abs() < 1e-6);
    assert!((at(&out, 2, 0, 2.5e-9) - 1.0).abs() < 1e-6);
}

#[test]
fn lc_rings_at_its_resonance() {
    // a step into series L and C: v_C = 1 − cos(ωt)
    let (l, c) = (1e-9, 1e-12);
    let net = Netlist {
        nodes: 3,
        fixed: vec![step(1)],
        inductors: vec![Inductor { a: 1, b: 2, l }],
        capacitors: vec![Capacitor { a: 2, b: 0, c }],
        ..Default::default()
    };
    let w = 1.0 / (l * c).sqrt();
    let out = run(&net, &opts(0.5e-12, 1e-9, vec![(2, 0)]), &mut || false).unwrap();
    for t in [0.05e-9, 0.1e-9, 0.3e-9, 0.6e-9] {
        let want = 1.0 - (w * (t - 0.5e-12)).cos();
        let got = at(&out, 1, 0, t);
        assert!((got - want).abs() < 0.02, "t = {t:e}: {got} vs {want}");
    }
}

#[test]
fn coupled_lines_match_their_even_mode() {
    // two symmetric coupled lines, driven together through the even-mode
    // impedance and loaded with it: no reflection, half the step arrives
    // after the even-mode delay
    let (l, m, c, cm): (f64, f64, f64, f64) = (400e-9, 100e-9, 100e-12, 20e-12); // per metre, Maxwell C: [[c, -cm], [-cm, c]]
    let len: f64 = 0.2;
    // modes normalised so that Tvᵀ·C·Tv = I: columns along (1, 1) and (1, −1)
    let ae = 1.0 / (2.0 * (c - cm)).sqrt();
    let ao = 1.0 / (2.0 * (c + cm)).sqrt();
    let tv = vec![vec![ae, ao], vec![ae, -ao]];
    // with this normalisation Tv⁻¹ = Tvᵀ·C, so Lm = Tvᵀ·C·L·C·Tv is the
    // diagonal of the even- and odd-mode L·C products
    let le = (l + m) * (c - cm);
    let lo = (l - m) * (c + cm);
    let (ze, zo) = (le.sqrt(), lo.sqrt());
    let (te, to) = (len * le.sqrt(), len * lo.sqrt());
    let z_even = ((l + m) / (c - cm)).sqrt();
    let t_even = len * ((l + m) * (c - cm)).sqrt();
    assert!((te - t_even).abs() < 1e-15);
    let net = Netlist {
        nodes: 6,
        fixed: vec![step(1)],
        resistors: vec![
            r(1, 2, z_even),
            r(1, 3, z_even),
            r(4, 0, z_even),
            r(5, 0, z_even),
        ],
        lines: vec![Line {
            end1: vec![2, 3],
            ref1: 0,
            end2: vec![4, 5],
            ref2: 0,
            tv,
            z: vec![ze, zo],
            delay: vec![te, to],
        }],
        ..Default::default()
    };
    let out = run(
        &net,
        &opts(2e-12, 3.0 * t_even, vec![(2, 0), (4, 0), (5, 0)]),
        &mut || false,
    )
    .unwrap();
    assert!((at(&out, 3, 0, 0.5 * t_even) - 0.5).abs() < 1e-6);
    assert!(at(&out, 3, 1, 0.98 * t_even).abs() < 1e-6);
    assert!((at(&out, 3, 1, 1.05 * t_even) - 0.5).abs() < 1e-6);
    assert!((at(&out, 3, 2, 2.5 * t_even) - 0.5).abs() < 1e-6);
}

#[test]
fn diode_operating_point() {
    // 1 V through 100 ohm into a diode: I = (1 − Vd)/100 = Is·(exp(Vd/Vt) − 1)
    let d = Diode {
        a: 2,
        b: 0,
        is: 1e-14,
        n: 1.0,
        cjo: 0.0,
        vj: 1.0,
        m: 0.5,
        fc: 0.5,
    };
    let net = Netlist {
        nodes: 3,
        fixed: vec![Fixed {
            node: 1,
            wave: vec![(0.0, 1.0)],
        }],
        resistors: vec![r(1, 2, 100.0)],
        diodes: vec![d],
        ..Default::default()
    };
    let out = run(&net, &opts(1e-12, 2e-12, vec![(2, 0)]), &mut || false).unwrap();
    let vd = out.data[0];
    let i_r = (1.0 - vd) / 100.0;
    let i_d = 1e-14 * ((vd / 0.025865).exp() - 1.0);
    assert!((i_r - i_d).abs() < 1e-9, "{vd}: {i_r} vs {i_d}");
}

#[test]
fn a_linear_table_is_a_resistor() {
    // a table I = V/100 from node 2 to ground, switched on by its
    // coefficient at 1 ns
    let net = Netlist {
        nodes: 3,
        fixed: vec![Fixed {
            node: 1,
            wave: vec![(0.0, 1.0)],
        }],
        resistors: vec![r(1, 2, 100.0)],
        tables: vec![Table {
            a: 2,
            b: 0,
            x: 2,
            y: 0,
            coef: Some(vec![(0.0, 0.0), (1e-9, 0.0), (1.001e-9, 1.0)]),
            table: vec![(-1.0, -0.01), (1.0, 0.01)],
            supply: None,
        }],
        ..Default::default()
    };
    let out = run(&net, &opts(1e-12, 2e-9, vec![(2, 0)]), &mut || false).unwrap();
    assert!((at(&out, 1, 0, 0.5e-9) - 1.0).abs() < 1e-6);
    assert!((at(&out, 1, 0, 1.5e-9) - 0.5).abs() < 1e-6);
    assert_eq!(out.stats.nonconverged, 0);
}

#[test]
fn rejects_a_line_shorter_than_the_step() {
    let net = Netlist {
        nodes: 3,
        lines: vec![single(1, 2, 50.0, 1e-12)],
        ..Default::default()
    };
    assert!(run(&net, &opts(5e-12, 1e-9, vec![]), &mut || false).is_err());
}

#[test]
fn a_supply_factor_scales_a_table() {
    // a 100 ohm table resistor whose current is scaled by s(V(3)) = V(3)/2:
    // with node 3 at 4 V it is 50 ohm, against 100 ohm in series from 1 V
    for (vs, want) in [(2.0, 0.5), (4.0, 1.0 / 3.0)] {
        let net = Netlist {
            nodes: 4,
            fixed: vec![
                Fixed {
                    node: 1,
                    wave: vec![(0.0, 1.0)],
                },
                Fixed {
                    node: 3,
                    wave: vec![(0.0, vs)],
                },
            ],
            resistors: vec![r(1, 2, 100.0)],
            tables: vec![Table {
                a: 2,
                b: 0,
                x: 2,
                y: 0,
                coef: None,
                table: vec![(-1.0, -0.01), (1.0, 0.01)],
                supply: Some(sisim::Supply {
                    p: 3,
                    q: 0,
                    table: vec![(0.0, 0.0), (4.0, 2.0)],
                }),
            }],
            ..Default::default()
        };
        let out = run(&net, &opts(1e-12, 1e-10, vec![(2, 0)]), &mut || false).unwrap();
        assert!(
            (out.data.last().unwrap() - want).abs() < 1e-6,
            "{vs}: {:?}",
            out.data.last()
        );
    }
}
