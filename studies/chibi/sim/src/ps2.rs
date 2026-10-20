//! The PS/2 ports, at the lines: each port's GAL (draft.py's U_KBD and
//! U_MOUSE) and the device on it, a keyboard or a mouse.
//!
//! **The port's GAL**, on the master clock: E sets two ticks after the
//! clock line falls (its synchroniser) and a write at the port's +0 (+2)
//! clears it; the interrupt and the two pull-downs are a register written
//! at +4 (+6): bit 3 the interrupt, bit 4 pulls the clock low, bit 5 the
//! data. A read gives the data line in bit 0 and E in bit 1. The device
//! task (routines2.device) takes each edge and shifts the bit in.
//!
//! **The device** sends a byte as a frame of 11 bits (a start bit, the
//! data LSB first, odd parity, a stop bit): each bit put on the data line
//! a quarter of a clock period before the clock falls, the clock low for
//! half a period and high for half, as system2.py's model and the
//! chip-level simulator's ps2dev do; then a gap. It sends only while the
//! clock line is high: the host holding it low inhibits it, and a frame
//! cut off before its stop bit is sent again. The host sends by holding
//! the clock low, pulling the data low and letting the clock go: the
//! device then clocks 10 bits in (sampling the data line as the clock
//! rises), pulls the data low for the eleventh clock (the ack), and
//! answers. The keyboard speaks scan code set 2 and the mouse the
//! standard 3-byte packets, and both answer the commands a driver sends
//! at start-up (Fen's board's set, studies/fen/board/src/ps2.rs).
//!
//! A mouse powers up with reporting off, as a real one does; `reporting`
//! starts it on.

use std::collections::VecDeque;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Keyboard,
    Mouse,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum State {
    /// Lines released, nothing to send.
    Idle,
    /// A frame's bit: 0 its data goes on the line, 1 the clock falls, 2 it
    /// rises.
    Send { frame: u16, bit: u8, phase: u8 },
    /// After a frame (or a command), before the next.
    Gap,
    /// The host holds the clock low.
    Inhibited,
    /// The host sends: bit k's clock falls (phase 0), rises and the bit is
    /// sampled (1); then the ack (2: data low, 3: the clock falls, 4: it
    /// rises and both lines go).
    Recv { bits: u16, bit: u8, phase: u8 },
}

const DEVICE_BUFFER: usize = 16;

#[derive(Clone, Debug)]
pub struct Port {
    pub kind: Kind,
    // the port's GAL
    pub e: bool,
    pub irq: bool,
    pub pull_clk: bool,
    pub pull_data: bool,
    e_at: Option<u64>,
    // the device's drivers: true released (high)
    dclk: bool,
    ddata: bool,
    state: State,
    next: u64,
    /// Bytes the device has to send.
    pub queue: VecDeque<u8>,
    /// Bytes the host has sent the device.
    pub received: Vec<u8>,
    /// The ticks of half a clock period, of a quarter, of the gap after
    /// a frame, and the device's wait before it answers or starts.
    half: u64,
    gap: u64,
    settle: u64,
    /// The device may start sending from here (power-on's self-test).
    ready_at: u64,
    want_arg: Option<u8>,
    pub reporting: bool,
    sample_ticks: u64,
    us: f64,
    dx: i32,
    dy: i32,
    buttons: u8,
    reported_buttons: u8,
    next_sample: u64,
}

impl Port {
    /// A port and its device; `us` is the ticks of a microsecond, `ready_us`
    /// when after power-on the device may first send.
    pub fn new(kind: Kind, us: f64, ready_us: f64) -> Port {
        let t = |x: f64| (x * us).round() as u64;
        Port {
            kind,
            e: false,
            irq: false,
            pull_clk: false,
            pull_data: false,
            e_at: None,
            dclk: true,
            ddata: true,
            state: State::Idle,
            next: u64::MAX,
            queue: VecDeque::new(),
            received: Vec::new(),
            half: t(40.0),
            gap: t(200.0),
            settle: t(50.0),
            ready_at: t(ready_us),
            want_arg: None,
            reporting: kind == Kind::Keyboard,
            sample_ticks: t(10_000.0),
            us,
            dx: 0,
            dy: 0,
            buttons: 0,
            reported_buttons: 0,
            next_sample: 0,
        }
    }

