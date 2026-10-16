//! Draft 2's decoder (RFC 0028, 2-4). A parcel is an opcode byte,
//! first in memory, and a register byte: `rd` in its high nibble, the
//! mode's register `R` in its low one. The opcode byte is a table, not
//! fields: rows 1-6 and 8-A give an operation its modes as columns, and
//! one-operand instructions take the mode from the register byte. The
//! modes (RFC 0028, 3) are draft 1b's, with mode E,
//! `[r14 + 4R]`, a second slot mode, and two tables without a base register
//! in the special mode.

use crate::insn::{
    ALU_ADC, ALU_ADD, ALU_ADDB4, ALU_AND, ALU_BIC, ALU_CMP, ALU_DIVS, ALU_DIVU, ALU_DIVUL,
    ALU_MERGE, ALU_MOV, ALU_MOVS, ALU_MULS, ALU_MULU, ALU_OR, ALU_SBC, ALU_SUB, ALU_TST, ALU_XOR,
    Insn, MemOp, Res, sext8, sext16, sext24,
};
use crate::key::{Ea, How};
use crate::machine::Machine;

/// An operand: a register, a constant, or memory.
enum Operand {
    Reg(u8),
    Imm(u32),
    Mem(MemOp),
}

/// The ALU functions of rows 4-6 and 8-A.
fn row_alu(row: u32) -> Option<u8> {
    match row {
        4 => Some(ALU_ADD),
        5 => Some(ALU_SUB),
        6 => Some(ALU_CMP),
        8 => Some(ALU_AND),
        9 => Some(ALU_OR),
        0xA => Some(ALU_XOR),
        _ => None,
    }
}

/// Row E's register forms, E0-E9: ADC SBC BIC TST MULU MULS (MULA) DIVU
/// DIVS DIVUL.
const ROW_E: [u8; 10] = [
    ALU_ADC, ALU_SBC, ALU_BIC, ALU_TST, ALU_MULU, ALU_MULS, 0, ALU_DIVU, ALU_DIVS, ALU_DIVUL,
];

/// Row E's special-mode forms, EA-ED: BIC TST MULU MULS.
const ROW_E_SPECIAL: [u8; 4] = [ALU_BIC, ALU_TST, ALU_MULU, ALU_MULS];

/// Extension parcels of mode `mode` with register `rn`, from the first
/// parcel alone.
fn mode_size(mode: u32, rn: u32) -> u32 {
    match mode {
        3 | 5 | 9 | 0xC => 1,
        0xF => match rn {
            3 | 7..=9 | 0xD | 0xE => 2,
            0..=0xC => 1,
            _ => 0,
        },
        _ => 0,
    }
}

