//! The `mini` board: Heron Mini (studies/mini, RFC 0041) with the video
//! options of RFC 0042, running studies/mini_gfx's programs. The machine
//! is the mini study's register-transfer model, tick for tick; its
//! "cycles" here are the master clock's ticks (50.35 MHz), so the page's
//! time is the machine's.
//!
//! The keyboard and the mouse go to UART 1 as studies/mini_gfx's input
//! packets (rt/input.h): a key down or up with its key code, the mouse's
//! position (the board keeps it, from the page's motion, on the screen of
//! the mode it shows) and its buttons. The terminal is the simulations'
//! console (the test card's I/O page).
//!
//! Parameters, each the default unless given:
//! - `layout`: the pixel layout, L0 or L1;
//! - `bandwidth`: B0, B1 or B2.
//!
//! Loads: `rom`, the control store (studies/websim/machines.py packs
//! studies/mini/sim.py's), at 0; `ram` at a physical address.

use mini_engine::video::{Bandwidth, Layout};
use mini_engine::{Board as VideoBoard, Cpu, FIELDS, Rom, System};

use crate::{Board, Load, Params, Status};

/// The master clock: two ticks a VGA pixel.
const CLOCK_HZ: f64 = 50_350_000.0;

pub struct Mini {
    cpu: Cpu,
    sys: System,
    mouse: (i32, i32),
    buttons: u8,
    shown: u64,
}

