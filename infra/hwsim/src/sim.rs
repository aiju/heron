//! The event-driven core: nets, the outputs that drive them, the event
//! queue, and the timing checks the chip models call.
//!
//! Every net is one bit. Chips are behavioural models with datasheet
//! pin-to-pin delays. When an input changes, the chip re-evaluates and
//! schedules each output change after the delay of the arc that caused it.
//! If an output already has a later change pending, the new value replaces
//! the pending one at the later time ("latest arrival wins"), so outputs
//! settle no earlier than their slowest input path, as static timing
//! analysis assumes.
//!
//! A pull-up is a weak driver: it sets a net's value only while no other
//! driver is enabled, and never contends. Open-collector outputs are
//! three-state outputs that only ever drive 0.

use std::collections::{BTreeMap, HashMap};

use serde::Serialize;

use crate::models::Model;

/// Time in picoseconds.
pub type Time = i64;

/// A time before anything happened, for "never changed".
pub const NEVER: Time = -1 << 40;

/// What a chip pin does, from the netlist.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    In,
    Out,
    Tri,
    Io,
    /// A pull-up resistor to VCC: a weak driver of 1.
    Pull,
}

/// A chip as the models see it: its pins and where they go.
pub struct ChipInfo {
    pub reference: String,
    pub part: String,
    pub pin_names: Vec<String>,
    pub kinds: Vec<Kind>,
    /// The net on each pin, if it's connected.
    pub pins: Vec<Option<u32>>,
    /// The output slot of each pin, if it's connected and can drive.
    pub outs: Vec<Option<u32>>,
    /// Whether the chip's timing violations count. A synchroniser's
    /// flip-flops sample asynchronous inputs and are expected to see
    /// setup violations, so the netlist can turn them off.
    pub checks: bool,
    /// Extra delay on each output pin (the wiring); empty for none.
    pub pin_delays: Vec<Time>,
}

pub struct Chip {
    pub info: ChipInfo,
    pub model: Model,
}

/// The parts of the circuit that don't change while it runs.
pub struct Topology {
    pub net_names: Vec<String>,
    /// The output slots driving each net.
    pub drivers: Vec<Vec<u32>>,
    /// The (chip, pin) inputs on each net.
    pub fanout: Vec<Vec<(u32, u32)>>,
    /// Whether each net has a weak driver (a pull-up) among its drivers.
    pub weak: Vec<bool>,
}

#[derive(Clone)]
pub struct Net {
    pub val: u8,
    /// When the value last changed.
    pub last: Time,
    pub float: bool,
    /// When the current contention started, if there is one.
    pub cont_since: Option<Time>,
}

/// One driver of a net: a chip output, with its value and whether it's
/// enabled (a tristate output that's off isn't).
#[derive(Clone)]
pub struct Out {
    pub net: u32,
    pub val: u8,
    pub en: bool,
    /// A pull-up: it only counts when no other driver is enabled.
    pub weak: bool,
    /// The latest change pending for this output.
    pub pend: Option<u32>,
}

/// Pending events in time order, and events at the same time in the order
/// they were scheduled: a bucket per time, filled in order.
#[derive(Default)]
struct Queue {
    /// The bucket being processed: its time, its events, how far in.
    cur_t: Time,
    cur: Vec<u32>,
    pos: usize,
    later: BTreeMap<Time, Vec<u32>>,
    /// Empty buckets, to reuse.
    spare: Vec<Vec<u32>>,
}

impl Queue {
    fn push(&mut self, t: Time, idx: u32) {
        debug_assert!(t >= self.cur_t, "an event in the past");
        if t == self.cur_t {
            self.cur.push(idx);
        } else {
            let Queue { later, spare, .. } = self;
            later
                .entry(t)
                .or_insert_with(|| spare.pop().unwrap_or_default())
                .push(idx);
        }
    }

