//! Pin-level models of the devices in infra/devices: the TL16C550C UART,
//! the 82C54 timer and a CompactFlash card in True IDE mode. Their
//! registers and timing live there; these models connect them to pins,
//! check the strobe timing their datasheets ask for, and drive their
//! outputs.
//!
//! A read happens when its strobe starts (the chip drives the data after
//! "RD->D"), a write when its strobe ends. Strobes act only while the chip
//! is selected.

use devices::cf::CfCard;
use devices::i8254::Timer;
use devices::uart16550::Uart;

use crate::Error;
use crate::models::{Spec, bus_value, follow};
use crate::sim::{ChipInfo, Ctx, Time};

/// The strobe timing a device asks for, and the state needed to check it.
struct Strobes {
    /// Address (and chip select) setup before a strobe, hold after it.
    t_as: Time,
    t_ah: Time,
    /// Minimum widths of the read and the write strobe.
    t_rd: Time,
    t_wr: Time,
    /// Write data setup before the write strobe ends, and hold after.
    t_ds: Time,
    t_dh: Time,
    /// Data out after the read strobe starts, and off after it ends.
    d_rd: Time,
    d_rdz: Time,
    started: Time,
    ended: Option<Time>,
    wr_ended: Option<Time>,
}

impl Strobes {
    fn new(s: &Spec, names: [&str; 8], defaults: [Time; 8]) -> Strobes {
        let v = |i: usize| s.d_or(names[i], defaults[i]);
        Strobes {
            t_as: v(0),
            t_ah: v(1),
            t_rd: v(2),
            t_wr: v(3),
            t_ds: v(4),
            t_dh: v(5),
            d_rd: v(6),
            d_rdz: v(7),
            started: 0,
            ended: None,
            wr_ended: None,
        }
    }

    /// A strobe starts: the address pins must have been stable for t_as.
    fn start(&mut self, cx: &mut Ctx, c: &ChipInfo, addr: &[usize], pin: usize) {
        self.started = cx.now();
        let last = addr
            .iter()
            .map(|&p| cx.last_change(c, p))
            .fold(crate::sim::NEVER, Time::max);
        let slack = cx.now() - last - self.t_as;
        if slack < 0 {
            cx.violate(c, pin, "address setup to strobe", slack);
        }
    }

    /// A strobe ends: it must have been wide enough, and for a write the
    /// data must have been stable for t_ds.
    fn end(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize, write: Option<&[usize]>) {
        let width = if write.is_some() {
            self.t_wr
        } else {
            self.t_rd
        };
        let slack = cx.now() - self.started - width;
        if slack < 0 {
            cx.violate(c, pin, "strobe width", slack);
        }
        if let Some(data) = write {
            let last = data
                .iter()
                .map(|&p| cx.last_change(c, p))
                .fold(crate::sim::NEVER, Time::max);
            let slack = cx.now() - last - self.t_ds;
            if slack < 0 {
                cx.violate(c, pin, "write data setup", slack);
            }
            self.wr_ended = Some(cx.now());
        }
        self.ended = Some(cx.now());
    }

    /// An address pin changed: outside a strobe it must have been held
    /// t_ah after the last one; during one it mustn't change at all.
    fn address_changed(&self, cx: &mut Ctx, c: &ChipInfo, pin: usize, active: bool) {
        if active {
            cx.violate(c, pin, "address changed during strobe", 0);
        } else {
            cx.check_hold(c, pin, self.ended, self.t_ah, "address after strobe");
        }
    }

    fn data_changed(&self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        cx.check_hold(c, pin, self.wr_ended, self.t_dh, "write data after strobe");
    }
}

fn drive_bus(cx: &mut Ctx, c: &ChipInfo, pins: &[usize], v: u32, en: bool, d: Time) {
    for (i, &p) in pins.iter().enumerate() {
        let bit = ((v >> i) & 1) as u8;
        let bit = if en { bit } else { cx.driven(c, p) };
        cx.drive(c, p, bit, en, d);
    }
}

