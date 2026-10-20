//! The `plain` board: draft 1 (1a, 1b, and 1b's variants) or draft 2 as
//! the programs run on them, without a supervisor: 1 MB of RAM from 0,
//! the reset vector at 0, and the I/O page at 0xFFFFFF00 with the console,
//! the timer and the cycle counter (RFC 0004, 26).
//!
//! The terminal is the console, its line open: a read with nothing typed
//! waits for the terminal (`Devices::open` in each machine), and ^D at the
//! terminal ends the input, after which reads read -1. Nothing typed is
//! echoed; the frontend does that.
//!
//! Parameters:
//! - `isa`: `v1a`, `v1b`, `v1bx` (the Lisp study's tagged mode), `v1bs`
//!   (the kernel study's system extensions) or `v2`;
//! - `clock_hz`: the clock it runs at, 3 MHz unless given;
//! - `timing`: the timing configuration its cycles follow, the
//!   simulators' reference (D16-overlap) unless given.
//!
//! Loads: `ram` at an address; `console`, input waiting on the console at
//! power-on, before anything typed.

use crate::{Board, Load, Params, Status};

enum Machine {
    V1(Box<v1_isa::Machine>),
    V2(Box<v2_isa::Machine>),
}

/// `on!(m, x => e)`: `e` with `x` the machine `m` holds, whichever draft.
macro_rules! on {
    ($m:expr, $x:ident => $e:expr) => {
        match $m {
            Machine::V1($x) => $e,
            Machine::V2($x) => $e,
        }
    };
}

pub struct Plain {
    m: Machine,
    clock_hz: f64,
}

impl Plain {
    pub fn new(p: &mut Params, loads: &[Load]) -> Result<Plain, String> {
        let isa = p.text("isa").unwrap_or("v2");
        let clock_hz = p.number("clock_hz")?.unwrap_or(3e6);
        let timing = p.text("timing");
        let mut ram = Vec::new();
        let mut console = Vec::new();
        for l in loads {
            match l.target.as_str() {
                "ram" => {
                    let end = l.at as usize + l.bytes.len();
                    if end > v2_isa::machine::RAM_SIZE as usize {
                        return Err(format!(
                            "{} bytes at {:#X} don't fit in RAM",
                            l.bytes.len(),
                            l.at
                        ));
                    }
                    if ram.len() < end {
                        ram.resize(end, 0);
                    }
                    ram[l.at as usize..end].copy_from_slice(&l.bytes);
                }
                "console" => console.extend_from_slice(&l.bytes),
                t => return Err(format!("the plain board has nothing to load called {t:?}")),
            }
        }
        let m = if isa == "v2" {
            let t = timing.unwrap_or(v2_isa::timing::REFERENCE);
            let t = v2_isa::timing::Config::named(t).ok_or(format!("no timing {t:?}"))?;
            Machine::V2(Box::new(v2_isa::Machine::new(&ram, &console, t)))
        } else {
            let i = v1_isa::Isa::named(isa).ok_or(format!("no ISA {isa:?}"))?;
            let t = timing.unwrap_or(v1_isa::timing::REFERENCE);
            let t = v1_isa::timing::Config::named(t).ok_or(format!("no timing {t:?}"))?;
            Machine::V1(Box::new(v1_isa::Machine::new(i, &ram, &console, t)))
        };
        let mut b = Plain { m, clock_hz };
        on!(&mut b.m, m => m.dev.open = true);
        Ok(b)
    }
}

impl Board for Plain {
    fn run(&mut self, until: u64, steps: u64) -> Result<Status, String> {
        on!(&mut self.m, m => {
            for _ in 0..steps {
                if m.halted {
                    return Ok(Status::Halted);
                }
                if m.dev.waiting {
                    return Ok(Status::Waiting);
                }
                if m.cycles >= until {
                    break;
                }
                m.step()?;
            }
            Ok(if m.dev.waiting { Status::Waiting } else { Status::Ran })
        })
    }

    fn cycles(&self) -> u64 {
        on!(&self.m, m => m.cycles)
    }

    fn instructions(&self) -> u64 {
        on!(&self.m, m => m.instructions)
    }

    fn clock_hz(&self) -> f64 {
        self.clock_hz
    }

    fn send(&mut self, bytes: &[u8]) {
        on!(&mut self.m, m => m.dev.send(bytes))
    }

    fn close(&mut self) {
        on!(&mut self.m, m => m.dev.close())
    }

    fn take_output(&mut self) -> Vec<u8> {
        on!(&mut self.m, m => std::mem::take(&mut m.dev.out))
    }

    fn registers(&self) -> Vec<(String, u32)> {
        on!(&self.m, m => {
            let mut out: Vec<(String, u32)> =
                (0..16).map(|i| (format!("r{i}"), m.r[i])).collect();
            out.push(("pc".into(), m.pc));
            let flags = (m.n as u32) << 3 | (m.z as u32) << 2 | (m.c as u32) << 1 | m.v as u32;
            out.push(("nzcv".into(), flags));
            out.push(("i".into(), m.i as u32));
            out
        })
    }

    fn peek(&self, addr: u32, len: u32) -> Vec<u8> {
        on!(&self.m, m => {
            let a = (addr as usize).min(m.mem.len());
            let b = a.saturating_add(len as usize).min(m.mem.len());
            m.mem[a..b].to_vec()
        })
    }
}
