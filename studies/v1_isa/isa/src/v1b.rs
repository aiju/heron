//! Draft 1b's decoder: 32-bit, 16-bit parcels, register + addressing mode
//! (isa-v1b.md and studies/v1_isa/v1b.py). The main format is `F D M R`:
//! operation, register, mode, register-or-constant for the mode.

use crate::insn::{self, Insn, MemOp, Res, sext8, sext16};
use crate::key::Ea;
use crate::machine::Machine;

const OP_SYS: u32 = 0x0;
const OP_MOV: u32 = 0x1;
const OP_ST: u32 = 0x2;
const OP_LEA: u32 = 0x3;
const OP_JCC: u32 = 0xA;
const OP_JEA: u32 = 0xB;
const OP_UN: u32 = 0xC;
const OP_SH: u32 = 0xD;
const OP_BCC: u32 = 0xE;
const OP_RR: u32 = 0xF;

/// The ALU function of the EA operations 1 and 4-9 (MOV, ADD, SUB, CMP,
/// AND, OR, XOR).
fn ea_alu(op: u32) -> u8 {
    [0, 8, 0, 0, 0, 2, 9, 4, 5, 6][op as usize]
}

/// The ALU functions of the register-register group: ADC, SBC, BIC, TST,
/// MULU, MULS, DIVU, DIVS, DIVUL.
const RR_ALU: [u8; 9] = [1, 3, 7, 10, 11, 12, 13, 14, 15];

/// An operand: a register, an immediate, or memory.
enum Operand {
    Reg(u8),
    Imm(u32),
    Mem(MemOp),
}

/// Extra parcels a mode needs, from the first parcel alone.
fn mode_size(mode: u32, rn: u32) -> u32 {
    match mode {
        3 | 5 | 9 | 0xC => 1,
        0xF => match rn {
            3 | 7..=9 => 2,
            0..=0xC => 1,
            _ => 0,
        },
        _ => 0,
    }
}

/// Decode a mode, with `ext` the extension parcels and `nxt` the next
/// instruction's address. None for a reserved mode.
fn operand(mode: u32, rn: u32, ext: [u32; 2], nxt: u32) -> Option<Operand> {
    let mem = |base: u32, disp: u32, size: u8, ea: Ea| {
        Some(Operand::Mem(MemOp {
            ea,
            base: base as u8,
            disp,
            index: 0,
            scale: 1,
            size,
        }))
    };
    let size3 = |k: u32| [4, 1, 2][k as usize];
    match mode {
        0 => Some(Operand::Reg(rn as u8)),
        1 => Some(Operand::Imm(rn)),
        0xD => Some(Operand::Imm(!rn)), // -(rn + 1)
        2 => mem(rn, 0, 4, Ea::R),
        3 => mem(rn, sext16(ext[0]), 4, Ea::Rd),
        4 => mem(15, 4 * rn, 4, Ea::Rd),
        5 => {
            let e = ext[0];
            let z = (e >> 8) & 3;
            if z == 3 {
                return None;
            }
            Some(Operand::Mem(MemOp {
                ea: Ea::Idx,
                base: rn as u8,
                disp: sext8(e),
                index: (e >> 12) as u8,
                scale: 1 << ((e >> 10) & 3),
                size: [1, 2, 4][z as usize],
            }))
        }
        6 => mem(rn, 0, 4, Ea::Pi),
        7 => mem(rn, 0, 4, Ea::Pd),
        8 => mem(rn, 0, 1, Ea::R),
        9 => mem(rn, sext16(ext[0]), 1, Ea::Rd),
        0xA => mem(rn, 0, 1, Ea::Pi),
        0xB => mem(rn, 0, 2, Ea::R),
        0xC => mem(rn, sext16(ext[0]), 2, Ea::Rd),
        0xF => match rn {
            0 => Some(Operand::Imm(sext16(ext[0]))),
            1 => Some(Operand::Imm(ext[0])),
            2 => Some(Operand::Imm(ext[0] << 16)),
            3 => Some(Operand::Imm(ext[0] | ext[1] << 16)),
            4..=6 => mem(0, sext16(ext[0]), size3(rn - 4), Ea::Abs),
            7..=9 => mem(0, ext[0] | ext[1] << 16, size3(rn - 7), Ea::Abs),
            0xA..=0xC => mem(0, nxt.wrapping_add(sext16(ext[0])), size3(rn - 0xA), Ea::Pc),
            _ => None,
        },
        _ => None,
    }
}

/// The instruction at pc and its length in parcels.
pub fn decode(m: &Machine, pc: u32) -> Res<(Insn, u32)> {
    let parcel = |a: u32| m.parcel(a);
    let w = parcel(pc)?;
    let op = w >> 12;
    let (d, mode, rn) = ((w >> 8) & 15, (w >> 4) & 15, w & 15);
    match op {
        OP_SYS => return Ok((insn::dec_sys(w), 1)),
        OP_UN => return Ok((insn::dec_unary(w), 1)),
        OP_SH => return Ok((insn::dec_shift(w), 1)),
        OP_BCC => return Ok((insn::dec_bcc(pc, w), 1)),
        OP_JCC => {
            let n = if mode == 1 && rn == 0 {
                3
            } else if mode == 0 && rn == 0 {
                2
            } else {
                1
            };
            return Ok((insn::dec_jcc(pc, w, &mut |a| parcel(a))?, n));
        }
        OP_RR => {
            if rn as usize >= RR_ALU.len() {
                return Ok((Insn::Illegal, 1));
            }
            return Ok((
                Insn::AluRR {
                    f: RR_ALU[rn as usize],
                    d: d as u8,
                    s: mode as u8,
                },
                1,
            ));
        }
        _ => {}
    }
    // the EA instructions (ops 1-9 and B)
    let n = 1 + mode_size(mode, rn);
    let mut ext = [0u32; 2];
    for i in 1..n {
        ext[(i - 1) as usize] = parcel(pc.wrapping_add(2 * i))?;
    }
    let nxt = pc.wrapping_add(2 * n);
    let Some(opnd) = operand(mode, rn, ext, nxt) else {
        return Ok((Insn::Illegal, n));
    };
    let d = d as u8;
    let insn = match (op, opnd) {
        (OP_JEA, _) if d > 1 => Insn::Illegal,
        (OP_JEA, Operand::Reg(r)) => Insn::JeaReg {
            call: d == 1,
            rn: r,
        },
        (OP_JEA, Operand::Imm(v)) => Insn::JeaImm {
            call: d == 1,
            t: v & !1,
        },
        (OP_JEA, Operand::Mem(m)) if m.size == 4 => Insn::JeaMem { call: d == 1, m },
        (OP_JEA, Operand::Mem(_)) => Insn::Illegal,
        (OP_ST, Operand::Mem(m)) => Insn::St { d, m },
        (OP_ST, _) => Insn::Illegal,
        (OP_LEA, Operand::Mem(m)) if m.ea != Ea::Pi && m.ea != Ea::Pd => Insn::LeaMem { d, m },
        (OP_LEA, _) => Insn::Illegal,
        // MOV and the ALU operations
        (_, Operand::Reg(r)) => Insn::AluReg {
            f: ea_alu(op),
            d,
            rn: r,
        },
        (_, Operand::Imm(v)) => Insn::AluImm {
            f: ea_alu(op),
            d,
            v,
        },
        (OP_MOV, Operand::Mem(m)) => Insn::Load { d, m },
        (_, Operand::Mem(m)) => Insn::AluMem {
            f: ea_alu(op),
            d,
            m,
        },
    };
    Ok((insn, n))
}