fn read_bus(cx: &Ctx, c: &ChipInfo, pins: &[usize]) -> u32 {
    bus_value(cx, c, pins) as u32
}

/// Which pins of a chip are which, for the eval dispatch.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Role {
    Other,
    Data,
    Addr,
    Strobe,
}

// ---------------------------------------------------------------- 16C550 UART

/// The TL16C550C: D0-D7, A0-A2, chip selects CS0, CS1 and CS2 (active low),
/// RD and WR (active low), MR (reset, active high), XIN (the baud clock,
/// counted on rising edges), and the outputs INTR, and RTS, DTR, OUT1,
/// OUT2 (active low). The serial line and the terminal are inside the
/// model: its preload is what the terminal types, its dump what it
/// received.
pub struct Uart16550 {
    pub core: Uart,
    d: [usize; 8],
    a: [usize; 3],
    cs0: usize,
    cs1: usize,
    cs2: usize,
    rd: usize,
    wr: usize,
    mr: usize,
    xin: usize,
    intr: usize,
    rts: usize,
    dtr: usize,
    out1: usize,
    out2: usize,
    role: Vec<Role>,
    st: Strobes,
    prev_xin: u8,
    reading: bool,
    writing: bool,
    outs: [u8; 5],
    d_out: Time,
}

impl Uart16550 {
    pub fn new(s: &Spec, preload: Option<&[u8]>) -> Result<Uart16550, Error> {
        let d = s.pins(|i| format!("D{i}"))?;
        let a = s.pins(|i| format!("A{i}"))?;
        let (cs0, cs1, cs2) = (s.pin("CS0")?, s.pin("CS1")?, s.pin("CS2")?);
        let (rd, wr) = (s.pin("RD")?, s.pin("WR")?);
        let mut role = vec![Role::Other; s.info.pin_names.len()];
        for &p in &d {
            role[p] = Role::Data;
        }
        for &p in a.iter().chain(&[cs0, cs1, cs2]) {
            role[p] = Role::Addr;
        }
        role[rd] = Role::Strobe;
        role[wr] = Role::Strobe;
        let mut core = Uart::new();
        if let Some(inp) = preload {
            core.rx_in.extend(inp.iter().copied());
        }
        Ok(Uart16550 {
            core,
            d,
            a,
            cs0,
            cs1,
            cs2,
            rd,
            wr,
            mr: s.pin("MR")?,
            xin: s.pin("XIN")?,
            intr: s.pin("INTR")?,
            rts: s.pin("RTS")?,
            dtr: s.pin("DTR")?,
            out1: s.pin("OUT1")?,
            out2: s.pin("OUT2")?,
            role,
            st: Strobes::new(
                s,
                [
                    "tAS",
                    "tAH",
                    "tRD",
                    "tWR",
                    "tDS",
                    "tDH",
                    "RD->D",
                    "RD->D dis",
                ],
                [15_000, 0, 50_000, 50_000, 15_000, 5_000, 40_000, 20_000],
            ),
            prev_xin: 0,
            reading: false,
            writing: false,
            outs: [2; 5],
            d_out: s.d_or("XIN->out", 30_000),
        })
    }

