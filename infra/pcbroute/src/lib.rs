//! A grid router for printed circuit boards.
//!
//! The routing layers are a 3-D grid of nodes whose pitch is a track's
//! width plus the clearance, so tracks of different nets may run on
//! neighbouring grid lines and only a node can be shared. Tracks run along
//! grid lines; a through via joins every layer at a node, and keeps tracks
//! of other nets out of the nodes around it on every layer (its
//! footprint).
//!
//! Pads and fixed copper are rasterised once: a node too close to another
//! net's copper belongs to that net (or to none, if two nets claim it), a
//! node inside a pad is one of the pad's terminals, and a node where a via
//! would come too close to copper (or touch any pad) may not have one.
//!
//! The nets are routed by negotiated congestion (PathFinder, McMurchie and
//! Ebeling 1995): every net is routed on its own, sharing nodes at a cost
//! that grows with each iteration, and nodes that stay over-used grow a
//! history cost, until no node is used by two nets. After the first round
//! only the nets still in conflict are routed again.
//!
//! A net with several pads is grown as a tree, in Prim's order: A* from
//! everything routed so far to the one pad nearest it, then the next. Two
//! things keep the searches small: the heuristic counts the via still
//! needed to reach a pad on another layer, and it is weighted a little
//! (hweight), so a search runs at its target rather than flooding the
//! box around it. A search stays near its net's bounding box (window)
//! unless that fails.
//!
//! Obstacles are tested at the nodes only; a track between two nodes can
//! pass a round obstacle a little closer than either node, so every
//! keep-out has a small slack.

mod geom;

use std::cmp::Ordering;
use std::collections::BinaryHeap;
use std::time::Instant;

pub use geom::{Shape, seg_dist};
use serde::{Deserialize, Serialize};

const FREE: i32 = -1;
const BLOCKED: i32 = -2;
const NONE: u32 = u32::MAX;

/// A net: its pads, as indices into the problem's shapes.
#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct Net {
    pub name: String,
    pub pads: Vec<usize>,
}

/// What to route, and how. Lengths in millimetres; the grid's origin is
/// the board's top left corner.
#[derive(Clone, Debug, Deserialize)]
#[serde(default)]
pub struct Problem {
    pub width: f64,
    pub height: f64,
    /// the grid pitch: a track's width plus the clearance
    pub pitch: f64,
    /// the number of routing layers
    pub layers: usize,
    /// per layer: 0 any direction, 1 horizontal, 2 vertical preferred
    pub dirs: Vec<u8>,
    /// per layer: a step's cost (at least 1)
    pub layer_cost: Vec<f64>,
    pub track: f64,
    pub clearance: f64,
    pub via_dia: f64,
    /// clearance to the board's edge
    pub edge: f64,
    /// added to every keep-out: a track runs between grid nodes, where it
    /// can pass a round obstacle a little closer than at either node
    pub slack: f64,
    pub shapes: Vec<Shape>,
    pub nets: Vec<Net>,
    /// the most rounds of rip-up and reroute
    pub iterations: usize,
    /// a via's cost, in steps
    pub via_cost: f64,
    /// a step against a layer's direction costs this many steps
    pub wrong_way: f64,
    /// the cost of sharing a node: first round, and its growth per round
    pub pres_fac: f64,
    pub pres_mult: f64,
    /// how much a round of over-use adds to a node's history cost
    pub hist_fac: f64,
    /// how far (mm) a search may stray outside its net's bounding box
    /// before it is retried on the whole board
    pub window: f64,
    /// the A* heuristic's weight: above 1 trades optimal paths for speed
    pub hweight: f64,
    pub verbose: bool,
}

