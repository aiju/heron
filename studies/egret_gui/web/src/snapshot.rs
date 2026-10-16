//! A machine's whole state as bytes (studies/egret_gui/snapshot.py
//! writes them): which draft, the registers, the timer, the display, RAM,
//! VRAM and the console input still to be read. Little-endian:
//!
//! ```text
//!    0  b"HERONSNP", u32 version (2)
//!   12  u32 pc, hi (0 on draft 2), flags word, r0-r15
//!   88  u64 cycles, timer period, next tick
//!  112  u32 timer flag, depth, pointer, RAM bytes, VRAM bytes, input bytes
//!  136  u32 palette[256]
//! 1160  u32 the draft: 1 (1b) or 2
//! 1164  RAM, VRAM, input
//! ```

use crate::Heron;

const MAGIC: &[u8] = b"HERONSNP";
const HEADER: usize = 1164;

struct Reader<'a> {
    b: &'a [u8],
    at: usize,
}

impl Reader<'_> {
    fn u32(&mut self) -> u32 {
        let v = u32::from_le_bytes(self.b[self.at..self.at + 4].try_into().unwrap());
        self.at += 4;
        v
    }

    fn u64(&mut self) -> u64 {
        let v = u64::from_le_bytes(self.b[self.at..self.at + 8].try_into().unwrap());
        self.at += 8;
        v
    }
}

pub fn load(b: &[u8]) -> Result<Heron, String> {
    if b.len() < HEADER || &b[..8] != MAGIC {
        return Err("not a snapshot".into());
    }
    let mut r = Reader { b, at: 8 };
    if r.u32() != 2 {
        return Err("a snapshot of another version".into());
    }
    let pc = r.u32();
    let hi = r.u32();
    let flags = r.u32();
    let mut regs = [0u32; 16];
    for x in regs.iter_mut() {
        *x = r.u32();
    }
    let cycles = r.u64();
    let period = r.u64();
    let next = r.u64();
    let flag = r.u32();
    let depth = r.u32();
    let pointer = r.u32();
    let (ram, vram, inp) = (r.u32() as usize, r.u32() as usize, r.u32() as usize);
    let mut palette = [0u32; 256];
    for p in palette.iter_mut() {
        *p = r.u32();
    }
    let draft = r.u32();
    if b.len() != HEADER + ram + vram + inp {
        return Err("a snapshot of the wrong size".into());
    }
    let ram_bytes = &b[HEADER..HEADER + ram];
    let vram_bytes = &b[HEADER + ram..HEADER + ram + vram];
    let inp_bytes = &b[HEADER + ram + vram..];
    let mut h = match draft {
        1 => {
            use v1_isa::timing::{Config, REFERENCE};
            let config = Config::named(REFERENCE).expect("the reference configuration");
            let mut m = v1_isa::Machine::new(v1_isa::Isa::V1b, ram_bytes, inp_bytes, config);
            m.hi = hi;
            Heron::V1(m)
        }
        2 => {
            use v2_isa::timing::{Config, REFERENCE};
            let config = Config::named(REFERENCE).expect("the reference configuration");
            Heron::V2(v2_isa::Machine::new(ram_bytes, inp_bytes, config))
        }
        _ => {
            return Err(format!(
                "a snapshot of draft {draft}, which this doesn't know"
            ));
        }
    };
    on!(&mut h, m => {
        m.pc = pc;
        m.set_flags_word(flags);
        m.r = regs;
        m.cycles = cycles;
        m.dev.timer_period = period;
        m.dev.timer_next = next;
        m.dev.timer_flag = flag;
    });
    let d = h.display();
    d.depth = depth & 3;
    d.pointer = pointer;
    d.palette = palette;
    let n = vram_bytes.len().min(d.vram.len());
    d.vram[..n].copy_from_slice(&vram_bytes[..n]);
    d.dirty = true;
    Ok(h)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_garbage() {
        assert!(load(b"nonsense").is_err());
    }
}