    pub fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        self.outputs(cx, c);
    }

    fn selected(&self, cx: &Ctx, c: &ChipInfo) -> bool {
        cx.input(c, self.cs0) == 1 && cx.input(c, self.cs1) == 1 && cx.input(c, self.cs2) == 0
    }

    fn reg(&self, cx: &Ctx, c: &ChipInfo) -> u8 {
        read_bus(cx, c, &self.a) as u8
    }

    /// Drive the outputs that changed.
    fn outputs(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        let u = &self.core;
        let now = [u.intr(), !u.rts(), !u.dtr(), !u.out1(), !u.out2()].map(u8::from);
        let pins = [self.intr, self.rts, self.dtr, self.out1, self.out2];
        for i in 0..5 {
            if now[i] != self.outs[i] {
                self.outs[i] = now[i];
                cx.drive(c, pins[i], now[i], true, self.d_out);
            }
        }
    }

    pub fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.xin {
            let v = cx.input(c, pin);
            if v == 1 && self.prev_xin == 0 {
                self.core.clock(1);
                self.outputs(cx, c);
            }
            self.prev_xin = v;
            return;
        }
        if pin == self.mr {
            if cx.input(c, pin) == 1 {
                self.core.reset();
                self.outputs(cx, c);
            }
            return;
        }
        match self.role[pin] {
            Role::Data => {
                if !self.reading {
                    self.st.data_changed(cx, c, pin);
                }
                return;
            }
            Role::Addr => {
                let active = self.reading || self.writing;
                self.st.address_changed(cx, c, pin, active);
            }
            Role::Strobe | Role::Other => {}
        }
        if !cx.state.check_on {
            return; // power-up and reset: the bus isn't meaningful yet
        }
        let sel = self.selected(cx, c);
        let rd = sel && cx.input(c, self.rd) == 0;
        let wr = sel && cx.input(c, self.wr) == 0;
        if rd && !self.reading {
            self.st.start(
                cx,
                c,
                &[
                    self.a[0], self.a[1], self.a[2], self.cs0, self.cs1, self.cs2,
                ],
                pin,
            );
            let v = self.core.read(self.reg(cx, c));
            drive_bus(cx, c, &self.d, v as u32, true, self.st.d_rd);
            self.outputs(cx, c);
        } else if !rd && self.reading {
            self.st.end(cx, c, pin, None);
            drive_bus(cx, c, &self.d, 0, false, self.st.d_rdz);
        }
        if wr && !self.writing {
            self.st.start(
                cx,
                c,
                &[
                    self.a[0], self.a[1], self.a[2], self.cs0, self.cs1, self.cs2,
                ],
                pin,
            );
        } else if !wr && self.writing {
            self.st.end(cx, c, pin, Some(&self.d.clone()));
            let v = read_bus(cx, c, &self.d) as u8;
            self.core.write(self.reg(cx, c), v);
            self.outputs(cx, c);
        }
        self.reading = rd;
        self.writing = wr;
    }
}

// ---------------------------------------------------------------- 82C54 timer

/// The 82C54: D0-D7, A0-A1, CS, RD and WR (active low), and for each
/// counter CLKn, GATEn and OUTn. Counters count on CLK's falling edges.
pub struct I8254 {
    pub core: Timer,
    d: [usize; 8],
    a: [usize; 2],
    cs: usize,
    rd: usize,
    wr: usize,
    clk: [usize; 3],
    gate: [usize; 3],
    out: [usize; 3],
    role: Vec<Role>,
    st: Strobes,
    prev_clk: [u8; 3],
    reading: bool,
    writing: bool,
    outs: [u8; 3],
    d_clk: Time,
    d_gate: Time,
    d_wr: Time,
}

impl I8254 {
    pub fn new(s: &Spec) -> Result<I8254, Error> {
        let d = s.pins(|i| format!("D{i}"))?;
        let a = s.pins(|i| format!("A{i}"))?;
        let (cs, rd, wr) = (s.pin("CS")?, s.pin("RD")?, s.pin("WR")?);
        let mut role = vec![Role::Other; s.info.pin_names.len()];
        for &p in &d {
            role[p] = Role::Data;
        }
        for &p in a.iter().chain(&[cs]) {
            role[p] = Role::Addr;
        }
        Ok(I8254 {
            core: Timer::new(),
            d,
            a,
            cs,
            rd,
            wr,
            clk: s.pins(|i| format!("CLK{i}"))?,
            gate: s.pins(|i| format!("GATE{i}"))?,
            out: s.pins(|i| format!("OUT{i}"))?,
            role,
            st: Strobes::new(
                s,
                [
                    "tAR",
                    "tRA",
                    "tRR",
                    "tWW",
                    "tDW",
                    "tWD",
                    "RD->D",
                    "RD->D dis",
                ],
                [30_000, 0, 95_000, 95_000, 95_000, 0, 120_000, 85_000],
            ),
            prev_clk: [0; 3],
            reading: false,
            writing: false,
            outs: [2; 3],
            d_clk: s.d_or("CLK->OUT", 150_000),
            d_gate: s.d_or("GATE->OUT", 120_000),
            d_wr: s.d_or("WR->OUT", 260_000),
        })
    }

