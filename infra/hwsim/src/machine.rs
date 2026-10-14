//! Running a machine: build the circuit from a netlist, load its memories,
//! clock it from reset until the program halts, and report what happened.
//!
//! The netlist is what `Netlist.export()` in infra/hw/netlist.py writes.
//! The configuration names the nets and chips the run loop needs; its
//! defaults are the draft 0 CPU's (studies/v0_hw), and a machine module's
//! CONFIG overrides them.

use std::collections::{BTreeMap, HashMap};
use std::time::Instant;

use serde::{Deserialize, Serialize};

use crate::Error;
use crate::models::{Model, Spec};
use crate::rng::Rng;
use crate::sim::{ChipInfo, Kind, Sim, Time};

#[derive(Deserialize)]
pub struct Netlist {
    pub nets: Vec<String>,
    pub chips: Vec<ChipDesc>,
}

#[derive(Deserialize)]
pub struct ChipDesc {
    #[serde(rename = "ref")]
    pub reference: String,
    pub model: String,
    #[serde(default)]
    pub part: String,
    pub pins: Vec<String>,
    pub kinds: Vec<String>,
    /// The net on each pin, -1 if it isn't connected.
    pub nets: Vec<i64>,
    #[serde(default)]
    pub delays: HashMap<String, Time>,
}

/// How the run loop knows the reset sequence is over.
#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Start {
    /// Draft 0: reset released, MODERST high and the microcode's uEND.
    V0,
    /// The first instruction fetch after reset.
    FirstFetch,
}

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Config {
    pub period_ps: Time,
    /// The write window, as fractions of the period.
    pub we_start: f64,
    pub we_end: f64,
    pub reset_cycles: i64,
    pub max_cycles: i64,
    /// The console input, all supplied up front.
    #[serde(with = "serde_bytes")]
    pub input: Vec<u8>,
    /// The power-on state of flip-flops and memories.
    pub seed: i64,
    /// Start with the register files cleared.
    pub zero_regs: bool,
    /// How many instruction fetches to list in the outcome.
    pub fetch_trace: usize,
    /// Trace these buses ({name: nets, low bit first}) for the cycles from
    /// trace_from to trace_to; no buses, no trace.
    pub trace_from: i64,
    pub trace_to: i64,
    pub trace_buses: BTreeMap<String, Vec<String>>,
    /// The register file chips of the A and B copies, low byte first.
    pub rf_chips: BTreeMap<String, Vec<String>>,
    pub rf_entries: usize,
    /// The RAM chips: low byte, high byte.
    pub ram_chips: Vec<String>,
    pub ram_bits: u32,
    pub addr_bits: usize,
    pub pc_bits: usize,
    /// Low while an instruction is fetched.
    pub fetch_net: String,
    /// At halt_level while the CPU halts.
    pub halt_net: String,
    pub halt_level: u8,
    pub start: Start,
}

impl Default for Config {
    fn default() -> Config {
        let refs = |r: &[&str]| r.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        Config {
            period_ps: 0,
            we_start: 0.5,
            we_end: 0.875,
            reset_cycles: 4,
            max_cycles: 10_000_000,
            input: Vec::new(),
            seed: 1,
            zero_regs: false,
            fetch_trace: 0,
            trace_from: 0,
            trace_to: 0,
            trace_buses: BTreeMap::new(),
            rf_chips: BTreeMap::from([
                ("A".to_string(), refs(&["U_RFAL", "U_RFAH"])),
                ("B".to_string(), refs(&["U_RFBL", "U_RFBH"])),
            ]),
            rf_entries: 16,
            ram_chips: refs(&["U_RAML", "U_RAMH"]),
            ram_bits: 15,
            addr_bits: 16,
            pc_bits: 15,
            fetch_net: "uLDIR_n".into(),
            halt_net: "uHALT_n".into(),
            halt_level: 0,
            start: Start::V0,
        }
    }
}

#[derive(Debug, Serialize)]
pub struct ViolationSummary {
    pub what: String,
    pub count: u64,
    pub worst_slack_ps: Time,
}

#[derive(Debug, Serialize)]
pub struct Histogram {
    #[serde(rename = "<2ns")]
    pub under_2ns: i64,
    #[serde(rename = "2-5ns")]
    pub ns_2_5: i64,
    #[serde(rename = "5-10ns")]
    pub ns_5_10: i64,
    #[serde(rename = "10-20ns")]
    pub ns_10_20: i64,
    #[serde(rename = "20-50ns")]
    pub ns_20_50: i64,
    #[serde(rename = ">=50ns")]
    pub over_50ns: i64,
}

#[derive(Debug, Serialize)]
pub struct WorstNet {
    pub net: String,
    pub max_ps: Time,
}

