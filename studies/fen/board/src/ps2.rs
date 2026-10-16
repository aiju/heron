//! Two PS/2 ports, a keyboard on one and a mouse on the other: RFC
//! 0009's "a shift register, bit counter and interrupt each". A port holds
//! one received byte; while it's unread the port holds the clock line low,
//! so the device keeps the rest in its own buffer. A byte takes 11 bits at
//! about 12 kHz, a little under a millisecond, to come in.
//!
//! The keyboard speaks scan code set 2, the mouse the standard 3-byte
//! protocol, and both answer the commands a driver sends at start-up
//! (reset, identify, enable, LEDs, sample rate, ...) with ACK (0xFA) and
//! what each returns. Neither does anything else with them.
//!
//! Each port, 32 bits:
//!   +0  R: the received byte (reading empties the port)
//!       W: a byte to the device
//!   +4  R: bit 0 a byte has been received, bit 1 sending to the device,
//!       bit 2 interrupts on
//!       W: bit 2 interrupts on (an interrupt while a byte waits)

use std::collections::VecDeque;

/// 11 bits at 12 kHz.
pub const BYTE_NS: u64 = 917_000;
/// A keyboard's buffer holds 16 bytes; past that, keys are lost.
const DEVICE_BUFFER: usize = 16;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Keyboard,
    Mouse,
}

#[derive(Clone, Debug)]
pub struct Port {
    pub kind: Kind,
    /// Bytes the device has to send.
    pub queue: VecDeque<u8>,
    /// The byte the port holds, if any.
    rx: Option<u8>,
    /// The byte coming in, and when it will have.
    incoming: Option<(u8, u64)>,
    pub irq_enable: bool,
    /// A command that takes an argument byte next.
    want_arg: Option<u8>,
    /// Sending to the device ends at this time.
    tx_until: u64,
    /// The mouse: reporting on, its sample period, the motion and buttons
    /// not reported yet, and when the next sample is due.
    reporting: bool,
    sample_ns: u64,
    dx: i32,
    dy: i32,
    buttons: u8,
    reported_buttons: u8,
    next_sample: u64,
}

impl Port {
    pub fn new(kind: Kind) -> Port {
        Port {
            kind,
            queue: VecDeque::new(),
            rx: None,
            incoming: None,
            irq_enable: false,
            want_arg: None,
            tx_until: 0,
            reporting: kind == Kind::Keyboard,
            sample_ns: 10_000_000,
            dx: 0,
            dy: 0,
            buttons: 0,
            reported_buttons: 0,
            next_sample: 0,
        }
    }

    fn send(&mut self, bytes: &[u8]) {
        for &b in bytes {
            if self.queue.len() < DEVICE_BUFFER {
                self.queue.push_back(b);
            }
        }
    }

    /// A key went down or up: `code` is its set 2 make code, 0xE0xx for
    /// the extended keys. The Pause key's sequence isn't supported.
    pub fn key(&mut self, code: u16, down: bool) {
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
    }

    /// The mouse moved by (dx, dy), up being positive y as PS/2 counts it,
    /// and its buttons are `buttons` (bit 0 left, 1 right, 2 middle).
    pub fn mouse(&mut self, dx: i32, dy: i32, buttons: u8) {
        self.dx += dx;
        self.dy += dy;
        self.buttons = buttons & 7;
    }

    /// The next byte starts coming in when the port is free.
    fn start_incoming(&mut self, now_ns: u64) {
        if self.rx.is_none()
            && self.incoming.is_none()
            && let Some(b) = self.queue.pop_front()
        {
            self.incoming = Some((b, now_ns.max(self.tx_until) + BYTE_NS));
        }
    }

    /// A mouse sample: a packet if anything changed.
    fn sample(&mut self) {
        if (self.dx, self.dy) == (0, 0) && self.buttons == self.reported_buttons {
            return;
        }
        if self.queue.len() + 3 > DEVICE_BUFFER {
            return;
        }
        let clamp = |v: i32| v.clamp(-255, 255);
        let (x, y) = (clamp(self.dx), clamp(self.dy));
        let ovx = self.dx != x;
        let ovy = self.dy != y;
        self.dx -= x;
        self.dy -= y;
        if ovx {
            self.dx = 0;
        }
        if ovy {
            self.dy = 0;
        }
        let b0 = self.buttons
            | 8
            | ((x < 0) as u8) << 4
            | ((y < 0) as u8) << 5
            | (ovx as u8) << 6
            | (ovy as u8) << 7;
        self.reported_buttons = self.buttons;
        self.send(&[b0, x as u8, y as u8]);
    }