    pub fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        for i in 0..3 {
            self.core.set_gate(i, cx.input(c, self.gate[i]) == 1);
        }
        self.outputs(cx, c, 0);
    }

    fn outputs(&mut self, cx: &mut Ctx, c: &ChipInfo, d: Time) {
        for i in 0..3 {
            let v = self.core.out(i) as u8;
            if v != self.outs[i] {
                self.outs[i] = v;
                cx.drive(c, self.out[i], v, true, d);
            }
        }
    }

    pub fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        for i in 0..3 {
            if pin == self.clk[i] {
                let v = cx.input(c, pin);
                if v == 0 && self.prev_clk[i] == 1 {
                    self.core.clock(i);
                    self.outputs(cx, c, self.d_clk);
                }
                self.prev_clk[i] = v;
                return;
            }
            if pin == self.gate[i] {
                self.core.set_gate(i, cx.input(c, pin) == 1);
                self.outputs(cx, c, self.d_gate);
                return;
            }
        }
        match self.role[pin] {
            Role::Data => {
                if !self.reading {
                    self.st.data_changed(cx, c, pin);
                }
                return;
            }
            Role::Addr => {
                let active = self.reading || self.writing;
                self.st.address_changed(cx, c, pin, active);
            }
            Role::Strobe | Role::Other => {}
        }
        if !cx.state.check_on {
            return;
        }
        let sel = cx.input(c, self.cs) == 0;
        let rd = sel && cx.input(c, self.rd) == 0;
        let wr = sel && cx.input(c, self.wr) == 0;
        let addr = [self.a[0], self.a[1], self.cs];
        if rd && !self.reading {
            self.st.start(cx, c, &addr, pin);
            let v = self.core.read(read_bus(cx, c, &self.a) as u8);
            drive_bus(cx, c, &self.d, v as u32, true, self.st.d_rd);
        } else if !rd && self.reading {
            self.st.end(cx, c, pin, None);
            drive_bus(cx, c, &self.d, 0, false, self.st.d_rdz);
        }
        if wr && !self.writing {
            self.st.start(cx, c, &addr, pin);
        } else if !wr && self.writing {
            self.st.end(cx, c, pin, Some(&self.d.clone()));
            let v = read_bus(cx, c, &self.d) as u8;
            self.core.write(read_bus(cx, c, &self.a) as u8, v);
            self.outputs(cx, c, self.d_wr);
        }
        self.reading = rd;
        self.writing = wr;
    }
}

// ---------------------------------------------------------------- CompactFlash card

/// A CompactFlash card in True IDE mode: D0-D15, A0-A2, CS0 and CS1
/// (active low), IORD and IOWR (active low), RESET (active low) and INTRQ.
/// WAKE is the simulator's: an "io" pin on a net of its own, which the
/// model uses to be woken when the card moves on by itself (BSY ending).
/// Its preload is the disk image, its dump the image at the end.
pub struct CompactFlash {
    pub core: CfCard,
    d: [usize; 16],
    a: [usize; 3],
    cs0: usize,
    cs1: usize,
    rd: usize,
    wr: usize,
    reset: usize,
    intrq: usize,
    wake: usize,
    addr_mask: Vec<u64>,
    addr: usize,
    role: Vec<Role>,
    st: Strobes,
    reading: bool,
    writing: bool,
    intr: u8,
    wake_at: Option<Time>,
    d_irq: Time,
}

