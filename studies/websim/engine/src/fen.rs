//! The `fen` board: draft 2 in system mode on the Fen study's board
//! (studies/fen/board), which says what's where. The terminal is the I/O
//! card's UART, the screen the video card, and the keyboard and the mouse
//! its PS/2 ports. What the software writes to the board's debug port is
//! the log.
//!
//! Parameters, each the board's default unless given:
//! - `ram_size`, in bytes;
//! - `clock_hz`;
//! - `boot_flags`, for the software to read (Fen's bit 0: a shell on the
//!   serial console rather than the desktop);
//! - `epoch`: the clock's seconds since 1970 at power-on;
//! - `timing`: the timing configuration the cycles follow.
//!
//! Loads: `ram` at a physical address; `cf`, the CompactFlash card's
//! image (at 0).

use fen_board::{Computer, Config, ps2, video};
use v2_isa::RunStatus;

use crate::{Board, Load, Params, Status};

pub struct Fen {
    c: Computer,
}

impl Fen {
    pub fn new(p: &mut Params, loads: &[Load]) -> Result<Fen, String> {
        let mut cfg = Config::default();
        if let Some(v) = p.u32("ram_size")? {
            cfg.ram_size = v;
        }
        if let Some(v) = p.number("clock_hz")? {
            cfg.clock_hz = v;
        }
        if let Some(v) = p.u32("boot_flags")? {
            cfg.boot_flags = v;
        }
        if let Some(v) = p.number("epoch")? {
            cfg.epoch = v as u64;
        }
        if let Some(t) = p.text("timing") {
            cfg.timing = v2_isa::timing::Config::named(t).ok_or(format!("no timing {t:?}"))?;
        }
        let mut cf = Vec::new();
        for l in loads.iter().filter(|l| l.target == "cf") {
            let end = l.at as usize + l.bytes.len();
            if cf.len() < end {
                cf.resize(end, 0);
            }
            cf[l.at as usize..end].copy_from_slice(&l.bytes);
        }
        let ram_size = cfg.ram_size as usize;
        let mut c = Computer::new(cfg, cf);
        for l in loads {
            match l.target.as_str() {
                "ram" if l.at as usize + l.bytes.len() <= ram_size => c.load(l.at, &l.bytes),
                "ram" => {
                    return Err(format!(
                        "{} bytes at {:#X} don't fit in RAM",
                        l.bytes.len(),
                        l.at
                    ));
                }
                "cf" => {}
                t => return Err(format!("the fen board has nothing to load called {t:?}")),
            }
        }
        Ok(Fen { c })
    }
}

impl Board for Fen {
    fn run(&mut self, until: u64, steps: u64) -> Result<Status, String> {
        Ok(match self.c.run(until, steps)? {
            RunStatus::Halted => Status::Halted,
            RunStatus::Idle => Status::Idle,
            RunStatus::Limit | RunStatus::Steps => Status::Ran,
        })
    }

    fn cycles(&self) -> u64 {
        self.c.m.cycles
    }

    fn instructions(&self) -> u64 {
        self.c.m.instructions
    }

    fn clock_hz(&self) -> f64 {
        self.c.board_ref().cfg.clock_hz
    }

    fn idle_cycles(&self) -> u64 {
        self.c.m.idle_cycles
    }

    fn send(&mut self, bytes: &[u8]) {
        self.c.uart_send(bytes)
    }

    fn take_output(&mut self) -> Vec<u8> {
        self.c.uart_take()
    }

    fn take_log(&mut self) -> Vec<u8> {
        self.c.debug_take()
    }

    fn screen_size(&self) -> Option<(u32, u32)> {
        Some((video::WIDTH as u32, video::HEIGHT as u32))
    }

    fn screen(&mut self, out: &mut Vec<u32>, always: bool) -> bool {
        self.c.screen(out, always)
    }

    fn key(&mut self, name: &str, down: bool) -> bool {
        match ps2::scancode(name) {
            Some(code) => {
                self.c.key(code, down);
                true
            }
            None => false,
        }
    }

    fn has_mouse(&self) -> bool {
        true
    }

    fn mouse(&mut self, dx: i32, dy: i32, buttons: u8) {
        // PS/2 counts y up
        self.c.mouse(dx, -dy, buttons)
    }

    fn registers(&self) -> Vec<(String, u32)> {
        let m = &self.c.m;
        let s = m.sys();
        let mut out: Vec<(String, u32)> = (0..16).map(|i| (format!("r{i}"), m.r[i])).collect();
        out.push(("pc".into(), m.pc));
        let flags = (m.n as u32) << 3 | (m.z as u32) << 2 | (m.c as u32) << 1 | m.v as u32;
        out.push(("nzcv".into(), flags));
        out.push(("i".into(), m.i as u32));
        out.push(("s".into(), s.supervisor as u32));
        out.push(("ipl".into(), s.ipl as u32));
        out.push(("ctx".into(), s.ctx));
        out.push(("bank".into(), s.cur_bank as u32));
        out.push(("far".into(), s.far));
        out.push(("fsr".into(), s.fsr));
        out
    }

    fn peek(&self, addr: u32, len: u32) -> Vec<u8> {
        let mem = &self.c.m.mem;
        let a = (addr as usize).min(mem.len());
        let b = a.saturating_add(len as usize).min(mem.len());
        mem[a..b].to_vec()
    }
}