#[derive(Debug, Serialize)]
pub struct Contention {
    pub count: i64,
    pub max_ps: Time,
    pub total_ps: Time,
    pub histogram: Histogram,
    /// The 12 nets with the longest contention.
    pub worst_nets: Vec<WorstNet>,
}

/// What a run did.
#[derive(Debug, Serialize)]
pub struct Outcome {
    pub halted: bool,
    /// Why the run stopped: "HALT", "cycle limit", "interrupted" or
    /// "reset sequence never finished".
    pub reason: String,
    /// Cycles from the first instruction to the end.
    pub cycles: i64,
    pub reset_cycles: i64,
    /// What the program wrote to the console.
    #[serde(with = "serde_bytes")]
    pub output: Vec<u8>,
    pub regs_a: Vec<i64>,
    pub regs_b: Vec<i64>,
    pub pc: i64,
    pub flags: BTreeMap<String, u8>,
    /// The first fetch_trace fetches: (cycle, address, word).
    pub fetches: Vec<[i64; 3]>,
    pub fetch_count: i64,
    /// A hash of every fetch's cycle, address and word.
    pub fetch_hash: u64,
    pub violations: Vec<crate::sim::Violation>,
    pub violation_summary: Vec<ViolationSummary>,
    pub violation_total: u64,
    pub contention: Contention,
    /// Output changes processed.
    pub events: u64,
    pub wall_seconds: f64,
    pub period_ps: Time,
    /// All of RAM at the end, as 16-bit words, low byte first.
    #[serde(with = "serde_bytes")]
    pub ram: Vec<u8>,
    /// One line per traced cycle: "cycle name=HEX ...".
    pub trace: Vec<String>,
}

const FNV_PRIME: u64 = 1099511628211;