impl CompactFlash {
    pub fn new(s: &Spec, preload: Option<&[u8]>) -> Result<CompactFlash, Error> {
        let d = s.pins(|i| format!("D{i}"))?;
        let a = s.pins(|i| format!("A{i}"))?;
        let (cs0, cs1) = (s.pin("CS0")?, s.pin("CS1")?);
        let (rd, wr) = (s.pin("IORD")?, s.pin("IOWR")?);
        let mut role = vec![Role::Other; s.info.pin_names.len()];
        for &p in &d {
            role[p] = Role::Data;
        }
        for &p in a.iter().chain(&[cs0, cs1]) {
            role[p] = Role::Addr;
        }
        let image = match preload {
            Some(img) => img.to_vec(),
            None => vec![0; 512 * s.param_or("sectors", 2048) as usize],
        };
        let mut core = CfCard::new(image);
        core.t_cmd_ns = s.param_or("t_cmd_ns", core.t_cmd_ns as i64) as u64;
        core.t_sector_ns = s.param_or("t_sector_ns", core.t_sector_ns as i64) as u64;
        core.t_reset_ns = s.param_or("t_reset_ns", core.t_reset_ns as i64) as u64;
        Ok(CompactFlash {
            core,
            addr_mask: s.masks(&a),
            addr: 0,
            d,
            a,
            cs0,
            cs1,
            rd,
            wr,
            reset: s.pin("RESET")?,
            intrq: s.pin("INTRQ")?,
            wake: s.pin("WAKE")?,
            role,
            st: Strobes::new(
                s,
                ["t1", "t9", "t2", "t2", "t3", "t4", "RD->D", "RD->D dis"],
                [
                    70_000, 20_000, 290_000, 290_000, 60_000, 30_000, 240_000, 30_000,
                ],
            ),
            reading: false,
            writing: false,
            intr: 2,
            wake_at: None,
            d_irq: s.d_or("INTRQ", 20_000),
        })
    }

    pub fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        self.addr = bus_value(cx, c, &self.a);
        cx.wake_done(c, self.wake);
        self.update(cx, c);
    }

    fn now_ns(cx: &Ctx) -> u64 {
        (cx.now().max(0) / 1000) as u64
    }

    /// Bring INTRQ up to date, and ask to be woken when the card next
    /// moves on by itself.
    fn update(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        let v = self.core.intrq() as u8;
        if v != self.intr {
            self.intr = v;
            cx.drive(c, self.intrq, v, true, self.d_irq);
        }
        if let Some(t) = self.core.next_event_ns() {
            let t = (t as Time) * 1000;
            if self.wake_at.is_none_or(|w| w > t || w <= cx.now()) {
                self.wake_at = Some(t);
                cx.wake(c, self.wake, t);
            }
        }
    }

    pub fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        follow(&mut self.addr, self.addr_mask[pin], cx.input(c, pin));
        let now = Self::now_ns(cx);
        if pin == self.wake {
            if cx.input(c, pin) == 1 {
                cx.wake_done(c, self.wake);
                if self.wake_at.is_some_and(|w| w <= cx.now()) {
                    self.wake_at = None;
                }
                self.core.advance(now);
                self.update(cx, c);
            }
            return;
        }
        if pin == self.reset {
            self.core.reset(now);
            self.update(cx, c);
            return;
        }
        match self.role[pin] {
            Role::Data => {
                if !self.reading {
                    self.st.data_changed(cx, c, pin);
                }
                return;
            }
            Role::Addr => {
                let active = self.reading || self.writing;
                self.st.address_changed(cx, c, pin, active);
            }
            Role::Strobe | Role::Other => {}
        }
        if !cx.state.check_on {
            return;
        }
        let (s0, s1) = (cx.input(c, self.cs0) == 0, cx.input(c, self.cs1) == 0);
        let sel = s0 || s1;
        let rd = sel && cx.input(c, self.rd) == 0;
        let wr = sel && cx.input(c, self.wr) == 0;
        let addr = [self.a[0], self.a[1], self.a[2], self.cs0, self.cs1];
        if rd && !self.reading {
            self.st.start(cx, c, &addr, pin);
            let v = self.core.read(s1, self.addr as u8, now);
            drive_bus(cx, c, &self.d, v as u32, true, self.st.d_rd);
        } else if !rd && self.reading {
            self.st.end(cx, c, pin, None);
            drive_bus(cx, c, &self.d, 0, false, self.st.d_rdz);
        }
        if wr && !self.writing {
            self.st.start(cx, c, &addr, pin);
        } else if !wr && self.writing {
            self.st.end(cx, c, pin, Some(&self.d.clone()));
            let v = read_bus(cx, c, &self.d) as u16;
            self.core.write(s1, self.addr as u8, v, now);
        }
        self.reading = rd;
        self.writing = wr;
        self.update(cx, c);
    }
}

