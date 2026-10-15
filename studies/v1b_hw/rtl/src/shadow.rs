//! The hardware following the instruction-level simulator: before each
//! instruction the simulator executes, the shadow takes its architectural
//! state (registers, HI, flags, PC and memory) and runs the microcode for
//! that one instruction, from its fetch to the next fetch. That is the
//! instruction's cost on the hardware, exactly as rtl.py would count it,
//! for programs whose devices the hardware model doesn't have.
//!
//! The datapath registers the instructions don't name (R, T, MAR, the loop
//! counter, MQ and the latches) carry over from one instruction to the
//! next, as they do in the hardware. Stores go to a scratch overlay and are
//! forgotten (the simulator makes the real ones); I/O reads return 0, so an
//! instruction that reads the I/O page computes something else, but its
//! microcode path doesn't depend on the value.

use std::sync::Arc;

use crate::{Bus, HI, Rom, Rtl};

/// The architectural state before an instruction.
#[derive(Clone, Copy, Debug, Default)]
pub struct Arch {
    pub r: [u32; 16],
    pub hi: u32,
    pub n: u32,
    pub z: u32,
    pub c: u32,
    pub v: u32,
    pub i: u32,
    pub pc: u32,
}

/// What timing an instruction found.
#[derive(Clone, Copy, Debug, Default)]
pub struct Timed {
    /// Cycles from the instruction's fetch to the next one.
    pub cycles: u32,
    /// It read the I/O page (and got 0).
    pub io: bool,
    /// It stopped at HALT, which waits instead of fetching.
    pub halt: bool,
}

/// Memory as the shadow sees it: the simulator's RAM, read only, and the
/// instruction's own stores in an overlay.
struct View<'a> {
    mem: &'a [u8],
    overlay: &'a mut Vec<(u32, u8)>,
    /// Added to fetch addresses: where the code really is (v1bs maps it).
    code_off: u32,
    io: bool,
}

impl View<'_> {
    fn byte(&self, a: u32) -> u32 {
        if let Some(&(_, b)) = self.overlay.iter().rev().find(|(x, _)| *x == a) {
            return b as u32;
        }
        self.mem.get(a as usize).copied().unwrap_or(0) as u32
    }
}

impl Bus for View<'_> {
    fn read(&mut self, addr: u32, io: bool, _fault: bool, fetch: bool, _cycle: u64) -> u32 {
        if io {
            self.io = true;
            return 0;
        }
        let a = if fetch {
            addr.wrapping_add(self.code_off)
        } else {
            addr
        } & 0xFFFFE;
        self.byte(a) | self.byte(a + 1) << 8
    }

    fn write(&mut self, addr: u32, io: bool, d: u32, lanes: u32) {
        if io {
            return;
        }
        let a = addr & 0xFFFFE;
        if lanes & 1 != 0 {
            self.overlay.push((a, d as u8));
        }
        if lanes & 2 != 0 {
            self.overlay.push((a + 1, (d >> 8) as u8));
        }
    }

    fn irq(&self) -> u32 {
        0
    }

    fn tick(&mut self) {}

    fn timer_on(&self) -> bool {
        false
    }
}

/// More cycles than any instruction takes: the microcode ran away.
const RUNAWAY: u32 = 10_000;

pub struct Shadow {
    pub cpu: Rtl,
    overlay: Vec<(u32, u8)>,
}

impl Shadow {
    /// A shadow whose processor has run the reset routine (which writes the
    /// loop constants into the register file).
    pub fn new(rom: Arc<Rom>) -> Result<Shadow, String> {
        let mut cpu = Rtl::new(rom);
        let mut overlay = Vec::new();
        let mut v = View {
            mem: &[],
            overlay: &mut overlay,
            code_off: 0,
            io: false,
        };
        while !cpu.started {
            cpu.step(&mut v)?;
            if cpu.total > 100 {
                return Err("the reset routine doesn't fetch".into());
            }
        }
        Ok(Shadow { cpu, overlay })
    }

    /// Whether the hardware decodes this first parcel as an illegal
    /// instruction (it doesn't implement it).
    pub fn illegal(&self, parcel: u32) -> bool {
        self.cpu.rom.illegal[(parcel & 0xFFFF) as usize]
    }

    /// Time the instruction at `a.pc`, with `mem` the simulator's RAM
    /// before it and `code_off` what to add to a fetch address to find
    /// it there.
    pub fn time(&mut self, a: &Arch, mem: &[u8], code_off: u32) -> Result<Timed, String> {
        let cpu = &mut self.cpu;
        cpu.rf[..16].copy_from_slice(&a.r);
        cpu.rf[HI] = a.hi;
        (cpu.n, cpu.z, cpu.c, cpu.v, cpu.i) = (a.n, a.z, a.c, a.v, a.i);
        self.overlay.clear();
        let mut v = View {
            mem,
            overlay: &mut self.overlay,
            code_off,
            io: false,
        };
        // the state the fetch leaves: the opcode in IR, the PC past it, the
        // decode ROM's routine next
        let ir = v.read(a.pc, false, false, true, 0);
        let dec = cpu.rom.decode[ir as usize];
        cpu.ir = ir;
        cpu.sx = (ir >> 4) & 15;
        cpu.len = dec >> crate::Y_BITS;
        cpu.uaddr = dec & ((1 << crate::Y_BITS) - 1);
        cpu.pc = a.pc.wrapping_add(2);
        cpu.irqs = 0;
        cpu.irqp = 0;
        cpu.halted = false;
        let mut n = 0;
        loop {
            cpu.step(&mut v)?;
            n += 1;
            if cpu.ended {
                break;
            }
            if cpu.at_halt {
                return Ok(Timed {
                    cycles: n,
                    io: v.io,
                    halt: true,
                });
            }
            if n > RUNAWAY {
                return Err(format!("the instruction at {:08X} doesn't end", a.pc));
            }
        }
        Ok(Timed {
            cycles: n,
            io: v.io,
            halt: false,
        })
    }

    /// After `time`: the interrupt entry the hardware makes instead of the
    /// fetch, up to the handler's first fetch. Its cycles; one more after
    /// HALT, whose wait ends with a cycle of its own.
    pub fn irq_entry(
        &mut self,
        mem: &[u8],
        code_off: u32,
        after_halt: bool,
    ) -> Result<u32, String> {
        let cpu = &mut self.cpu;
        if !after_halt {
            // the last cycle didn't fetch: the PC is still the next
            // instruction's address
            if let Some((addr, _)) = cpu.fetched {
                cpu.pc = addr;
            }
        }
        self.overlay.clear();
        let mut v = View {
            mem,
            overlay: &mut self.overlay,
            code_off,
            io: false,
        };
        cpu.uaddr = cpu.rom.irq_entry;
        let mut n = after_halt as u32;
        loop {
            cpu.step(&mut v)?;
            n += 1;
            if cpu.ended {
                return Ok(n);
            }
            if n > RUNAWAY {
                return Err("the interrupt entry doesn't end".into());
            }
        }
    }
}