impl Default for Problem {
    fn default() -> Self {
        Problem {
            width: 100.0,
            height: 100.0,
            pitch: 0.254,
            layers: 2,
            dirs: vec![],
            layer_cost: vec![],
            track: 0.127,
            clearance: 0.127,
            via_dia: 0.45,
            edge: 0.5,
            slack: 0.02,
            shapes: vec![],
            nets: vec![],
            iterations: 50,
            via_cost: 8.0,
            wrong_way: 3.0,
            pres_fac: 0.5,
            pres_mult: 1.6,
            hist_fac: 0.3,
            window: 12.0,
            hweight: 1.5,
            verbose: false,
        }
    }
}

/// A routed net: its tracks (layer, x1, y1, x2, y2) and vias (x, y), in
/// millimetres, and whether all its pads were reached.
#[derive(Clone, Debug, Default, Serialize)]
pub struct NetRoute {
    pub name: String,
    pub segments: Vec<(usize, f64, f64, f64, f64)>,
    pub vias: Vec<(f64, f64)>,
    pub routed: bool,
}

/// One round of rip-up and reroute.
#[derive(Clone, Debug, Default, Serialize)]
pub struct Round {
    pub rerouted: usize,
    pub overused: usize,
    pub conflicted_nets: usize,
    pub length: f64,
    pub vias: usize,
    pub seconds: f64,
    /// A* searches, nodes expanded, and searches retried on the whole board
    pub searches: u64,
    pub expanded: u64,
    pub retried: u64,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct Solution {
    pub nets: Vec<NetRoute>,
    pub rounds: Vec<Round>,
    /// nets with a pad the grid can't reach (no terminal node)
    pub unreachable: Vec<String>,
    /// nets that are routed but still share nodes with another
    pub conflicted: Vec<String>,
    /// nets that could not be completed even ignoring congestion
    pub failed: Vec<String>,
    pub nodes: usize,
}

struct Grid {
    nx: usize,
    ny: usize,
    nl: usize,
    pitch: f64,
    owner: Vec<i32>,
    term: Vec<i32>,
    vowner: Vec<i32>,
}

impl Grid {
    fn node(&self, l: usize, x: usize, y: usize) -> usize {
        (l * self.ny + y) * self.nx + x
    }
    fn split(&self, n: usize) -> (usize, usize, usize) {
        let x = n % self.nx;
        let y = (n / self.nx) % self.ny;
        let l = n / (self.nx * self.ny);
        (l, x, y)
    }
    fn pos(&self, x: usize, y: usize) -> (f64, f64) {
        (x as f64 * self.pitch, y as f64 * self.pitch)
    }
    /// The nodes (x, y) within `margin` of a box.
    fn span(&self, b: (f64, f64, f64, f64), margin: f64) -> (usize, usize, usize, usize) {
        let p = self.pitch;
        let x0 = ((b.0 - margin) / p).floor().max(0.0) as usize;
        let y0 = ((b.1 - margin) / p).floor().max(0.0) as usize;
        let x1 = (((b.2 + margin) / p).ceil() as usize).min(self.nx - 1);
        let y1 = (((b.3 + margin) / p).ceil() as usize).min(self.ny - 1);
        (x0, y0, x1, y1)
    }
}

fn claim(cell: &mut i32, net: i64) {
    let want = if net < 0 { BLOCKED } else { net as i32 };
    *cell = match *cell {
        FREE => want,
        c if c == want => c,
        _ => BLOCKED,
    };
}

fn build_grid(p: &Problem) -> Grid {
    let nx = (p.width / p.pitch).floor() as usize + 1;
    let ny = (p.height / p.pitch).floor() as usize + 1;
    let nl = p.layers;
    let mut g = Grid {
        nx,
        ny,
        nl,
        pitch: p.pitch,
        owner: vec![FREE; nx * ny * nl],
        term: vec![-1; nx * ny * nl],
        vowner: vec![FREE; nx * ny],
    };
    let keep = p.clearance + p.track / 2.0 + p.slack;
    let via_r = p.via_dia / 2.0;
    let vkeep = via_r + p.clearance + p.slack;
    // the board's edge
    for y in 0..ny {
        for x in 0..nx {
            let (px, py) = g.pos(x, y);
            let d = px.min(py).min(p.width - px).min(p.height - py);
            if d < p.edge + p.track / 2.0 {
                for l in 0..nl {
                    let n = g.node(l, x, y);
                    g.owner[n] = BLOCKED;
                }
            }
            if d < p.edge + via_r {
                g.vowner[y * nx + x] = BLOCKED;
            }
        }
    }
    for (si, s) in p.shapes.iter().enumerate() {
        let (x0, y0, x1, y1) = g.span(s.bbox(), vkeep.max(keep) + p.pitch);
        for y in y0..=y1 {
            for x in x0..=x1 {
                let (px, py) = g.pos(x, y);
                let d = s.dist(px, py);
                for l in 0..nl {
                    if !s.on(l) {
                        continue;
                    }
                    let n = g.node(l, x, y);
                    if s.pad && d <= 1e-9 && s.net >= 0 {
                        g.term[n] = if g.term[n] < 0 || g.term[n] == si as i32 {
                            si as i32
                        } else if p.shapes[g.term[n] as usize].net == s.net {
                            g.term[n]
                        } else {
                            -2
                        };
                    }
                    if d < keep - 1e-9 {
                        claim(&mut g.owner[n], s.net);
                    }
                }
                // a via goes through every layer: any copper counts
                if d < vkeep - 1e-9 {
                    let v = &mut g.vowner[y * nx + x];
                    if s.pad && d < via_r + 1e-9 {
                        *v = BLOCKED;
                    } else {
                        claim(v, s.net);
                    }
                }
            }
        }
    }
    g
}

/// A heap entry: the estimate f, the cost so far g (ties go to the
/// larger g, the node nearer the target), the node.
#[derive(PartialEq)]
struct Item(f32, f32, u32);
impl Eq for Item {}
impl PartialOrd for Item {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}
impl Ord for Item {
    fn cmp(&self, o: &Self) -> Ordering {
        o.0.total_cmp(&self.0)
            .then(self.1.total_cmp(&o.1))
            .then(o.2.cmp(&self.2))
    }
}

struct Router<'a> {
    p: &'a Problem,
    g: Grid,
    occ: Vec<u16>,
    hist: Vec<f32>,
    pres: f32,
    // A* scratch
    cost: Vec<f32>,
    from: Vec<u32>,
    stamp: Vec<u32>,
    search: u32,
    // the via footprint: offsets (dx, dy) of the nodes it keeps from other nets
    foot: Vec<(i64, i64)>,
    // per net: the nodes it uses (tracks and via footprints), its path
    // nodes in order (for output), and its vias (node index on layer 0)
    used: Vec<Vec<u32>>,
    paths: Vec<Vec<Vec<u32>>>,
    vias: Vec<Vec<u32>>,
    terms: Vec<Vec<u32>>,
    mark: Vec<u32>,
    mark_id: u32,
    searches: u64,
    expanded: u64,
    retried: u64,
}