/// Run a machine. `roms` are the ROM images by chip reference; `ram` is
/// the RAM image as 16-bit words, low byte first. `interrupted` is asked
/// now and then whether to stop early.
pub fn run(
    netlist: &Netlist,
    cfg: &Config,
    roms: &HashMap<String, Vec<u8>>,
    ram: Option<&[u8]>,
    interrupted: &mut dyn FnMut() -> bool,
) -> Result<Outcome, Error> {
    if cfg.period_ps <= 0 {
        return Err(Error(format!(
            "period_ps must be positive, not {}",
            cfg.period_ps
        )));
    }
    let [ram_lo, ram_hi] = cfg.ram_chips.as_slice() else {
        return Err(Error(format!(
            "ram_chips must name two chips, not {:?}",
            cfg.ram_chips
        )));
    };
    let rf = |side: &str| -> Result<&Vec<String>, Error> {
        cfg.rf_chips
            .get(side)
            .ok_or_else(|| Error(format!("rf_chips has no {side} side")))
    };
    let (rf_a, rf_b) = (rf("A")?, rf("B")?);

    // Memories are loaded before the models start, so the first evaluation
    // sees them.
    let mut pre: HashMap<&str, Vec<u8>> =
        roms.iter().map(|(k, v)| (k.as_str(), v.clone())).collect();
    let ram_size = 1usize << cfg.ram_bits;
    if let Some(img) = ram {
        let (mut lo, mut hi) = (vec![0; ram_size], vec![0; ram_size]);
        for (i, w) in img.as_chunks::<2>().0.iter().take(ram_size).enumerate() {
            lo[i] = w[0];
            hi[i] = w[1];
        }
        pre.insert(ram_lo, lo);
        pre.insert(ram_hi, hi);
    }
    if cfg.zero_regs {
        for r in rf_a.iter().chain(rf_b) {
            pre.insert(r, vec![0; 32768]);
        }
    }
    let mut sim = build(netlist, &pre, &mut Rng::new(cfg.seed))?;

    let chip = |r: &str| sim.chip(r).ok_or_else(|| Error(format!("no chip {r}")));
    let net = |n: &str| sim.net(n).ok_or_else(|| Error(format!("no net {n}")));
    let bus = |prefix: &str, n: usize, start: usize| -> Result<Vec<u32>, Error> {
        (start..start + n)
            .map(|i| net(&format!("{prefix}{i}")))
            .collect()
    };
    let io = chip("X_IO")?;
    let clk = chip("X_CLK")?;
    let clock_out = |pin: &str| -> Result<u32, Error> {
        let info = &sim.chips[clk].info;
        let p = info.pin_names.iter().position(|p| p == pin);
        p.and_then(|p| info.outs[p])
            .ok_or_else(|| Error(format!("X_CLK: no output {pin}")))
    };
    let (o_clk, o_we, o_rst) = (clock_out("CLK")?, clock_out("WEWIN")?, clock_out("RESET")?);
    let (n_halt, n_ldir) = (net(&cfg.halt_net)?, net(&cfg.fetch_net)?);
    let (n_rst, n_i) = (net("RESET_n")?, net("IFLAG")?);
    let v0_nets = match cfg.start {
        Start::V0 => Some((net("uEND_n")?, net("MODERST")?, net("MODEIRQ")?)),
        Start::FirstFetch => None,
    };
    let (n_addr, n_dbus, n_pc) = (
        bus("ADDR", cfg.addr_bits, 0)?,
        bus("DBUS", 16, 0)?,
        bus("PC", cfg.pc_bits, 1)?,
    );
    let flags: Vec<(&str, u32)> = ["NFLAG", "ZFLAG", "CFLAG", "VFLAG", "IFLAG"]
        .iter()
        .map(|&f| Ok((f, net(f)?)))
        .collect::<Result<_, Error>>()?;
    let trace_buses: Vec<(&str, Vec<u32>)> = cfg
        .trace_buses
        .iter()
        .map(|(name, nets)| {
            Ok((
                name.as_str(),
                nets.iter().map(|n| net(n)).collect::<Result<_, _>>()?,
            ))
        })
        .collect::<Result<_, Error>>()?;
    let sram = |r: &str| -> Result<usize, Error> {
        let i = chip(r)?;
        match sim.chips[i].model {
            Model::Sram(_) => Ok(i),
            _ => Err(Error(format!("{r} isn't a static RAM"))),
        }
    };
    let rf_idx: Vec<Vec<usize>> = [rf_a, rf_b]
        .iter()
        .map(|refs| refs.iter().map(|r| sram(r)).collect())
        .collect::<Result<_, _>>()?;
    let (ram_lo, ram_hi) = (sram(ram_lo)?, sram(ram_hi)?);
    match &mut sim.chips[io].model {
        Model::IoDev(d) => d.input = cfg.input.clone(),
        _ => return Err(Error("X_IO isn't an I/O device".into())),
    }

    let val = |sim: &Sim, n: u32| sim.state.nets[n as usize].val;
    let bus_val = |sim: &Sim, ns: &[u32]| -> i64 {
        ns.iter()
            .enumerate()
            .map(|(i, &n)| (sim.state.nets[n as usize].val as i64) << i)
            .sum()
    };
    let timer_on = |sim: &Sim| match &sim.chips[io].model {
        Model::IoDev(d) => d.timer_period != 0,
        _ => false,
    };
    let halting = |sim: &Sim| {
        if val(sim, n_halt) != cfg.halt_level {
            return false;
        }
        match v0_nets {
            Some((_, mrst, mirq)) => val(sim, mrst) == 0 && val(sim, mirq) == 0,
            None => true,
        }
    };

    let t = cfg.period_ps;
    let (ws, we) = (
        (t as f64 * cfg.we_start) as Time,
        (t as f64 * cfg.we_end) as Time,
    );
    let mut fetches = Vec::new();
    let (mut fetch_count, mut fetch_hash) = (0i64, 1469598103934665603u64);
    let mut trace = Vec::new();
    let mut prog_start: Option<i64> = None;
    let start = Instant::now();
    sim.state.outs[o_rst as usize].val = 0;
    sim.state.schedule(o_rst, 0, 0, true);
    sim.run(1);
    let mut cyc = 0i64;
    let (halted, reason, cycles) = loop {
        let t0 = cyc * t;
        let cycle = prog_start.map_or(-1, |p| cyc - p);
        sim.state.cycle_start = t0;
        sim.state.cycle = cycle;
        sim.state.schedule(o_clk, t0, 1, true);
        sim.state.schedule(o_clk, t0 + t / 2, 0, true);
        sim.state.schedule(o_we, t0 + ws, 1, true);
        sim.state.schedule(o_we, t0 + we, 0, true);
        if cyc == cfg.reset_cycles {
            sim.state.schedule(o_rst, t0 + t / 4, 1, true);
        }
        sim.state.check_on = cyc > cfg.reset_cycles;
        sim.run(t0 + t);

        // the end of the cycle: observe
        if !trace_buses.is_empty() && cycle >= cfg.trace_from && cycle <= cfg.trace_to {
            let mut line = cycle.to_string();
            for (name, nets) in &trace_buses {
                line += &format!(" {name}={}", bus_hex(&sim, nets));
            }
            trace.push(line);
        }
        if val(&sim, n_ldir) == 0 && prog_start.is_some() {
            let (a, w) = (bus_val(&sim, &n_addr), bus_val(&sim, &n_dbus));
            fetch_count += 1;
            fetch_hash = (fetch_hash ^ (cycle as u64) << 32 ^ (a as u64) << 16 ^ w as u64)
                .wrapping_mul(FNV_PRIME);
            if fetches.len() < cfg.fetch_trace {
                fetches.push([cycle, a, w]);
            }
        }
        let started = match v0_nets {
            Some((end, mrst, _)) => {
                val(&sim, n_rst) == 1 && val(&sim, mrst) == 1 && val(&sim, end) == 0
            }
            None => val(&sim, n_rst) == 1 && val(&sim, n_ldir) == 0 && cyc > cfg.reset_cycles,
        };
        if prog_start.is_none() && started {
            prog_start = Some(cyc + 1);
            // the fetch in the reset sequence's last cycle belongs to cycle -1
            let (a, w) = (bus_val(&sim, &n_addr), bus_val(&sim, &n_dbus));
            fetch_count += 1;
            fetch_hash = (fetch_hash ^ 0xFFFF_FFFFu64 << 32 ^ (a as u64) << 16 ^ w as u64)
                .wrapping_mul(FNV_PRIME);
            if cfg.fetch_trace > 0 {
                fetches.push([-1, a, w]);
            }
        }
        if prog_start.is_some() && halting(&sim) && (val(&sim, n_i) == 0 || !timer_on(&sim)) {
            break (true, "HALT", cycle + 1);
        }
        if prog_start.is_some() && cycle + 1 >= cfg.max_cycles {
            break (false, "cycle limit", cycle + 1);
        }
        if prog_start.is_none() && cyc > cfg.reset_cycles + 50 {
            break (false, "reset sequence never finished", 0);
        }
        if cyc % 1024 == 0 && interrupted() {
            break (false, "interrupted", cycle + 1);
        }
        cyc += 1;
    };
    let wall_seconds = start.elapsed().as_secs_f64();

    let mem = |i: usize| match &sim.chips[i].model {
        Model::Sram(m) => &m.mem,
        _ => unreachable!("checked above"),
    };
    let regs = |chips: &[usize]| -> Vec<i64> {
        (0..cfg.rf_entries)
            .map(|i| {
                chips
                    .iter()
                    .enumerate()
                    .map(|(k, &c)| (mem(c)[i] as i64) << (8 * k))
                    .sum()
            })
            .collect()
    };
    let (lo, hi) = (mem(ram_lo), mem(ram_hi));
    let ram = (0..ram_size).flat_map(|i| [lo[i], hi[i]]).collect();
    let output = match &sim.chips[io].model {
        Model::IoDev(d) => d.output.clone(),
        _ => unreachable!("checked above"),
    };

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

    Ok(Outcome {
        halted,
        reason: reason.into(),
        cycles,
        reset_cycles: cfg.reset_cycles,
        output,
        regs_a: regs(&rf_idx[0]),
        regs_b: regs(&rf_idx[1]),
        pc: bus_val(&sim, &n_pc) << 1,
        flags: flags
            .iter()
            .map(|&(f, n)| (f.to_string(), val(&sim, n)))
            .collect(),
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
        period_ps: t,
        ram,
        trace,
    })
}