/// Decode a mode, with `ext` the extension parcels and `nxt` the next
/// instruction's address. None for one that traps.
fn operand(mode: u32, rn: u32, ext: [u32; 2], nxt: u32) -> Option<Operand> {
    let mem = |ea: Ea, base: u32, disp: u32, size: u8| {
        Some(Operand::Mem(MemOp {
            ea,
            base: base as u8,
            disp,
            index: 0,
            scale: 1,
            size,
        }))
    };
    // an index parcel: register, scale, size, and its low byte
    let indexed = |ea: Ea, base: u32, disp: u32, e: u32| {
        let z = (e >> 8) & 3;
        if z == 3 {
            return None;
        }
        Some(Operand::Mem(MemOp {
            ea,
            base: base as u8,
            disp,
            index: (e >> 12) as u8,
            scale: 1 << ((e >> 10) & 3),
            size: [1, 2, 4][z as usize],
        }))
    };
    let size3 = |k: u32| [4, 1, 2][k as usize];
    match mode {
        0 => Some(Operand::Reg(rn as u8)),
        1 => Some(Operand::Imm(rn)),
        0xD => Some(Operand::Imm(!rn)), // -(rn + 1)
        2 => mem(Ea::R, rn, 0, 4),
        3 => mem(Ea::Rd, rn, sext16(ext[0]), 4),
        4 => mem(Ea::Rd, 15, 4 * rn, 4),
        // the slot modes: words 0-15 at sp, and at r14
        0xE => mem(Ea::Rd, 14, 4 * rn, 4),
        5 => indexed(Ea::Idx, rn, sext8(ext[0]), ext[0]),
        6 => mem(Ea::Pi, rn, 0, 4),
        7 => mem(Ea::Pd, rn, 0, 4),
        8 => mem(Ea::R, rn, 0, 1),
        9 => mem(Ea::Rd, rn, sext16(ext[0]), 1),
        0xA => mem(Ea::Pi, rn, 0, 1),
        0xB => mem(Ea::R, rn, 0, 2),
        0xC => mem(Ea::Rd, rn, sext16(ext[0]), 2),
        0xF => match rn {
            0 => Some(Operand::Imm(sext16(ext[0]))),
            1 => Some(Operand::Imm(ext[0])),
            2 => Some(Operand::Imm(ext[0] << 16)),
            3 => Some(Operand::Imm(ext[0] | ext[1] << 16)),
            4..=6 => mem(Ea::Abs, 0, sext16(ext[0]), size3(rn - 4)),
            7..=9 => mem(Ea::Abs, 0, ext[0] | ext[1] << 16, size3(rn - 7)),
            0xA..=0xC => mem(Ea::Pc, 0, nxt.wrapping_add(sext16(ext[0])), size3(rn - 0xA)),
            // the tables: an index parcel holding the address's bits 23-16,
            // then bits 15-0
            0xD | 0xE => {
                let a = sext24((ext[0] & 0xFF) << 16 | ext[1]);
                if rn == 0xD {
                    indexed(Ea::AbsX, 0, a, ext[0])
                } else {
                    indexed(Ea::PcX, 0, nxt.wrapping_add(a), ext[0])
                }
            }
            _ => None,
        },
        _ => None,
    }
}

/// An instruction with a mode: its operand, and its length in parcels.
fn with_mode(m: &Machine, pc: u32, mode: u32, rn: u32) -> Res<(Option<Operand>, u32)> {
    let n = 1 + mode_size(mode, rn);
    let mut ext = [0u32; 2];
    for i in 1..n {
        ext[(i - 1) as usize] = m.parcel(pc.wrapping_add(2 * i))?;
    }
    Ok((operand(mode, rn, ext, pc.wrapping_add(2 * n)), n))
}