impl<'a> Router<'a> {
    fn new(p: &'a Problem) -> Self {
        let g = build_grid(p);
        let n = g.owner.len();
        // nodes (tracks of other nets) a via keeps clear: centre distance
        // under via radius + clearance + half a track
        let reach = (p.via_dia / 2.0 + p.clearance + p.track / 2.0) / p.pitch;
        let k = reach.ceil() as i64;
        let mut foot = vec![];
        for dy in -k..=k {
            for dx in -k..=k {
                if ((dx * dx + dy * dy) as f64).sqrt() < reach - 1e-9 {
                    foot.push((dx, dy));
                }
            }
        }
        // each pad's terminal nodes
        let mut terms = vec![vec![]; p.shapes.len()];
        for (i, &t) in g.term.iter().enumerate() {
            if t >= 0 {
                terms[t as usize].push(i as u32);
            }
        }
        let nn = p.nets.len();
        Router {
            p,
            occ: vec![0; n],
            hist: vec![0.0; n],
            pres: p.pres_fac as f32,
            cost: vec![0.0; n],
            from: vec![NONE; n],
            stamp: vec![0; n],
            search: 0,
            foot,
            used: vec![vec![]; nn],
            paths: vec![vec![]; nn],
            vias: vec![vec![]; nn],
            terms,
            mark: vec![0; n],
            mark_id: 0,
            searches: 0,
            expanded: 0,
            retried: 0,
            g,
        }
    }