    /// The next event, if it's before `until`.
    fn pop(&mut self, until: Time) -> Option<(Time, u32)> {
        loop {
            if self.pos < self.cur.len() {
                if self.cur_t >= until {
                    return None;
                }
                self.pos += 1;
                return Some((self.cur_t, self.cur[self.pos - 1]));
            }
            let next = self.later.first_entry()?;
            if *next.key() >= until {
                return None;
            }
            let (t, bucket) = next.remove_entry();
            let mut done = std::mem::replace(&mut self.cur, bucket);
            done.clear();
            self.spare.push(done);
            (self.cur_t, self.pos) = (t, 0);
        }
    }
}

#[derive(Clone, Copy)]
struct Event {
    t: Time,
    out: u32,
    val: u8,
    en: bool,
}

/// A timing violation, as reported (the first 200 of a run).
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Violation {
    pub cycle: i64,
    pub at_ps: Time,
    pub chip: String,
    pub pin: String,
    pub net: String,
    pub kind: String,
    pub slack_ps: Time,
}

/// Bus contention: two enabled drivers disagreeing on a net.
#[derive(Default)]
pub struct ContentionStats {
    pub count: i64,
    pub max: Time,
    pub total: Time,
    /// The longest contention on each net.
    pub nets: HashMap<String, Time>,
    /// Durations: <2 ns, <5, <10, <20, <50, longer.
    pub hist: [i64; 6],
}

/// Everything that changes while the circuit runs, apart from the chips'
/// own state.
pub struct State {
    pub now: Time,
    pub nets: Vec<Net>,
    pub outs: Vec<Out>,
    events: Vec<Event>,
    free: Vec<u32>,
    queue: Queue,
    /// Output changes processed.
    pub event_count: u64,

    /// The program-relative cycle number (-1 during reset).
    pub cycle: i64,
    /// When the current cycle's rising edge was.
    pub cycle_start: Time,
    /// Whether timing checks are on (they're off while reset is held).
    pub check_on: bool,

    /// Nets whose changes are recorded (by net number), between
    /// probe_from and probe_to, into probe_log as (time, net, value).
    pub probe: Vec<bool>,
    pub probe_from: Time,
    pub probe_to: Time,
    pub probe_log: Vec<(Time, u32, u8)>,

    /// The first 200 violations.
    pub violations: Vec<Violation>,
    /// For each kind of violation: how often, and the worst slack.
    pub violation_stats: HashMap<String, (u64, Time)>,
    pub contention: ContentionStats,
}

impl State {
    /// Schedule output slot `o` to take (v, en) at time t.
    pub fn schedule(&mut self, o: u32, t: Time, v: u8, en: bool) {
        let out = &self.outs[o as usize];
        if let Some(p) = out.pend {
            let ev = &mut self.events[p as usize];
            if ev.t >= t {
                // a later change is pending: it carries the newest value
                ev.val = v;
                ev.en = en;
                return;
            }
            if ev.val == v && ev.en == en {
                return;
            }
        } else if out.val == v && out.en == en {
            return;
        }
        let ev = Event {
            t,
            out: o,
            val: v,
            en,
        };
        let idx = match self.free.pop() {
            Some(i) => {
                self.events[i as usize] = ev;
                i
            }
            None => {
                self.events.push(ev);
                (self.events.len() - 1) as u32
            }
        };
        self.queue.push(t, idx);
        self.outs[o as usize].pend = Some(idx);
    }

    /// Schedule output slot `o` to take (v, en) at time t, whatever else is
    /// pending for it. This is for a model's own timers (a device's wake-up
    /// pin), not for logic: it skips the latest-arrival rule.
    pub fn schedule_force(&mut self, o: u32, t: Time, v: u8, en: bool) {
        let ev = Event {
            t,
            out: o,
            val: v,
            en,
        };
        let idx = match self.free.pop() {
            Some(i) => {
                self.events[i as usize] = ev;
                i
            }
            None => {
                self.events.push(ev);
                (self.events.len() - 1) as u32
            }
        };
        self.queue.push(t, idx);
        let pend_t = self.outs[o as usize]
            .pend
            .map(|p| self.events[p as usize].t);
        if pend_t.is_none_or(|pt| pt <= t) {
            self.outs[o as usize].pend = Some(idx);
        }
    }

