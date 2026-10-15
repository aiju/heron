//! Running a whole system: cards on a backplane, with their own clocks.
//!
//! Where [`crate::machine`] drives one CPU's clock itself, here nothing is
//! driven from outside. Oscillators and the power-on reset are parts in
//! the netlist like any other, and the run just lets time pass. A cycle is
//! the time between two rising edges of the CPU's clock net, however long
//! each one is; at each edge the run looks at the nets it was told to
//! watch, which still show their values from the end of the cycle.
//!
//! Memories and devices start from preloaded contents (ROM and RAM images,
//! a UART's input, a disk image), and the run returns what the chips it
//! names hold at the end. RAM images are loaded again when reset ends, so
//! writes from power-up's random state don't count.

use std::collections::{BTreeMap, HashMap};
use std::time::Instant;

use serde::{Deserialize, Serialize};

use crate::Error;
use crate::machine::{Contention, Histogram, Netlist, ViolationSummary, WorstNet, build};
use crate::rng::Rng;
use crate::sim::{Sim, Time};

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct SysConfig {
    /// The power-on state of flip-flops and memories.
    pub seed: i64,
    /// Stop after this much simulated time, or this many cycles of the
    /// program.
    pub max_ps: Time,
    pub max_cycles: i64,
    /// The CPU clock: every rising edge ends a cycle.
    pub clock_net: String,
    /// Timing checks start once this net is high (the end of reset).
    pub reset_net: String,
    /// At this level at the end of a cycle that fetches an instruction.
    pub fetch_net: String,
    pub fetch_level: u8,
    /// The address and data of a fetch, low bit first.
    pub addr_nets: Vec<String>,
    pub data_nets: Vec<String>,
    /// How many fetches to list in the outcome.
    pub fetch_trace: usize,
    /// Stop at the end of a cycle in which every (net, level) of any one
    /// of these lists holds.
    pub stop_when: Vec<Vec<(String, u8)>>,
    /// Trace these buses ({name: nets, low bit first}) for the cycles from
    /// trace_from to trace_to.
    pub trace_from: i64,
    pub trace_to: i64,
    pub trace_buses: BTreeMap<String, Vec<String>>,
    /// Chips whose contents to return (RAMs, devices).
    pub dump: Vec<String>,
    /// Nets whose values to return at the end.
    pub observe: Vec<String>,
    /// Nets whose every change to record between probe_from_ps and
    /// probe_to_ps (a waveform, for debugging).
    pub probe: Vec<String>,
    pub probe_from_ps: Time,
    pub probe_to_ps: Time,
}

impl Default for SysConfig {
    fn default() -> SysConfig {
        SysConfig {
            seed: 1,
            max_ps: 1 << 50,
            max_cycles: 10_000_000,
            clock_net: "CLK".into(),
            reset_net: "RESET_n".into(),
            fetch_net: "uLDIR_n".into(),
            fetch_level: 0,
            addr_nets: Vec::new(),
            data_nets: Vec::new(),
            fetch_trace: 0,
            stop_when: Vec::new(),
            trace_from: 0,
            trace_to: 0,
            trace_buses: BTreeMap::new(),
            dump: Vec::new(),
            observe: Vec::new(),
            probe: Vec::new(),
            probe_from_ps: 0,
            probe_to_ps: 0,
        }
    }
}

/// What a system run did.
#[derive(Debug, Serialize)]
pub struct SysOutcome {
    pub halted: bool,
    /// Why the run stopped: "stop condition", "cycle limit", "time limit",
    /// "interrupted" or "the clock stopped".
    pub reason: String,
    /// Cycles from the first instruction fetched after reset to the end.
    pub cycles: i64,
    /// Simulated time from the start of that first cycle to the end.
    pub time_ps: Time,
    /// When reset ended and when the first instruction was fetched.
    pub reset_ps: Time,
    pub start_ps: Time,
    /// The first fetch_trace fetches: (cycle, address, word).
    pub fetches: Vec<[i64; 3]>,
    pub fetch_count: i64,
    pub fetch_hash: u64,
    pub violations: Vec<crate::sim::Violation>,
    pub violation_summary: Vec<ViolationSummary>,
    pub violation_total: u64,
    pub contention: Contention,
    pub events: u64,
    pub wall_seconds: f64,
    /// The chips named in `dump`: their contents.
    pub dumps: BTreeMap<String, serde_bytes::ByteBuf>,
    /// The nets named in `observe`: their values at the end.
    pub nets: BTreeMap<String, u8>,
    /// One line per traced cycle: "cycle t=ps name=HEX ...".
    pub trace: Vec<String>,
    /// The probed nets' changes: (time, net name, value).
    pub probe: Vec<(Time, String, u8)>,
}