    fn rip_up(&mut self, net: usize) {
        for &n in &self.used[net] {
            self.occ[n as usize] -= 1;
        }
        self.used[net].clear();
        self.paths[net].clear();
        self.vias[net].clear();
    }

    fn commit(&mut self, net: usize) {
        self.mark_id += 1;
        let id = self.mark_id;
        let mut used = vec![];
        let g = &self.g;
        let mut add = |n: usize, mark: &mut Vec<u32>| {
            if mark[n] != id {
                mark[n] = id;
                used.push(n as u32);
            }
        };
        for path in &self.paths[net] {
            for &n in path {
                add(n as usize, &mut self.mark);
            }
        }
        for &v in &self.vias[net] {
            let (_, x, y) = g.split(v as usize);
            for &(dx, dy) in &self.foot {
                let (xx, yy) = (x as i64 + dx, y as i64 + dy);
                if xx < 0 || yy < 0 || xx >= g.nx as i64 || yy >= g.ny as i64 {
                    continue;
                }
                for l in 0..g.nl {
                    add(g.node(l, xx as usize, yy as usize), &mut self.mark);
                }
            }
        }
        for &n in &used {
            self.occ[n as usize] += 1;
        }
        self.used[net] = used;
    }

    /// Route one net; false if a pad couldn't be reached at all.
    fn route_net(&mut self, net: usize) -> bool {
        let p = self.p;
        let pads: Vec<usize> = p.nets[net]
            .pads
            .iter()
            .copied()
            .filter(|&s| !self.terms[s].is_empty())
            .collect();
        if pads.len() < 2 {
            return true;
        }
        let mut tree: Vec<u32> = self.terms[pads[0]].clone();
        let mut left: Vec<usize> = pads[1..].to_vec();
        let mut ok = true;
        while !left.is_empty() {
            // the pad nearest the tree next (Prim's order), searched for alone
            let g = &self.g;
            let centre = |s: usize| -> (i64, i64) {
                let t = &self.terms[s];
                let (_, x, y) = g.split(t[t.len() / 2] as usize);
                (x as i64, y as i64)
            };
            let step = (tree.len() / 256).max(1);
            let pad = *left
                .iter()
                .min_by_key(|&&q| {
                    let (qx, qy) = centre(q);
                    tree.iter()
                        .step_by(step)
                        .map(|&n| {
                            let (_, x, y) = g.split(n as usize);
                            (x as i64 - qx).abs() + (y as i64 - qy).abs()
                        })
                        .min()
                        .unwrap_or(0)
                })
                .unwrap();
            let target = [pad];
            let mut found = self.search(net, &tree, &target, true);
            if found.is_none() {
                self.retried += 1;
                found = self.search(net, &tree, &target, false);
            }
            match found {
                Some((path, pad)) => {
                    // vias: where the path changes layer
                    for w in path.windows(2) {
                        let (la, xa, ya) = self.g.split(w[0] as usize);
                        let (lb, _, _) = self.g.split(w[1] as usize);
                        if la != lb {
                            self.vias[net].push(self.g.node(0, xa, ya) as u32);
                        }
                    }
                    tree.extend_from_slice(&path);
                    tree.extend_from_slice(&self.terms[pad]);
                    self.paths[net].push(path);
                    left.retain(|&q| q != pad);
                }
                None => {
                    ok = false;
                    break;
                }
            }
        }
        self.vias[net].sort_unstable();
        self.vias[net].dedup();
        ok
    }