    fn record_contention(&mut self, net: u32, d: Time, topo: &Topology) {
        if !self.check_on {
            return;
        }
        let c = &mut self.contention;
        c.count += 1;
        c.total += d;
        c.max = c.max.max(d);
        // a net is listed once it has had contention for some time
        let name = &topo.net_names[net as usize];
        if d > c.nets.get(name).copied().unwrap_or(0) {
            c.nets.insert(name.clone(), d);
        }
        let bucket = [2000, 5000, 10000, 20000, 50000]
            .iter()
            .take_while(|&&limit| d >= limit)
            .count();
        c.hist[bucket] += 1;
    }
}

/// What a chip model sees while it evaluates: the circuit's state, through
/// its own pins.
pub struct Ctx<'a> {
    pub state: &'a mut State,
    pub topo: &'a Topology,
}

impl Ctx<'_> {
    pub fn now(&self) -> Time {
        self.state.now
    }

    /// The value on a pin (0 if it isn't connected).
    pub fn input(&self, c: &ChipInfo, pin: usize) -> u8 {
        match c.pins[pin] {
            Some(n) => self.state.nets[n as usize].val,
            None => 0,
        }
    }

    /// The value a pin's output is driving (or last drove).
    pub fn driven(&self, c: &ChipInfo, pin: usize) -> u8 {
        match c.outs[pin] {
            Some(o) => self.state.outs[o as usize].val,
            None => 0,
        }
    }

    /// Drive a pin to (v, en) after delay d.
    pub fn drive(&mut self, c: &ChipInfo, pin: usize, v: u8, en: bool, d: Time) {
        let t = self.state.now + d;
        self.drive_at(c, pin, v, en, t);
    }

    /// Drive a pin to (v, en) at time t.
    pub fn drive_at(&mut self, c: &ChipInfo, pin: usize, v: u8, en: bool, t: Time) {
        // a pin has an output slot only if it's connected
        if let Some(o) = c.outs[pin] {
            let t = t + c.pin_delays.get(pin).copied().unwrap_or(0);
            self.state.schedule(o, t, v, en);
        }
    }

    /// Ask to be woken at time t: a model's wake-up pin (an "io" pin on a
    /// net of its own) goes high then, and the model sets it low again
    /// when it sees it.
    pub fn wake(&mut self, c: &ChipInfo, pin: usize, t: Time) {
        if let Some(o) = c.outs[pin] {
            let t = t.max(self.state.now);
            self.state.schedule_force(o, t, 1, true);
        }
    }

    /// Set a wake-up pin low again, now.
    pub fn wake_done(&mut self, c: &ChipInfo, pin: usize) {
        if let Some(o) = c.outs[pin] {
            let now = self.state.now;
            self.state.schedule_force(o, now, 0, true);
        }
    }

    /// When the value on a pin last changed.
    pub fn last_change(&self, c: &ChipInfo, pin: usize) -> Time {
        match c.pins[pin] {
            Some(n) => self.state.nets[n as usize].last,
            None => NEVER,
        }
    }

    /// Whether a pin's net has two drivers disagreeing on it.
    pub fn contended(&self, c: &ChipInfo, pin: usize) -> bool {
        match c.pins[pin] {
            Some(n) => self.state.nets[n as usize].cont_since.is_some(),
            None => false,
        }
    }

    pub fn violate(&mut self, c: &ChipInfo, pin: usize, kind: &str, slack: Time) {
        let s = &mut *self.state;
        if !s.check_on || !c.checks {
            return;
        }
        let key = format!("{}.{} {}", c.reference, c.pin_names[pin], kind);
        let entry = s.violation_stats.entry(key).or_insert((0, slack));
        entry.0 += 1;
        entry.1 = entry.1.min(slack);
        if s.violations.len() < 200 {
            let net = match c.pins[pin] {
                Some(n) => self.topo.net_names[n as usize].clone(),
                None => String::new(),
            };
            s.violations.push(Violation {
                cycle: s.cycle,
                at_ps: s.now - s.cycle_start,
                chip: c.reference.clone(),
                pin: c.pin_names[pin].clone(),
                net,
                kind: kind.to_string(),
                slack_ps: slack,
            });
        }
    }

    /// At a clock edge: the input on `pin` must have been stable for
    /// `setup` ps, and not under contention.
    pub fn check_setup(&mut self, c: &ChipInfo, pin: usize, setup: Time, what: &str) {
        let Some(n) = c.pins[pin] else { return };
        let net = &self.state.nets[n as usize];
        let slack = self.state.now - net.last - setup;
        let contended = net.cont_since.is_some();
        if slack < 0 {
            self.violate(c, pin, &format!("setup {what}"), slack);
        }
        if contended {
            self.violate(c, pin, "sampled during bus contention", 0);
        }
    }

    /// The input on `pin` changed: it must have been held for `hold` ps
    /// after the last clock edge, if there was one.
    pub fn check_hold(
        &mut self,
        c: &ChipInfo,
        pin: usize,
        last_edge: Option<Time>,
        hold: Time,
        what: &str,
    ) {
        let Some(edge) = last_edge else { return };
        let slack = self.state.now - edge - hold;
        if slack < 0 {
            self.violate(c, pin, &format!("hold {what}"), slack);
        }
    }
}