const FNV_PRIME: u64 = 1099511628211;

/// Run a system from power-up. `pre` preloads chips by reference: ROM and
/// RAM images, a UART's input, a disk image. `interrupted` is asked now
/// and then whether to stop early.
pub fn run_system(
    netlist: &Netlist,
    cfg: &SysConfig,
    pre: &HashMap<String, Vec<u8>>,
    interrupted: &mut dyn FnMut() -> bool,
) -> Result<SysOutcome, Error> {
    let pre: HashMap<&str, Vec<u8>> = pre.iter().map(|(k, v)| (k.as_str(), v.clone())).collect();
    let mut sim = build(netlist, &pre, &mut Rng::new(cfg.seed))?;
    let net = |sim: &Sim, n: &str| sim.net(n).ok_or_else(|| Error(format!("no net {n}")));
    let nets = |sim: &Sim, ns: &[String]| -> Result<Vec<u32>, Error> {
        ns.iter().map(|n| net(sim, n)).collect()
    };
    let clk = net(&sim, &cfg.clock_net)?;
    let rst = net(&sim, &cfg.reset_net)?;
    let fetch = net(&sim, &cfg.fetch_net)?;
    let (addr, data) = (nets(&sim, &cfg.addr_nets)?, nets(&sim, &cfg.data_nets)?);
    let stop: Vec<Vec<(u32, u8)>> = cfg
        .stop_when
        .iter()
        .map(|conj| conj.iter().map(|(n, v)| Ok((net(&sim, n)?, *v))).collect())
        .collect::<Result<_, Error>>()?;
    let trace_buses: Vec<(&str, Vec<u32>)> = cfg
        .trace_buses
        .iter()
        .map(|(name, ns)| Ok((name.as_str(), nets(&sim, ns)?)))
        .collect::<Result<_, Error>>()?;
    let dump: Vec<(String, usize)> = cfg
        .dump
        .iter()
        .map(|r| {
            sim.chip(r)
                .map(|i| (r.clone(), i))
                .ok_or_else(|| Error(format!("no chip {r}")))
        })
        .collect::<Result<_, _>>()?;
    let observe = nets(&sim, &cfg.observe)?;
    for n in nets(&sim, &cfg.probe)? {
        sim.state.probe[n as usize] = true;
    }
    sim.state.probe_from = cfg.probe_from_ps;
    sim.state.probe_to = cfg.probe_to_ps;

    let val = |sim: &Sim, n: u32| sim.state.nets[n as usize].val;
    let bus_val = |sim: &Sim, ns: &[u32]| -> i64 {
        ns.iter()
            .enumerate()
            .map(|(i, &n)| (sim.state.nets[n as usize].val as i64) << i)
            .sum()
    };

    let start = Instant::now();
    let mut fetches = Vec::new();
    let (mut fetch_count, mut fetch_hash) = (0i64, 1469598103934665603u64);
    let mut trace = Vec::new();
    let (mut reset_ps, mut prog_start): (Option<Time>, Option<(i64, Time)>) = (None, None);
    let mut reset_seen = false;
    let mut edges = 0i64;
    let mut last_edge = 0;
    // a cycle must end within this long, or the clock has stopped
    let stall_limit: Time = 1_000_000_000;
    let (halted, reason, cycles, end_ps) = loop {
        let until = (last_edge + stall_limit).min(cfg.max_ps);
        let Some(t) = sim.run_watch(until, Some(clk)) else {
            let reason = if until >= cfg.max_ps {
                "time limit"
            } else {
                "the clock stopped"
            };
            let c = prog_start.map_or(0, |(e, _)| edges - e);
            break (false, reason, c, sim.state.now);
        };
        last_edge = t;
        edges += 1;
        // the end of a cycle: observe. Reset is over at the first edge
        // with the reset net high after it has been low.
        if val(&sim, rst) == 0 {
            reset_seen = true;
        } else if reset_ps.is_none() && reset_seen {
            reset_ps = Some(t);
            sim.state.check_on = true;
            // RAM images go in now, as a loader would put them there:
            // power-up's random state can write to a RAM before reset
            // reaches its control logic
            for (r, img) in &pre {
                if let Some(i) = sim.chip(r) {
                    sim.chips[i].model.reload(img);
                }
            }
        }
        let cycle = prog_start.map_or(-1, |(e, _)| edges - e - 1);
        sim.state.cycle = cycle;
        sim.state.cycle_start = t;
        if !trace_buses.is_empty() && cycle >= cfg.trace_from && cycle <= cfg.trace_to {
            let mut line = format!("{cycle} t={t}");
            for (name, ns) in &trace_buses {
                line += &format!(" {name}={}", bus_hex(&sim, ns));
            }
            trace.push(line);
        }
        let fetching = val(&sim, fetch) == cfg.fetch_level;
        if fetching && reset_ps.is_some() {
            let (a, w) = (bus_val(&sim, &addr), bus_val(&sim, &data));
            fetch_count += 1;
            fetch_hash = (fetch_hash ^ ((cycle as u64) << 32) ^ ((a as u64) << 16) ^ w as u64)
                .wrapping_mul(FNV_PRIME);
            if fetches.len() < cfg.fetch_trace {
                fetches.push([cycle, a, w]);
            }
            if prog_start.is_none() {
                // the fetch in reset's last cycle belongs to cycle -1
                prog_start = Some((edges, t));
            }
        }
        if let Some((e, _)) = prog_start {
            let done = stop
                .iter()
                .any(|conj| conj.iter().all(|&(n, v)| val(&sim, n) == v));
            if done && cycle >= 0 {
                break (true, "stop condition", edges - e, t);
            }
            if edges - e >= cfg.max_cycles {
                break (false, "cycle limit", edges - e, t);
            }
        }
        if edges % 1024 == 0 && interrupted() {
            let c = prog_start.map_or(0, |(e, _)| edges - e);
            break (false, "interrupted", c, t);
        }
    };
    let wall_seconds = start.elapsed().as_secs_f64();

    let s = &sim.state;
    let mut violation_summary: Vec<ViolationSummary> = s
        .violation_stats
        .iter()
        .map(|(k, &(count, worst))| ViolationSummary {
            what: k.clone(),
            count,
            worst_slack_ps: worst,
        })
        .collect();
    violation_summary.sort_by(|a, b| (a.worst_slack_ps, &a.what).cmp(&(b.worst_slack_ps, &b.what)));
    let c = &s.contention;
    let mut worst_nets: Vec<WorstNet> = c
        .nets
        .iter()
        .map(|(n, &max_ps)| WorstNet {
            net: n.clone(),
            max_ps,
        })
        .collect();
    worst_nets.sort_by(|a, b| (-a.max_ps, &a.net).cmp(&(-b.max_ps, &b.net)));
    worst_nets.truncate(12);
    let start_ps = prog_start.map_or(end_ps, |(_, t)| t);
    Ok(SysOutcome {
        halted,
        reason: reason.into(),
        cycles,
        time_ps: end_ps - start_ps,
        reset_ps: reset_ps.unwrap_or(-1),
        start_ps,
        fetches,
        fetch_count,
        fetch_hash,
        violations: s.violations.clone(),
        violation_total: s.violation_stats.values().map(|&(n, _)| n).sum(),
        violation_summary,
        contention: Contention {
            count: c.count,
            max_ps: c.max,
            total_ps: c.total,
            histogram: Histogram {
                under_2ns: c.hist[0],
                ns_2_5: c.hist[1],
                ns_5_10: c.hist[2],
                ns_10_20: c.hist[3],
                ns_20_50: c.hist[4],
                over_50ns: c.hist[5],
            },
            worst_nets,
        },
        events: s.event_count,
        wall_seconds,
        dumps: dump
            .iter()
            .filter_map(|(r, i)| {
                sim.chips[*i]
                    .model
                    .dump()
                    .map(|d| (r.clone(), serde_bytes::ByteBuf::from(d)))
            })
            .collect(),
        nets: cfg
            .observe
            .iter()
            .zip(&observe)
            .map(|(n, &i)| (n.clone(), val(&sim, i)))
            .collect(),
        trace,
        probe: sim
            .state
            .probe_log
            .iter()
            .map(|&(t, n, v)| (t, sim.topo.net_names[n as usize].clone(), v))
            .collect(),
    })
}

/// A bus's value in hex, any width.
fn bus_hex(sim: &Sim, nets: &[u32]) -> String {
    let mut digits = String::new();
    for i in (0..nets.len().div_ceil(4)).rev() {
        let d: usize = (0..4)
            .filter(|j| 4 * i + j < nets.len())
            .map(|j| (sim.state.nets[nets[4 * i + j] as usize].val as usize) << j)
            .sum();
        digits.push(char::from_digit(d as u32, 16).unwrap().to_ascii_uppercase());
    }
    let out = digits.trim_start_matches('0');
    if out.is_empty() {
        "0".into()
    } else {
        out.into()
    }
}