    /// A* from the tree to the nearest node of a pad in `left`. Returns the
    /// path (tree end first) and the pad reached. `windowed` keeps the
    /// search near the net's own bounding box.
    fn search(
        &mut self,
        net: usize,
        tree: &[u32],
        left: &[usize],
        windowed: bool,
    ) -> Option<(Vec<u32>, usize)> {
        self.search += 1;
        self.searches += 1;
        let sid = self.search;
        let mut expanded = 0u64;
        let Router {
            p,
            g,
            occ,
            hist,
            pres,
            cost,
            from,
            stamp,
            foot,
            terms,
            ..
        } = self;
        let (p, g, occ, hist, pres, foot, terms) = (*p, &*g, &*occ, &*hist, *pres, &*foot, &*terms);
        let net_i = net as i32;
        let (nx, ny, nl) = (g.nx, g.ny, g.nl);
        // the targets' box, for the heuristic; with the tree's, the window
        let (mut tx0, mut ty0, mut tx1, mut ty1) = (usize::MAX, usize::MAX, 0usize, 0usize);
        // the layers the targets are on: from any other, a via is still to come
        let mut on_target_layer = vec![false; nl];
        for &pad in left {
            for &n in &terms[pad] {
                let (tl, x, y) = g.split(n as usize);
                on_target_layer[tl] = true;
                tx0 = tx0.min(x);
                ty0 = ty0.min(y);
                tx1 = tx1.max(x);
                ty1 = ty1.max(y);
            }
        }
        let (mut wx0, mut wy0, mut wx1, mut wy1) = (tx0, ty0, tx1, ty1);
        for &n in tree {
            let (_, x, y) = g.split(n as usize);
            wx0 = wx0.min(x);
            wy0 = wy0.min(y);
            wx1 = wx1.max(x);
            wy1 = wy1.max(y);
        }
        if windowed {
            let m = (p.window / p.pitch) as usize;
            wx0 = wx0.saturating_sub(m);
            wy0 = wy0.saturating_sub(m);
            wx1 = (wx1 + m).min(nx - 1);
            wy1 = (wy1 + m).min(ny - 1);
        } else {
            (wx0, wy0, wx1, wy1) = (0, 0, nx - 1, ny - 1);
        }
        let hw = p.hweight as f32;
        let via_h = p.via_cost as f32;
        let h = |l: usize, x: usize, y: usize| -> f32 {
            let dx = if x < tx0 {
                tx0 - x
            } else {
                x.saturating_sub(tx1)
            };
            let dy = if y < ty0 {
                ty0 - y
            } else {
                y.saturating_sub(ty1)
            };
            let v = if on_target_layer[l] { 0.0 } else { via_h };
            ((dx + dy) as f32 + v) * hw
        };
        let node_cost = |n: usize| -> f32 { (1.0 + hist[n]) * (1.0 + pres * occ[n] as f32) };
        let legal = |n: usize| -> bool {
            let o = g.owner[n];
            o == FREE || o == net_i
        };
        let via_extra = |x: usize, y: usize| -> f32 {
            let mut c = 0.0;
            for &(dx, dy) in foot {
                let (xx, yy) = (x as i64 + dx, y as i64 + dy);
                if xx < 0 || yy < 0 || xx >= nx as i64 || yy >= ny as i64 {
                    continue;
                }
                for l in 0..nl {
                    let n = g.node(l, xx as usize, yy as usize);
                    if occ[n] > 0 || hist[n] > 0.0 {
                        c += node_cost(n) - 1.0;
                    }
                }
            }
            c
        };
        let mut heap = BinaryHeap::new();
        for &n in tree {
            let n = n as usize;
            stamp[n] = sid;
            cost[n] = 0.0;
            from[n] = NONE;
            let (l, x, y) = g.split(n);
            heap.push(Item(h(l, x, y), 0.0, n as u32));
        }
        let ww = p.wrong_way as f32;
        let mut found = None;
        while let Some(Item(f, _, n)) = heap.pop() {
            let n = n as usize;
            let (l, x, y) = g.split(n);
            let c = cost[n];
            if f > c + h(l, x, y) + 1e-3 {
                continue; // a stale entry
            }
            expanded += 1;
            let t = g.term[n];
            if t >= 0 && left.contains(&(t as usize)) {
                found = Some((n, t as usize));
                break;
            }
            let lc = p.layer_cost.get(l).copied().unwrap_or(1.0) as f32;
            let dir = p.dirs.get(l).copied().unwrap_or(0);
            let mut relax = |nb: usize,
                             step: f32,
                             hl: usize,
                             hx: usize,
                             hy: usize,
                             heap: &mut BinaryHeap<Item>| {
                let nc = c + step * node_cost(nb);
                if stamp[nb] != sid || nc < cost[nb] {
                    stamp[nb] = sid;
                    cost[nb] = nc;
                    from[nb] = n as u32;
                    heap.push(Item(nc + h(hl, hx, hy), nc, nb as u32));
                }
            };
            let hcost = lc * if dir == 2 { ww } else { 1.0 };
            let vcost = lc * if dir == 1 { ww } else { 1.0 };
            if x > wx0 && legal(n - 1) {
                relax(n - 1, hcost, l, x - 1, y, &mut heap);
            }
            if x < wx1 && legal(n + 1) {
                relax(n + 1, hcost, l, x + 1, y, &mut heap);
            }
            if y > wy0 && legal(n - nx) {
                relax(n - nx, vcost, l, x, y - 1, &mut heap);
            }
            if y < wy1 && legal(n + nx) {
                relax(n + nx, vcost, l, x, y + 1, &mut heap);
            }
            // a via to every other layer
            let v = g.vowner[y * nx + x];
            if nl > 1 && (v == FREE || v == net_i) {
                let vc = p.via_cost as f32 + via_extra(x, y);
                for l2 in 0..nl {
                    let nb = g.node(l2, x, y);
                    if l2 != l && legal(nb) {
                        relax(nb, vc, l2, x, y, &mut heap);
                    }
                }
            }
        }
        self.expanded += expanded;
        if p.verbose && expanded > 300_000 {
            eprintln!(
                "  search for {}: {expanded} expanded, tree {}, {} pads left, window {}x{}, found {}",
                p.nets[net].name,
                tree.len(),
                left.len(),
                wx1 - wx0,
                wy1 - wy0,
                found.is_some()
            );
        }
        let (end, pad) = found?;
        let mut path = vec![end as u32];
        let mut n = end;
        while from[n] != NONE {
            n = from[n] as usize;
            path.push(n as u32);
        }
        path.reverse();
        Some((path, pad))
    }