/// A circuit: its chips, how they're wired, and its state.
pub struct Sim {
    pub state: State,
    pub topo: Topology,
    pub chips: Vec<Chip>,
}

impl Sim {
    /// Wire up chips: `pins[c][p]` is the net on chip c's pin p.
    /// Returns the circuit and each chip's output slots, before the models
    /// exist; `finish` adds them.
    pub fn wire(net_names: Vec<String>, chips: Vec<ChipInfo>) -> (State, Topology, Vec<ChipInfo>) {
        let n = net_names.len();
        let mut topo = Topology {
            net_names,
            drivers: vec![Vec::new(); n],
            fanout: vec![Vec::new(); n],
            weak: vec![false; n],
        };
        let mut outs = Vec::new();
        let mut chips = chips;
        for (ci, c) in chips.iter_mut().enumerate() {
            c.outs = vec![None; c.pins.len()];
            for p in 0..c.pins.len() {
                let Some(net) = c.pins[p] else { continue };
                let k = c.kinds[p];
                if matches!(k, Kind::Out | Kind::Tri | Kind::Io | Kind::Pull) {
                    let o = outs.len() as u32;
                    let weak = k == Kind::Pull;
                    outs.push(Out {
                        net,
                        val: weak as u8,
                        en: matches!(k, Kind::Out | Kind::Pull),
                        weak,
                        pend: None,
                    });
                    c.outs[p] = Some(o);
                    topo.drivers[net as usize].push(o);
                    topo.weak[net as usize] |= weak;
                }
                if matches!(k, Kind::In | Kind::Io) {
                    topo.fanout[net as usize].push((ci as u32, p as u32));
                }
            }
        }
        let nets = vec![
            Net {
                val: 0,
                last: 0,
                float: true,
                cont_since: None
            };
            n
        ];
        let state = State {
            now: 0,
            nets,
            outs,
            events: Vec::new(),
            free: Vec::new(),
            queue: Queue::default(),
            event_count: 0,
            cycle: 0,
            cycle_start: 0,
            check_on: false,
            probe: vec![false; n],
            probe_from: 0,
            probe_to: 0,
            probe_log: Vec::new(),
            violations: Vec::new(),
            violation_stats: HashMap::new(),
            contention: ContentionStats::default(),
        };
        (state, topo, chips)
    }