/// The instruction at pc and its length in parcels.
pub fn decode(m: &Machine, pc: u32) -> Res<(Insn, u32)> {
    let w = m.parcel(pc)?;
    let (op, rb) = (w & 0xFF, w >> 8);
    let (hi, lo) = (rb >> 4, rb & 15);
    let (row, col) = (op >> 4, op & 15);
    let (d, s) = (hi as u8, lo as u8);
    let nxt = pc.wrapping_add(2);
    let one = |i: Insn| Ok((i, 1));
    let ext1 = || m.parcel(pc.wrapping_add(2));
    match op {
        0x01 | 0x02 => {
            // LDM rb, ra-rc and STM: ra in the high nibble, rb in the low
            // one, rc in the extension parcel's top nibble
            let e = ext1()?;
            let c = e >> 12;
            if e & 0xFFF != 0 || c < hi {
                return Ok((Insn::Illegal, 2));
            }
            let (b, a, cnt) = (s, d, (c - hi + 1) as u8);
            return Ok((
                if op == 0x01 {
                    Insn::Ldm { b, a, cnt }
                } else {
                    Insn::Stm { b, a, cnt }
                },
                2,
            ));
        }
        0x04..=0x07 => {
            let mode = [3, 4, 5, 0xF][(op - 4) as usize];
            let (o, n) = with_mode(m, pc, mode, lo)?;
            return Ok((
                match o {
                    Some(Operand::Mem(mo)) => Insn::LeaMem { d, m: mo },
                    _ => Insn::Illegal,
                },
                n,
            ));
        }
        0x08 => return one(Insn::AluReg { f: ALU_ADDB4, d, s }),
        0x0E => return one(Insn::Mfsr { a: d, b: s }),
        0x0F => return one(Insn::Mtsr { a: d, b: s }),
        0x09..=0x0D => {
            // the tagged operations: TMOV TTST TADD TSUB TCMP
            let f = [ALU_MOV, ALU_TST, ALU_ADD, ALU_SUB, ALU_CMP][(op - 9) as usize];
            return one(Insn::AluTag { f, d, rn: s });
        }
        0x20 | 0x21 | 0x2D => {
            // CLR, INC and DEC: the mode from the register byte
            let (o, n) = with_mode(m, pc, hi, lo)?;
            let insn = match o {
                Some(Operand::Reg(r)) if op == 0x20 => Insn::AluImm {
                    f: ALU_MOV,
                    d: r,
                    v: 0,
                },
                Some(Operand::Reg(r)) => Insn::Unary {
                    d: r,
                    s: r,
                    f: if op == 0x21 { 2 } else { 3 },
                },
                Some(Operand::Mem(mo)) if op == 0x20 => Insn::Clr { m: mo },
                Some(Operand::Mem(mo)) => Insn::IncMem {
                    m: mo,
                    dec: op == 0x2D,
                },
                _ => Insn::Illegal,
            };
            return Ok((insn, n));
        }
        0x70..=0x7F => {
            // MOV and CMP with #u7: the constant's high bits in the low
            // nibble, its low three in the opcode
            let v = lo << 3 | (op & 7);
            let f = if op < 0x78 { ALU_MOV } else { ALU_CMP };
            return one(Insn::AluImm { f, d, v });
        }
        0xB0..=0xBF => {
            let target = nxt.wrapping_add(sext8(rb).wrapping_mul(2));
            return one(if col == 15 {
                Insn::Bsr { target }
            } else {
                Insn::Bcc {
                    cc: col as u8,
                    target,
                }
            });
        }
        0xC0..=0xCF => {
            // the count's bit 0 in opcode bit 0, bits 4-1 in the low nibble
            let kind = ((op >> 2) & 3) as u8;
            return one(match op & 3 {
                0 | 1 => Insn::ShiftImm {
                    d,
                    op: kind,
                    cnt: (lo << 1 | (op & 1)) as u8,
                },
                2 => Insn::ShiftReg { d, s, op: kind },
                _ => Insn::Illegal,
            });
        }
        0xD0..=0xDE => return one(Insn::Unary { d, s, f: col as u8 }),
        0xDF => {
            return one(if lo == 15 {
                Insn::Illegal
            } else {
                Insn::Set { a: d, cc: s }
            });
        }
        0xE6 => return one(Insn::Mula { d, s }),
        0xE0..=0xE9 => {
            return one(Insn::AluReg {
                f: ROW_E[col as usize],
                d,
                s,
            });
        }
        0xEA..=0xED => {
            let (o, n) = with_mode(m, pc, 0xF, lo)?;
            let f = ROW_E_SPECIAL[(col - 0xA) as usize];
            return Ok((
                match o {
                    Some(Operand::Imm(v)) => Insn::AluImm { f, d, v },
                    Some(Operand::Mem(mo)) => Insn::AluMem { f, d, m: mo },
                    _ => Insn::Illegal,
                },
                n,
            ));
        }
        0xEE => return one(Insn::AluReg { f: ALU_MERGE, d, s }),
        0xF0 | 0xF1 => {
            // JMP and CALL: the mode from the register byte
            let call = op == 0xF1;
            let (o, n) = with_mode(m, pc, hi, lo)?;
            let insn = match o {
                Some(Operand::Reg(r)) => Insn::JeaReg { call, rn: r },
                Some(Operand::Imm(v)) => Insn::JeaImm { call, t: v & !1 },
                Some(Operand::Mem(mo)) if mo.size == 4 => Insn::JeaMem { call, m: mo },
                _ => Insn::Illegal,
            };
            return Ok((insn, n));
        }
        0xF2 => {
            // Jcc, JMP (14) and CALL (15): the condition in the high nibble,
            // the low one spare; PC-relative in parcels
            if lo != 0 {
                return Ok((Insn::Illegal, 2));
            }
            let nxt = pc.wrapping_add(4);
            let target = nxt.wrapping_add(sext16(ext1()?).wrapping_mul(2));
            return Ok((
                Insn::Jcc {
                    cc: d,
                    target,
                    how: How::Rel,
                },
                2,
            ));
        }
        0xF3 => {
            if lo != 0 {
                return Ok((Insn::Illegal, 3));
            }
            let target = (ext1()? | m.parcel(pc.wrapping_add(4))? << 16) & !1;
            return Ok((
                Insn::Jcc {
                    cc: d,
                    target,
                    how: How::Abs,
                },
                3,
            ));
        }
        0xF4 | 0xF5 => {
            if hi > lo || lo > 14 {
                return one(Insn::Illegal);
            }
            let (a, cnt) = (d, s - d + 1);
            return one(if op == 0xF4 {
                Insn::Save { a, cnt }
            } else {
                Insn::Restore { a, cnt }
            });
        }
        0xF6 => {
            // DBNZ r, back: 1-16 parcels back from the next instruction
            let target = nxt.wrapping_sub(2 * (lo + 1));
            return one(Insn::Dbnz { r: d, target });
        }
        0xFC => return one(Insn::Swi),
        0xFD => {
            return match rb {
                0x00 => {
                    // MULFX rd, rs, #n: rd and rs in the high byte, n in
                    // bits 4-0
                    let e = ext1()?;
                    if e & 0xE0 != 0 {
                        return Ok((Insn::Illegal, 2));
                    }
                    Ok((
                        Insn::Mulfx {
                            d: (e >> 12) as u8,
                            s: ((e >> 8) & 15) as u8,
                            n: (e & 31) as u8,
                        },
                        2,
                    ))
                }
                _ => one(Insn::Illegal),
            };
        }
        0xFE => {
            return match rb {
                0x00 => one(Insn::SetI { val: 1 }),
                0x01 => one(Insn::SetI { val: 0 }),
                0x02 => one(Insn::Rti),
                0x03 => one(Insn::Halt),
                _ => one(Insn::Illegal),
            };
        }
        _ => {}
    }
    // rows 1-6 and 8-A: an operation with the mode as the column. MOVS
    // has no quick constants: its cells 31 and 3D are MFUR and MTUR, the
    // supervisor's, which trap without a supervisor yet
    if !matches!(row, 1..=6 | 8..=0xA) || (row == 3 && matches!(col, 1 | 0xD)) {
        return one(Insn::Illegal);
    }
    let (o, n) = with_mode(m, pc, col, lo)?;
    let Some(o) = o else {
        return Ok((Insn::Illegal, n));
    };
    let insn = match (row, o) {
        (1 | 3, o) => {
            let nz = row == 3;
            let f = if nz { ALU_MOVS } else { ALU_MOV };
            match o {
                Operand::Reg(r) => Insn::AluReg { f, d, s: r },
                Operand::Imm(v) => Insn::AluImm { f, d, v },
                Operand::Mem(m) => Insn::Load { d, m, nz },
            }
        }
        (2, Operand::Mem(m)) => Insn::St { d, m },
        (2, _) => Insn::Illegal,
        (_, o) => {
            let f = row_alu(row).unwrap();
            match o {
                Operand::Reg(r) => Insn::AluReg { f, d, s: r },
                Operand::Imm(v) => Insn::AluImm { f, d, v },
                Operand::Mem(m) => Insn::AluMem { f, d, m },
            }
        }
    };
    Ok((insn, n))
}