// ---------------------------------------------------------------- PS/2 device

/// What a PS/2 device is doing.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Ps2State {
    Idle,
    /// Sending bit `n` of the frame: data set, clock low, clock high.
    Send(u8, u8),
    /// Receiving the host's bit `n`: clock low, clock high (sampled).
    Recv(u8, u8),
    /// The acknowledge: data low, a clock, data released.
    Ack(u8),
}

/// A PS/2 keyboard or mouse on the end of its cable: CLK and DATA are
/// open-collector lines (the board pulls them up). It sends its preload's
/// bytes, one frame each (a start bit, the byte low bit first, odd parity,
/// a stop bit), the data changing while the clock is high and the host
/// reading it as the clock falls, `start_ps` after power-up and `gap_ps`
/// apart, a clock's half period `half_ps`. A host that holds the clock low
/// inhibits it: a frame cut short is sent again. A host that pulls the
/// data low with the clock released asks to send: the device clocks in a
/// byte (sampled as the clock rises), acknowledges it, and answers 0xFA.
/// Its dump is the bytes the host sent. WAKE is the simulator's, on a net
/// of its own.
pub struct Ps2Device {
    clk: usize,
    data: usize,
    wake: usize,
    half: Time,
    gap: Time,
    queue: std::collections::VecDeque<u8>,
    pub received: Vec<u8>,
    state: Ps2State,
    frame: u16,
    shift: u16,
    next_send: Time,
    wake_at: Option<Time>,
}

impl Ps2Device {
    pub fn new(s: &Spec, preload: Option<&[u8]>) -> Result<Ps2Device, Error> {
        Ok(Ps2Device {
            clk: s.pin("CLK")?,
            data: s.pin("DATA")?,
            wake: s.pin("WAKE")?,
            half: s.param_or("half_ps", 40_000_000),
            gap: s.param_or("gap_ps", 500_000_000),
            queue: preload.unwrap_or(&[]).iter().copied().collect(),
            received: Vec::new(),
            state: Ps2State::Idle,
            frame: 0,
            shift: 0,
            next_send: s.param_or("start_ps", 1_000_000_000),
            wake_at: None,
        })
    }

    pub fn init(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        cx.wake_done(c, self.wake);
        cx.drive(c, self.clk, 1, false, 0);
        cx.drive(c, self.data, 1, false, 0);
        let t = self.next_send;
        self.wake_in(cx, c, t);
    }

    fn wake_in(&mut self, cx: &mut Ctx, c: &ChipInfo, t: Time) {
        if self.wake_at.is_none_or(|w| w > t || w <= cx.now()) {
            self.wake_at = Some(t);
            cx.wake(c, self.wake, t);
        }
    }

    fn line(cx: &mut Ctx, c: &ChipInfo, pin: usize, v: u8) {
        if v == 0 {
            cx.drive(c, pin, 0, true, 0);
        } else {
            cx.drive(c, pin, 1, false, 0);
        }
    }

    /// The host asks to send: the clock released, the data held low.
    fn rts(&self, cx: &Ctx, c: &ChipInfo) -> bool {
        cx.input(c, self.clk) == 1 && cx.input(c, self.data) == 0
    }