    /// Reset: the GAL's registers (the device has power of its own).
    pub fn reset(&mut self, now: u64) {
        let was = self.clk_line();
        self.e = false;
        self.e_at = None;
        self.irq = false;
        self.pull_clk = false;
        self.pull_data = false;
        self.lines_changed(now, was);
    }

    pub fn clk_line(&self) -> bool {
        self.dclk && !self.pull_clk
    }

    pub fn data_line(&self) -> bool {
        self.ddata && !self.pull_data
    }

    /// What a read of the port gives (bit 0 the data line, bit 1 E).
    pub fn read(&self) -> u16 {
        self.data_line() as u16 | (self.e as u16) << 1
    }

    /// A write at the port's +0 (+2): the edge taken.
    pub fn take_edge(&mut self) {
        self.e = false;
    }

    /// A write at the port's +4 (+6) at `now`: the interrupt and the
    /// pulls.
    pub fn write_control(&mut self, v: u16, now: u64) {
        let was = self.clk_line();
        let was_pulling = self.pull_clk;
        self.irq = v & 8 != 0;
        self.pull_clk = v & 16 != 0;
        self.pull_data = v & 32 != 0;
        self.lines_changed(now, was);
        if self.pull_clk && !was_pulling && matches!(self.state, State::Idle | State::Gap) {
            self.state = State::Inhibited;
            self.next = u64::MAX;
        }
        if !self.pull_clk && was_pulling && self.state == State::Inhibited {
            if self.pull_data {
                // a request to send: the device clocks the byte in
                self.state = State::Recv {
                    bits: 0,
                    bit: 0,
                    phase: 0,
                };
            } else {
                self.state = State::Gap;
            }
            self.next = now + self.settle;
        }
    }

    fn lines_changed(&mut self, now: u64, clk_was: bool) {
        if clk_was && !self.clk_line() && self.e_at.is_none() {
            self.e_at = Some(now + 2);
        }
    }

    /// When the port next changes by itself.
    pub fn next_event(&self) -> u64 {
        let mut n = self.next.min(self.e_at.unwrap_or(u64::MAX));
        if self.kind == Kind::Mouse && self.reporting && self.moving() {
            n = n.min(self.next_sample);
        }
        n
    }

    /// Bring the port up to `t`.
    pub fn advance(&mut self, t: u64) {
        loop {
            let e = self.e_at.unwrap_or(u64::MAX);
            let s = if self.kind == Kind::Mouse && self.reporting && self.moving() {
                self.next_sample
            } else {
                u64::MAX
            };
            let n = self.next.min(e).min(s);
            if n > t {
                return;
            }
            if e == n {
                self.e = true;
                self.e_at = None;
            } else if s == n {
                self.sample();
                self.next_sample = n + self.sample_ticks;
                self.wake(n);
            } else {
                self.step(n);
            }
        }
    }

    /// Something to send: start if the line is free.
    fn wake(&mut self, now: u64) {
        if self.state == State::Idle && !self.queue.is_empty() {
            self.next = now.max(self.ready_at);
        }
    }