    pub fn advance(&mut self, now_ns: u64) {
        if self.kind == Kind::Mouse && self.reporting && now_ns >= self.next_sample {
            self.sample();
            self.next_sample = now_ns + self.sample_ns;
        }
        if let Some((b, t)) = self.incoming
            && t <= now_ns
        {
            self.incoming = None;
            self.rx = Some(b);
        }
        self.start_incoming(now_ns);
    }

    pub fn irq(&self) -> bool {
        self.irq_enable && self.rx.is_some()
    }

    /// When the port next changes by itself.
    pub fn next_ns(&self, now_ns: u64) -> Option<u64> {
        let mut next = self.incoming.map(|(_, t)| t);
        let moving = (self.dx, self.dy) != (0, 0) || self.buttons != self.reported_buttons;
        if self.kind == Kind::Mouse && self.reporting && moving {
            let t = self.next_sample.max(now_ns + 1);
            next = Some(next.map_or(t, |n| n.min(t)));
        }
        next
    }

    /// A byte from the host: a command, or a command's argument.
    fn command(&mut self, b: u8) {
        if let Some(cmd) = self.want_arg.take() {
            if cmd == 0xF3 && self.kind == Kind::Mouse && b != 0 {
                self.sample_ns = 1_000_000_000 / b as u64;
            }
            self.send(&[0xFA]);
            return;
        }
        match (self.kind, b) {
            (_, 0xFF) => {
                // reset: the self-test passes
                self.queue.clear();
                self.reporting = self.kind == Kind::Keyboard;
                self.dx = 0;
                self.dy = 0;
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
            (_, 0xED | 0xF3 | 0xE8 | 0xF0) => {
                self.want_arg = Some(b);
                self.send(&[0xFA]);
            }
            (Kind::Mouse, 0xE9) => self.send(&[0xFA, 0x00, 0x02, 100]),
            _ => self.send(&[0xFA]),
        }
    }

    pub fn read(&mut self, reg: u32, now_ns: u64) -> u32 {
        self.advance(now_ns);
        match reg {
            0 => {
                let v = self.rx.take().unwrap_or(0) as u32;
                self.start_incoming(now_ns);
                v
            }
            4 => {
                self.rx.is_some() as u32
                    | ((now_ns < self.tx_until) as u32) << 1
                    | (self.irq_enable as u32) << 2
            }
            _ => 0,
        }
    }

    pub fn write(&mut self, reg: u32, v: u32, now_ns: u64) {
        self.advance(now_ns);
        match reg {
            0 => {
                // the host pulls the clock low and sends the byte: about two
                // byte times before the device's answer starts
                self.tx_until = now_ns + 2 * BYTE_NS;
                self.command(v as u8);
                self.start_incoming(now_ns);
            }
            4 => self.irq_enable = v & 4 != 0,
            _ => {}
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
    let f = [
        0x05, 0x06, 0x04, 0x0C, 0x03, 0x0B, 0x83, 0x0A, 0x01, 0x09, 0x78, 0x07,
    ];
    if let Some(n) = name.strip_prefix('F')
        && let Ok(n) = n.parse::<usize>()
        && (1..=12).contains(&n)
    {
        return Some(f[n - 1]);
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
        "CapsLock" => 0x58,
        "Semicolon" => 0x4C,
        "Quote" => 0x52,
        "Enter" => 0x5A,
        "ShiftLeft" => 0x12,
        "Comma" => 0x41,
        "Period" => 0x49,
        "Slash" => 0x4A,
        "ShiftRight" => 0x59,
        "ControlLeft" => 0x14,
        "AltLeft" => 0x11,
        "Space" => 0x29,
        "AltRight" => 0xE011,
        "ControlRight" => 0xE014,
        "MetaLeft" => 0xE01F,
        "MetaRight" => 0xE027,
        "Escape" => 0x76,
        "Insert" => 0xE070,
        "Delete" => 0xE071,
        "Home" => 0xE06C,
        "End" => 0xE069,
        "PageUp" => 0xE07D,
        "PageDown" => 0xE07A,
        "ArrowUp" => 0xE075,
        "ArrowDown" => 0xE072,
        "ArrowLeft" => 0xE06B,
        "ArrowRight" => 0xE074,
        "NumLock" => 0x77,
        "ScrollLock" => 0x7E,
        "IntlBackslash" => 0x61,
        _ => return None,
    })
}