/// A bus's value in hex, any width (draft 1b's control word has 120 bits).
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

/// Build the circuit from a netlist, with memories preloaded by chip
/// reference, and let every chip drive its initial outputs.
pub fn build(netlist: &Netlist, pre: &HashMap<&str, Vec<u8>>, rng: &mut Rng) -> Result<Sim, Error> {
    let n_nets = netlist.nets.len();
    let mut infos = Vec::new();
    for c in &netlist.chips {
        if c.kinds.len() != c.pins.len() || c.nets.len() != c.pins.len() {
            return Err(Error(format!(
                "{}: pins, kinds and nets differ in length",
                c.reference
            )));
        }
        let kinds = c
            .kinds
            .iter()
            .map(|k| match k.as_str() {
                "in" => Ok(Kind::In),
                "out" => Ok(Kind::Out),
                "tri" => Ok(Kind::Tri),
                "io" => Ok(Kind::Io),
                _ => Err(Error(format!("{}: unknown pin kind {k:?}", c.reference))),
            })
            .collect::<Result<_, _>>()?;
        let pins = c
            .nets
            .iter()
            .map(|&n| match n {
                -1 => Ok(None),
                n if (0..n_nets as i64).contains(&n) => Ok(Some(n as u32)),
                n => Err(Error(format!("{}: no net {n}", c.reference))),
            })
            .collect::<Result<_, _>>()?;
        infos.push(ChipInfo {
            reference: c.reference.clone(),
            part: c.part.clone(),
            pin_names: c.pins.clone(),
            kinds,
            pins,
            outs: Vec::new(),
        });
    }
    let (state, topo, infos) = Sim::wire(netlist.nets.clone(), infos);
    let mut chips = Vec::new();
    for (desc, info) in netlist.chips.iter().zip(infos) {
        let spec = Spec {
            info: &info,
            delays: &desc.delays,
        };
        let model = Model::new(
            &desc.model,
            &spec,
            rng,
            pre.get(desc.reference.as_str()).map(|v| v.as_slice()),
        )?;
        chips.push(crate::sim::Chip { info, model });
    }
    let mut sim = Sim { state, topo, chips };
    sim.init();
    Ok(sim)
}