    fn step(&mut self, now: u64) {
        let q = self.half / 2;
        let was = self.clk_line();
        match self.state {
            State::Idle | State::Gap => {
                self.state = State::Idle;
                self.next = u64::MAX;
                if now < self.ready_at {
                    self.next = self.ready_at;
                } else if !self.clk_line() {
                    self.state = State::Inhibited;
                } else if let Some(b) = self.queue.pop_front() {
                    let parity = (b.count_ones() & 1 == 0) as u16;
                    let frame = (b as u16) << 1 | parity << 9 | 1 << 10;
                    self.state = State::Send {
                        frame,
                        bit: 0,
                        phase: 0,
                    };
                    self.next = now;
                }
            }
            State::Send { frame, bit, phase } => {
                if self.pull_clk {
                    // inhibited: the frame again later, unless it's done
                    self.dclk = true;
                    self.ddata = true;
                    if bit < 10 {
                        self.queue.push_front((frame >> 1) as u8);
                    }
                    self.state = State::Inhibited;
                    self.next = u64::MAX;
                } else {
                    match phase {
                        0 => {
                            self.ddata = frame >> bit & 1 != 0;
                            self.next = now + q;
                        }
                        1 => {
                            self.dclk = false;
                            self.next = now + self.half;
                        }
                        _ => {
                            self.dclk = true;
                            self.next = now + q;
                        }
                    }
                    self.state = if phase < 2 {
                        State::Send {
                            frame,
                            bit,
                            phase: phase + 1,
                        }
                    } else if bit < 10 {
                        State::Send {
                            frame,
                            bit: bit + 1,
                            phase: 0,
                        }
                    } else {
                        // the next frame's first bit a gap after this
                        // frame's 22 half periods, as system2.py has it
                        self.ddata = true;
                        self.next = now + q + self.gap;
                        State::Gap
                    };
                }
            }
            State::Inhibited => self.next = u64::MAX,
            State::Recv { bits, bit, phase } => {
                if self.pull_clk {
                    self.dclk = true;
                    self.ddata = true;
                    self.state = State::Inhibited;
                    self.next = u64::MAX;
                } else {
                    let (state, next) = match phase {
                        0 => {
                            self.dclk = false;
                            (
                                State::Recv {
                                    bits,
                                    bit,
                                    phase: 1,
                                },
                                now + self.half,
                            )
                        }
                        1 => {
                            self.dclk = true;
                            let bits = bits | (self.data_line() as u16) << bit;
                            if bit == 9 {
                                (
                                    State::Recv {
                                        bits,
                                        bit,
                                        phase: 2,
                                    },
                                    now + q,
                                )
                            } else {
                                let s = State::Recv {
                                    bits,
                                    bit: bit + 1,
                                    phase: 0,
                                };
                                (s, now + self.half)
                            }
                        }
                        2 => {
                            self.ddata = false;
                            (
                                State::Recv {
                                    bits,
                                    bit,
                                    phase: 3,
                                },
                                now + q,
                            )
                        }
                        3 => {
                            self.dclk = false;
                            (
                                State::Recv {
                                    bits,
                                    bit,
                                    phase: 4,
                                },
                                now + self.half,
                            )
                        }
                        _ => {
                            self.dclk = true;
                            self.ddata = true;
                            let b = bits as u8;
                            let odd = (bits & 0x1FF).count_ones() & 1 == 1;
                            if odd && bits >> 9 & 1 == 1 {
                                self.received.push(b);
                                self.command(b);
                            } else {
                                self.send(&[0xFE]);
                            }
                            (State::Gap, now + self.gap + self.settle)
                        }
                    };
                    self.state = state;
                    self.next = next;
                }
            }
        }
        self.lines_changed(now, was);
    }

    fn send(&mut self, bytes: &[u8]) {
        for &b in bytes {
            if self.queue.len() < DEVICE_BUFFER {
                self.queue.push_back(b);
            }
        }
    }

    /// Bytes to send, as they are (a test's, or a device's answer).
    pub fn push(&mut self, bytes: &[u8], now: u64) {
        self.queue.extend(bytes.iter().copied());
        self.wake(now);
    }

    /// A key went down or up: `code` is its set 2 make code, 0xE0xx for
    /// the extended keys.
    pub fn key(&mut self, code: u16, down: bool, now: u64) {
        if !self.reporting {
            return;
        }
        let mut bytes = Vec::new();
        if code >> 8 == 0xE0 {
            bytes.push(0xE0);
        }
        if !down {
            bytes.push(0xF0);
        }
        bytes.push(code as u8);
        if self.queue.len() + bytes.len() <= DEVICE_BUFFER {
            self.send(&bytes);
        }
        self.wake(now);
    }

    fn moving(&self) -> bool {
        (self.dx, self.dy) != (0, 0) || self.buttons != self.reported_buttons
    }

    /// The mouse moved by (dx, dy), y up as PS/2 counts it, with `buttons`
    /// held (bit 0 left, 1 right, 2 middle).
    pub fn mouse(&mut self, dx: i32, dy: i32, buttons: u8, now: u64) {
        if !self.moving() {
            self.next_sample = self.next_sample.max(now);
        }
        self.dx += dx;
        self.dy += dy;
        self.buttons = buttons & 7;
    }