    /// Let every model drive its initial outputs, in chip order, and the
    /// pull-ups take hold of their nets (a pull-up never changes, so
    /// nothing else would resolve a net only it drives).
    pub fn init(&mut self) {
        let Sim { state, topo, chips } = self;
        for chip in chips.iter_mut() {
            let mut cx = Ctx { state, topo };
            chip.model.init(&mut cx, &chip.info);
        }
        for n in 0..self.topo.weak.len() {
            if self.topo.weak[n] {
                self.resolve(n as u32);
            }
        }
    }

    /// Process every event strictly before `until`.
    pub fn run(&mut self, until: Time) {
        self.run_watch(until, None);
    }

    /// Process events strictly before `until`, but stop just after the
    /// event that makes net `watch` rise, and return its time. The chips
    /// that net goes to have seen the edge, but none of their outputs has
    /// changed yet (every delay is positive), so every other net still
    /// shows its value from before the edge.
    pub fn run_watch(&mut self, until: Time, watch: Option<u32>) -> Option<Time> {
        while let Some((t, idx)) = self.state.queue.pop(until) {
            self.state.free.push(idx);
            self.state.now = t;
            let ev = self.state.events[idx as usize];
            let out = &mut self.state.outs[ev.out as usize];
            if out.pend == Some(idx) {
                out.pend = None;
            }
            if out.val == ev.val && out.en == ev.en {
                continue;
            }
            out.val = ev.val;
            out.en = ev.en;
            let net = out.net;
            self.state.event_count += 1;
            let before = self.state.nets[net as usize].val;
            self.resolve(net);
            if watch == Some(net) && before == 0 && self.state.nets[net as usize].val == 1 {
                return Some(t);
            }
        }
        None
    }

    /// A driver of net n changed: work out the net's value, and if it
    /// changed, tell the chips it goes to.
    fn resolve(&mut self, n: u32) {
        let Sim { state, topo, chips } = self;
        let drivers = &topo.drivers[n as usize];
        let v = if drivers.len() == 1 && !topo.weak[n as usize] {
            let o = &state.outs[drivers[0] as usize];
            let net = &mut state.nets[n as usize];
            if !o.en {
                net.float = true;
                return;
            }
            net.float = false;
            o.val
        } else {
            let (mut cnt, mut conflict, mut val, mut pulled) = (0, false, 0, false);
            for &d in drivers {
                let o = &state.outs[d as usize];
                if o.weak {
                    pulled = true;
                } else if o.en {
                    if cnt == 0 {
                        val = o.val;
                    } else if o.val != val {
                        conflict = true;
                    }
                    cnt += 1;
                }
            }
            let now = state.now;
            let net = &mut state.nets[n as usize];
            if conflict {
                if net.cont_since.is_none() {
                    net.cont_since = Some(now);
                }
                return; // the value is undefined; keep the old one
            }
            if let Some(since) = net.cont_since.take() {
                state.record_contention(n, now - since, topo);
            }
            let net = &mut state.nets[n as usize];
            if cnt == 0 && !pulled {
                net.float = true;
                return;
            }
            net.float = false;
            if cnt == 0 { 1 } else { val }
        };
        let net = &mut state.nets[n as usize];
        if v == net.val {
            return;
        }
        net.val = v;
        net.last = state.now;
        if state.probe[n as usize] && state.now >= state.probe_from && state.now < state.probe_to {
            state.probe_log.push((state.now, n, v));
        }
        for &(ci, pin) in &topo.fanout[n as usize] {
            let chip = &mut chips[ci as usize];
            let mut cx = Ctx { state, topo };
            chip.model.eval(&mut cx, &chip.info, pin as usize);
        }
    }

    /// The chip with this reference.
    pub fn chip(&self, reference: &str) -> Option<usize> {
        self.chips
            .iter()
            .position(|c| c.info.reference == reference)
    }

    /// The net with this name.
    pub fn net(&self, name: &str) -> Option<u32> {
        self.topo
            .net_names
            .iter()
            .position(|n| n == name)
            .map(|i| i as u32)
    }
}