    fn conflicts(&self, net: usize) -> bool {
        self.used[net].iter().any(|&n| self.occ[n as usize] > 1)
    }

    fn output(&self, net: usize) -> NetRoute {
        let g = &self.g;
        let mut segs = vec![];
        for path in &self.paths[net] {
            // runs of nodes on one layer in one direction become a segment
            let mut i = 0;
            while i + 1 < path.len() {
                let (la, xa, ya) = g.split(path[i] as usize);
                let (lb, _, _) = g.split(path[i + 1] as usize);
                if la != lb {
                    i += 1;
                    continue;
                }
                let mut j = i + 1;
                let (_, x1, y1) = g.split(path[j] as usize);
                let (ddx, ddy) = (x1 as i64 - xa as i64, y1 as i64 - ya as i64);
                while j + 1 < path.len() {
                    let (lc, xc, yc) = g.split(path[j + 1] as usize);
                    let (_, xb, yb) = g.split(path[j] as usize);
                    if lc != la || xc as i64 - xb as i64 != ddx || yc as i64 - yb as i64 != ddy {
                        break;
                    }
                    j += 1;
                }
                let (_, xe, ye) = g.split(path[j] as usize);
                let (ax, ay) = g.pos(xa, ya);
                let (ex, ey) = g.pos(xe, ye);
                segs.push((la, ax, ay, ex, ey));
                i = j;
            }
        }
        let vias = self.vias[net]
            .iter()
            .map(|&v| {
                let (_, x, y) = g.split(v as usize);
                g.pos(x, y)
            })
            .collect();
        NetRoute {
            name: self.p.nets[net].name.clone(),
            segments: segs,
            vias,
            routed: true,
        }
    }
}