    fn step(&mut self, cx: &mut Ctx, c: &ChipInfo) {
        let now = cx.now();
        let (q, h) = (self.half / 2, self.half);
        match self.state {
            Ps2State::Idle => {
                if self.rts(cx, c) {
                    self.shift = 0;
                    self.state = Ps2State::Recv(0, 0);
                    self.wake_in(cx, c, now + q);
                } else if let Some(&b) = self.queue.front() {
                    if now < self.next_send {
                        let t = self.next_send;
                        self.wake_in(cx, c, t);
                    } else if cx.input(c, self.clk) == 1 && cx.input(c, self.data) == 1 {
                        let parity = 1 ^ (b.count_ones() as u16 & 1);
                        self.frame = (u16::from(b) << 1) | (parity << 9) | (1 << 10);
                        self.state = Ps2State::Send(0, 0);
                        self.wake_in(cx, c, now + q);
                    } else {
                        self.wake_in(cx, c, now + h);
                    }
                }
            }
            Ps2State::Send(n, phase) => match phase {
                0 => {
                    Self::line(cx, c, self.data, ((self.frame >> n) & 1) as u8);
                    self.state = Ps2State::Send(n, 1);
                    self.wake_in(cx, c, now + q);
                }
                1 => {
                    Self::line(cx, c, self.clk, 0);
                    self.state = Ps2State::Send(n, 2);
                    self.wake_in(cx, c, now + h);
                }
                2 => {
                    Self::line(cx, c, self.clk, 1);
                    self.state = Ps2State::Send(n, 3);
                    self.wake_in(cx, c, now + q);
                }
                _ => {
                    if cx.input(c, self.clk) == 0 {
                        // inhibited: the frame again later
                        Self::line(cx, c, self.data, 1);
                        self.state = Ps2State::Idle;
                        self.next_send = now + self.gap;
                        let t = self.next_send;
                        self.wake_in(cx, c, t);
                    } else if n == 10 {
                        Self::line(cx, c, self.data, 1);
                        self.queue.pop_front();
                        self.state = Ps2State::Idle;
                        self.next_send = now + self.gap;
                        let t = self.next_send;
                        self.wake_in(cx, c, t);
                    } else {
                        self.state = Ps2State::Send(n + 1, 0);
                        self.wake_in(cx, c, now + q);
                    }
                }
            },
            Ps2State::Recv(n, phase) => {
                if phase == 0 {
                    Self::line(cx, c, self.clk, 0);
                    self.state = Ps2State::Recv(n, 1);
                    self.wake_in(cx, c, now + h);
                } else {
                    Self::line(cx, c, self.clk, 1);
                    // sampled as the clock rises: data bits 0-7, parity, stop
                    self.shift |= u16::from(cx.input(c, self.data)) << n;
                    if n == 9 {
                        self.received.push((self.shift & 0xFF) as u8);
                        self.state = Ps2State::Ack(0);
                    } else {
                        self.state = Ps2State::Recv(n + 1, 0);
                    }
                    self.wake_in(cx, c, now + h);
                }
            }
            Ps2State::Ack(phase) => match phase {
                0 => {
                    Self::line(cx, c, self.data, 0);
                    self.state = Ps2State::Ack(1);
                    self.wake_in(cx, c, now + q);
                }
                1 => {
                    Self::line(cx, c, self.clk, 0);
                    self.state = Ps2State::Ack(2);
                    self.wake_in(cx, c, now + h);
                }
                2 => {
                    Self::line(cx, c, self.clk, 1);
                    self.state = Ps2State::Ack(3);
                    self.wake_in(cx, c, now + q);
                }
                _ => {
                    Self::line(cx, c, self.data, 1);
                    self.queue.push_front(0xFA);
                    self.state = Ps2State::Idle;
                    self.next_send = now + self.gap;
                    let t = self.next_send;
                    self.wake_in(cx, c, t);
                }
            },
        }
    }

    pub fn eval(&mut self, cx: &mut Ctx, c: &ChipInfo, pin: usize) {
        if pin == self.wake {
            if cx.input(c, pin) == 1 {
                cx.wake_done(c, self.wake);
                if self.wake_at.is_some_and(|w| w <= cx.now()) {
                    self.wake_at = None;
                    self.step(cx, c);
                }
            }
            return;
        }
        // the host's request to send, seen while idle
        if self.state == Ps2State::Idle && self.rts(cx, c) {
            let t = cx.now() + self.half / 2;
            self.wake_in(cx, c, t);
        }
    }
}