/// The control store from its blob: little-endian words, `n` distinct
/// microwords of FIELDS.len() values each, then 2^17 indices, then entry,
/// refill, irq, the four fault addresses and the four lengths.
fn rom(blob: &[u8]) -> Result<Rom, String> {
    let w: Vec<u32> = blob
        .chunks_exact(4)
        .map(|c| u32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect();
    let nf = FIELDS.len();
    let n = *w.first().ok_or("an empty control store")? as usize;
    let words_end = 1 + n * nf;
    let index_end = words_end + (1 << 17);
    if w.len() != index_end + 11 {
        return Err(format!(
            "the control store's blob is {} words, not {}",
            w.len(),
            index_end + 11
        ));
    }
    let words = w[1..words_end]
        .chunks(nf)
        .map(|c| c.try_into().expect("a microword"))
        .collect();
    let index = w[words_end..index_end].iter().map(|&i| i as i32).collect();
    let t = &w[index_end..];
    Ok(Rom {
        words,
        index,
        entry: t[0],
        refill: t[1],
        irq: t[2],
        fault: [t[3], t[4], t[5], t[6]],
        lengths: [t[7] as u64, t[8] as u64, t[9] as u64, t[10] as u64],
    })
}

impl Mini {
    pub fn new(p: &mut Params, loads: &[Load]) -> Result<Mini, String> {
        let layout = match p.text("layout").unwrap_or("L0") {
            "L0" => Layout::L0,
            "L1" => Layout::L1,
            l => return Err(format!("layout: L0 or L1, not {l:?}")),
        };
        let bandwidth = match p.text("bandwidth").unwrap_or("B0") {
            "B0" => Bandwidth::B0,
            "B1" => Bandwidth::B1,
            "B2" => Bandwidth::B2,
            b => return Err(format!("bandwidth: B0, B1 or B2, not {b:?}")),
        };
        let blob = loads
            .iter()
            .find(|l| l.target == "rom")
            .ok_or("the mini board needs its control store (a rom load)")?;
        let cpu = Cpu::new(rom(&blob.bytes)?, 2, false, false)?;
        let mut sys = System::new(VideoBoard {
            layout,
            bandwidth,
            ..VideoBoard::default()
        });
        let size = sys.ram.len();
        for l in loads {
            match l.target.as_str() {
                "ram" if l.at as usize + l.bytes.len() <= size => {
                    let a = l.at as usize;
                    sys.ram[a..a + l.bytes.len()].copy_from_slice(&l.bytes);
                }
                "ram" => {
                    return Err(format!(
                        "{} bytes at {:#X} don't fit in RAM",
                        l.bytes.len(),
                        l.at
                    ));
                }
                "rom" => {}
                t => return Err(format!("the mini board has nothing to load called {t:?}")),
            }
        }
        Ok(Mini {
            cpu,
            sys,
            mouse: (320, 240),
            buttons: 0,
            shown: 0,
        })
    }

    fn send_mouse(&mut self) {
        let (x, y) = (self.mouse.0 as u32, self.mouse.1 as u32);
        let p = [
            0x82,
            self.buttons & 7,
            (x & 127) as u8,
            (x >> 7 & 127) as u8,
            (y & 127) as u8,
            (y >> 7 & 127) as u8,
        ];
        self.sys.uarts[1].inp.extend_from_slice(&p);
    }
}

/// A browser's key (KeyboardEvent.code) as studies/mini_gfx's key code.
fn key_code(name: &str) -> Option<u8> {
    if let Some(l) = name.strip_prefix("Key") {
        let c = l.as_bytes();
        if c.len() == 1 && c[0].is_ascii_uppercase() {
            return Some(c[0].to_ascii_lowercase());
        }
    }
    if let Some(d) = name.strip_prefix("Digit") {
        let c = d.as_bytes();
        if c.len() == 1 && c[0].is_ascii_digit() {
            return Some(c[0]);
        }
    }
    if let Some(Ok(n)) = name.strip_prefix('F').map(str::parse::<u8>) {
        return (1..=7).contains(&n).then_some(n);
    }
    Some(match name {
        "Space" => b' ',
        "Enter" | "NumpadEnter" => 13,
        "Backspace" => 8,
        "Tab" => 9,
        "Escape" => 27,
        "ArrowUp" => 0x11,
        "ArrowDown" => 0x12,
        "ArrowLeft" => 0x13,
        "ArrowRight" => 0x14,
        "ShiftLeft" | "ShiftRight" => 0x15,
        "ControlLeft" | "ControlRight" | "MetaLeft" | "MetaRight" => 0x16,
        "AltLeft" | "AltRight" => 0x17,
        "PageUp" => 0x1C,
        "PageDown" => 0x1D,
        "Home" => 0x1E,
        "End" => 0x1F,
        "Delete" => 0x7F,
        "Minus" => b'-',
        "Equal" => b'=',
        "BracketLeft" => b'[',
        "BracketRight" => b']',
        "Backslash" => b'\\',
        "Semicolon" => b';',
        "Quote" => b'\'',
        "Comma" => b',',
        "Period" => b'.',
        "Slash" => b'/',
        "Backquote" => b'`',
        _ => return None,
    })
}

impl Board for Mini {
    fn run(&mut self, until: u64, steps: u64) -> Result<Status, String> {
        let stop = self.cpu.instructions.saturating_add(steps);
        while self.cpu.ticks < until {
            if self.cpu.halted {
                return Ok(Status::Halted);
            }
            if self.cpu.instructions >= stop {
                return Ok(Status::Ran);
            }
            self.cpu.step(&mut self.sys)?;
        }
        Ok(Status::Ran)
    }

    /// The master clock's ticks: the board's cycles are its clock's.
    #[allow(clippy::misnamed_getters)]
    fn cycles(&self) -> u64 {
        self.cpu.ticks
    }

    fn instructions(&self) -> u64 {
        self.cpu.instructions
    }

    fn clock_hz(&self) -> f64 {
        CLOCK_HZ
    }

    fn send(&mut self, bytes: &[u8]) {
        self.sys.page.inp.extend_from_slice(bytes);
    }

    fn take_output(&mut self) -> Vec<u8> {
        std::mem::take(&mut self.sys.page.out)
    }

    fn screen_size(&self) -> Option<(u32, u32)> {
        let (w, h) = self.sys.video.last_size;
        Some((w as u32, h as u32))
    }

    fn screen(&mut self, out: &mut Vec<u32>, always: bool) -> bool {
        let v = &self.sys.video;
        if v.frames == 0 || (!always && v.frames == self.shown) {
            return false;
        }
        self.shown = v.frames;
        out.clear();
        out.extend(v.last.iter().map(|&c| {
            let c = u32::from(c);
            let (r, g, b) = ((c >> 11) & 31, (c >> 5) & 63, c & 31);
            ((r * 255 / 31) << 16) | ((g * 255 / 63) << 8) | (b * 255 / 31)
        }));
        true
    }

    fn key(&mut self, name: &str, down: bool) -> bool {
        match key_code(name) {
            Some(k) => {
                self.sys.uarts[1]
                    .inp
                    .extend_from_slice(&[if down { 0x80 } else { 0x81 }, k]);
                true
            }
            None => false,
        }
    }

    fn has_mouse(&self) -> bool {
        true
    }

    fn mouse(&mut self, dx: i32, dy: i32, buttons: u8) {
        let (w, h) = self.sys.video.last_size;
        self.mouse.0 = (self.mouse.0 + dx).clamp(0, w as i32 - 1);
        self.mouse.1 = (self.mouse.1 + dy).clamp(0, h as i32 - 1);
        self.buttons = buttons;
        self.send_mouse();
    }

    fn registers(&self) -> Vec<(String, u32)> {
        let mut out: Vec<(String, u32)> =
            (0..16).map(|i| (format!("r{i}"), self.cpu.rf[i])).collect();
        out.push(("pc".into(), self.cpu.pc));
        out.push(("flags".into(), self.cpu.flags_word()));
        out
    }

    fn peek(&self, addr: u32, len: u32) -> Vec<u8> {
        let mem = &self.sys.ram;
        let a = (addr as usize).min(mem.len());
        let b = a.saturating_add(len as usize).min(mem.len());
        mem[a..b].to_vec()
    }
}