/// Route a problem.
pub fn route(p: &Problem) -> Solution {
    let t0 = Instant::now();
    let mut r = Router::new(p);
    let mut sol = Solution {
        nodes: r.g.owner.len(),
        ..Default::default()
    };
    let nn = p.nets.len();
    let mut unreachable = vec![false; nn];
    for (i, net) in p.nets.iter().enumerate() {
        if net.pads.iter().any(|&s| r.terms[s].is_empty()) {
            unreachable[i] = true;
            sol.unreachable.push(net.name.clone());
        }
    }
    // short nets first
    let mut order: Vec<usize> = (0..nn).collect();
    let span = |i: usize| -> f64 {
        let mut b = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
        for &s in &p.nets[i].pads {
            let (x0, y0, x1, y1) = p.shapes[s].bbox();
            b = (b.0.min(x0), b.1.min(y0), b.2.max(x1), b.3.max(y1));
        }
        (b.2 - b.0) + (b.3 - b.1)
    };
    order.sort_by(|&a, &b| span(a).total_cmp(&span(b)));
    let mut failed = vec![false; nn];
    let mut todo = order.clone();
    for it in 0..p.iterations.max(1) {
        let t = Instant::now();
        for &net in &todo {
            r.rip_up(net);
            failed[net] = !r.route_net(net);
            r.commit(net);
        }
        let conflicted: Vec<usize> = order.iter().copied().filter(|&n| r.conflicts(n)).collect();
        let mut overused = 0;
        for n in 0..r.occ.len() {
            if r.occ[n] > 1 {
                overused += 1;
                r.hist[n] += p.hist_fac as f32 * (r.occ[n] - 1) as f32;
            }
        }
        let length: f64 = (0..nn)
            .map(|n| {
                r.paths[n]
                    .iter()
                    .map(|pth| pth.len().saturating_sub(1))
                    .sum::<usize>() as f64
                    * p.pitch
            })
            .sum();
        let vias: usize = r.vias.iter().map(|v| v.len()).sum();
        sol.rounds.push(Round {
            rerouted: todo.len(),
            overused,
            conflicted_nets: conflicted.len(),
            length,
            vias,
            seconds: t.elapsed().as_secs_f64(),
            searches: r.searches,
            expanded: r.expanded,
            retried: r.retried,
        });
        (r.searches, r.expanded, r.retried) = (0, 0, 0);
        if p.verbose {
            eprintln!(
                "round {it}: {} nets rerouted, {overused} nodes over-used by {} nets, {:.0} mm, {vias} vias, {:.1} s",
                todo.len(),
                conflicted.len(),
                length,
                t.elapsed().as_secs_f64()
            );
        }
        if conflicted.is_empty() {
            break;
        }
        r.pres *= p.pres_mult as f32;
        todo = conflicted;
    }
    for n in 0..nn {
        let mut out = r.output(n);
        out.routed = !failed[n] && !unreachable[n];
        if failed[n] {
            sol.failed.push(out.name.clone());
        }
        if r.conflicts(n) {
            sol.conflicted.push(out.name.clone());
        }
        sol.nets.push(out);
    }
    if p.verbose {
        eprintln!("routed in {:.1} s", t0.elapsed().as_secs_f64());
    }
    sol
}