    /// A mouse sample: a packet if anything changed.
    fn sample(&mut self) {
        if !self.moving() || self.queue.len() + 3 > DEVICE_BUFFER {
            return;
        }
        let clamp = |v: i32| v.clamp(-255, 255);
        let (x, y) = (clamp(self.dx), clamp(self.dy));
        let (ovx, ovy) = (self.dx != x, self.dy != y);
        self.dx = if ovx { 0 } else { self.dx - x };
        self.dy = if ovy { 0 } else { self.dy - y };
        let b0 = self.buttons
            | 8
            | ((x < 0) as u8) << 4
            | ((y < 0) as u8) << 5
            | (ovx as u8) << 6
            | (ovy as u8) << 7;
        self.reported_buttons = self.buttons;
        self.send(&[b0, x as u8, y as u8]);
    }

    /// A byte from the host: a command, or a command's argument.
    fn command(&mut self, b: u8) {
        if let Some(cmd) = self.want_arg.take() {
            if cmd == 0xF3 && self.kind == Kind::Mouse && b != 0 {
                self.sample_ticks = (1e6 / b as f64 * self.us) as u64;
            }
            self.send(&[0xFA]);
            return;
        }
        match (self.kind, b) {
            (_, 0xFF) => {
                self.queue.clear();
                self.reporting = self.kind == Kind::Keyboard;
                (self.dx, self.dy) = (0, 0);
                match self.kind {
                    Kind::Keyboard => self.send(&[0xFA, 0xAA]),
                    Kind::Mouse => self.send(&[0xFA, 0xAA, 0x00]),
                }
            }
            (Kind::Keyboard, 0xF2) => self.send(&[0xFA, 0xAB, 0x83]),
            (Kind::Mouse, 0xF2) => self.send(&[0xFA, 0x00]),
            (_, 0xF4) => {
                self.reporting = true;
                self.send(&[0xFA]);
            }
            (_, 0xF5) => {
                self.reporting = false;
                self.send(&[0xFA]);
            }
            (_, 0xEE) if self.kind == Kind::Keyboard => self.send(&[0xEE]),
            (_, 0xED | 0xF3 | 0xE8 | 0xF0) => {
                self.want_arg = Some(b);
                self.send(&[0xFA]);
            }
            (Kind::Mouse, 0xE9) => self.send(&[0xFA, 0x00, 0x02, 100]),
            _ => self.send(&[0xFA]),
        }
    }
}

/// Set 2 make codes, by the names browsers give keys (KeyboardEvent.code).
pub fn scancode(name: &str) -> Option<u16> {
    let letters = [
        0x1C, 0x32, 0x21, 0x23, 0x24, 0x2B, 0x34, 0x33, 0x43, 0x3B, 0x42, 0x4B, 0x3A, 0x31, 0x44,
        0x4D, 0x15, 0x2D, 0x1B, 0x2C, 0x3C, 0x2A, 0x1D, 0x22, 0x35, 0x1A,
    ];
    if let Some(c) = name.strip_prefix("Key")
        && c.len() == 1
    {
        let i = c.as_bytes()[0].wrapping_sub(b'A') as usize;
        return letters.get(i).copied();
    }
    let digits = [0x45, 0x16, 0x1E, 0x26, 0x25, 0x2E, 0x36, 0x3D, 0x3E, 0x46];
    if let Some(c) = name.strip_prefix("Digit")
        && c.len() == 1
    {
        let i = c.as_bytes()[0].wrapping_sub(b'0') as usize;
        return digits.get(i).copied();
    }
    Some(match name {
        "Backquote" => 0x0E,
        "Minus" => 0x4E,
        "Equal" => 0x55,
        "Backspace" => 0x66,
        "Tab" => 0x0D,
        "BracketLeft" => 0x54,
        "BracketRight" => 0x5B,
        "Backslash" => 0x5D,
        "Semicolon" => 0x4C,
        "Quote" => 0x52,
        "Enter" => 0x5A,
        "ShiftLeft" => 0x12,
        "ShiftRight" => 0x59,
        "Comma" => 0x41,
        "Period" => 0x49,
        "Slash" => 0x4A,
        "ControlLeft" => 0x14,
        "AltLeft" => 0x11,
        "Space" => 0x29,
        "Escape" => 0x76,
        "ArrowUp" => 0xE075,
        "ArrowDown" => 0xE072,
        "ArrowLeft" => 0xE06B,
        "ArrowRight" => 0xE074,
        _ => return None,
    })
}
