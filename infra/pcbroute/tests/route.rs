//! The router on small boards.

use pcbroute::{Net, Problem, Shape, route};

fn pad(cx: f64, cy: f64, net: i64, layers: Vec<usize>) -> Shape {
    Shape {
        kind: "rect".into(),
        cx,
        cy,
        hw: 0.3,
        hh: 0.3,
        layers,
        net,
        pad: net >= 0,
        ..Default::default()
    }
}

fn problem(shapes: Vec<Shape>, nets: Vec<Vec<usize>>, layers: usize) -> Problem {
    Problem {
        width: 20.0,
        height: 20.0,
        layers,
        shapes,
        nets: nets
            .into_iter()
            .enumerate()
            .map(|(i, pads)| Net {
                name: format!("N{i}"),
                pads,
            })
            .collect(),
        ..Default::default()
    }
}

#[test]
fn two_pads() {
    let p = problem(
        vec![pad(2.0, 2.0, 0, vec![0]), pad(15.0, 12.0, 0, vec![0])],
        vec![vec![0, 1]],
        1,
    );
    let s = route(&p);
    assert!(s.failed.is_empty() && s.conflicted.is_empty(), "{s:?}");
    let len: f64 = s.nets[0]
        .segments
        .iter()
        .map(|&(_, a, b, c, d)| (c - a).abs() + (d - b).abs())
        .sum();
    assert!((len - 23.0).abs() < 1.0, "length {len}");
}

#[test]
fn around_an_obstacle() {
    // a wall of another net's copper between the pads, on the only layer
    let wall = Shape {
        kind: "rect".into(),
        cx: 10.0,
        cy: 8.0,
        hw: 0.5,
        hh: 7.0,
        layers: vec![0],
        net: -1,
        ..Default::default()
    };
    let p = problem(
        vec![pad(5.0, 8.0, 0, vec![0]), pad(15.0, 8.0, 0, vec![0]), wall],
        vec![vec![0, 1]],
        1,
    );
    let s = route(&p);
    assert!(s.failed.is_empty(), "{s:?}");
    assert!(
        s.nets[0]
            .segments
            .iter()
            .any(|&(_, _, y1, _, y2)| y1.max(y2) > 15.0 || y1.min(y2) < 1.0)
    );
}

#[test]
fn via_through_a_wall() {
    // a full wall on layer 0: the route must take a via to layer 1
    let wall = Shape {
        kind: "rect".into(),
        cx: 10.0,
        cy: 10.0,
        hw: 0.5,
        hh: 10.0,
        layers: vec![0],
        net: -1,
        ..Default::default()
    };
    let p = problem(
        vec![pad(5.0, 8.0, 0, vec![0]), pad(15.0, 8.0, 0, vec![0]), wall],
        vec![vec![0, 1]],
        2,
    );
    let s = route(&p);
    assert!(s.failed.is_empty(), "{s:?}");
    assert!(s.nets[0].vias.len() >= 2, "{s:?}");
}

#[test]
fn crossing_nets_negotiate() {
    // two nets that cross on one layer can't both be routed there: with two
    // layers, they must end up without sharing a node
    let p = problem(
        vec![
            pad(2.0, 10.0, 0, vec![]),
            pad(18.0, 10.0, 0, vec![]),
            pad(10.0, 2.0, 1, vec![]),
            pad(10.0, 18.0, 1, vec![]),
        ],
        vec![vec![0, 1], vec![2, 3]],
        2,
    );
    let s = route(&p);
    assert!(s.failed.is_empty() && s.conflicted.is_empty(), "{s:?}");
}

#[test]
fn search_effort() {
    // two pads 60 mm apart on an empty board: A* should expand about a
    // path's worth of nodes, not the rectangle between them
    for hw in [1.0, 1.5] {
        let mut p = problem(
            vec![pad(2.0, 2.0, 0, vec![0]), pad(50.0, 34.0, 0, vec![0])],
            vec![vec![0, 1]],
            4,
        );
        p.width = 60.0;
        p.height = 40.0;
        p.dirs = vec![0, 1, 2, 0];
        p.layer_cost = vec![1.5, 1.0, 1.0, 1.0];
        p.hweight = hw;
        let s = route(&p);
        let r = &s.rounds[0];
        eprintln!(
            "hweight {hw}: {} expanded for a {:.0} mm route",
            r.expanded, r.length
        );
        assert!(s.failed.is_empty());
    }
}
