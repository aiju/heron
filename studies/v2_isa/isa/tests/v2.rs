//! Draft 2: its encoder through the assembler core, the machine running
//! what it assembles, and the timing of its new kinds of work. The
//! encodings in `rfc_examples` are RFC 0028's own.

use toolchain::asm::{Assembler, Kind as StmtKind};
use toolchain::obj;
use v2_isa::Machine;
use v2_isa::asm::encoder;
use v2_isa::key::{Ea, Key, Kind};
use v2_isa::timing::{CONFIGS, Config};

/// The parcels of `line`, assembled at 0x100 with `here` at its address,
/// `far` at 0x30000 and `table` at 0x234560.
fn encode(line: &str) -> Vec<u16> {
    let src = format!(
        "        .org 0x100\nhere:   {line}\n        .org 0x30000\nfar:    HALT\ntable = 0x234560\n"
    );
    let mut a = Assembler::new(encoder("v2").unwrap(), false);
    a.load("t.s", Some(&src)).unwrap();
    a.assemble().unwrap_or_else(|e| panic!("{line}: {e}"));
    a.stmts()
        .iter()
        .find(|s| s.kind == StmtKind::Insn)
        .unwrap()
        .words
        .clone()
}

/// A parcel from its bytes in memory: the opcode, then the register byte.
fn b(op: u16, rb: u16) -> u16 {
    op | rb << 8
}

fn error(src: &str) -> String {
    let mut a = Assembler::new(encoder("v2").unwrap(), false);
    a.load("t.s", Some(src)).unwrap();
    a.assemble().err().unwrap().to_string()
}

#[test]
fn rfc_examples() {
    let cases: &[(&str, &[u16])] = &[
        ("ADD r1, [r2]+", &[b(0x46, 0x12)]),
        ("MOV r3, [r4 + 8]", &[b(0x13, 0x34), 0x0008]),
        ("MOV [sp + 12], r5", &[b(0x24, 0x53)]),
        ("BNE here - 4", &[b(0xB1, 0xFD)]),
        ("MOV r5, #'a'", &[b(0x71, 0x5C)]),
        ("CLR [r6]+", &[b(0x20, 0x66)]),
        ("MOV r1, [r14 + 8]", &[b(0x1E, 0x12)]),
        ("RET", &[b(0xF0, 0x07)]),
        ("HALT", &[b(0xFE, 0x03)]),
    ];
    for (line, words) in cases {
        assert_eq!(encode(line), *words, "{line}");
    }
}

#[test]
fn encodings() {
    let cases: &[(&str, &[u16])] = &[
        // constants: quick, 7 bits, then the special mode
        ("MOV r1, #5", &[b(0x11, 0x15)]),
        ("MOV r1, #-3", &[b(0x1D, 0x12)]),
        ("MOV r1, #127", &[b(0x77, 0x1F)]),
        ("MOV r1, #128", &[b(0x1F, 0x10), 0x0080]),
        ("MOV r1, #0xFFFF", &[b(0x1F, 0x11), 0xFFFF]),
        ("MOV r1, #0x12340000", &[b(0x1F, 0x12), 0x1234]),
        ("MOV r1, #0x12345678", &[b(0x1F, 0x13), 0x5678, 0x1234]),
        ("CMP r2, #16", &[b(0x78, 0x22)]),
        ("CMP r2, #15", &[b(0x61, 0x2F)]),
        ("ADD r2, #100", &[b(0x4F, 0x20), 0x0064]),
        ("MOVS r1, #5", &[b(0x3F, 0x10), 0x0005]),
        ("TST r1, #0x80", &[b(0xEB, 0x10), 0x0080]),
        ("MULU r1, #10", &[b(0xEC, 0x10), 0x000A]),
        // moves, stores and the modes
        ("MOV r1, r0", &[b(0x10, 0x10)]),
        ("MOVS r1, r2", &[b(0x30, 0x12)]),
        ("MOVS r1, byte [r2]+", &[b(0x3A, 0x12)]),
        ("MOV r1, [sp]+", &[b(0x16, 0x1F)]),
        ("MOV -[sp], r1", &[b(0x27, 0x1F)]),
        ("MOV half [r2 + 6], r1", &[b(0x2C, 0x12), 0x0006]),
        ("MOV r1, [r2 + r3*4 + 1]", &[b(0x15, 0x12), 0x3A01]),
        ("MOV r1, [0x1234]", &[b(0x1F, 0x14), 0x1234]),
        ("MOV r1, [0x123456]", &[b(0x1F, 0x17), 0x3456, 0x0012]),
        ("MOV r1, [pc + here]", &[b(0x1F, 0x1A), 0xFFFC]),
        ("MOV [0x40], #0", &[b(0x20, 0xF4), 0x0040]),
        // tables without a base register
        ("MOV r1, [table + r2*4]", &[b(0x1F, 0x1D), 0x2A23, 0x4560]),
        (
            "MOV r1, byte [table + r2]",
            &[b(0x1F, 0x1D), 0x2023, 0x4560],
        ),
        ("MOV r1, [r2 + 0x123456]", &[b(0x1F, 0x1D), 0x2212, 0x3456]),
        ("MOV r1, [r2 + 0x1234]", &[b(0x13, 0x12), 0x1234]),
        ("JMP [pc + here + r2*4]", &[b(0xF0, 0xFE), 0x2AFF, 0xFFFA]),
        // one operand, the mode in the register byte
        ("CLR r5", &[b(0x20, 0x05)]),
        ("CLR byte [r1 + 2]", &[b(0x20, 0x91), 0x0002]),
        ("INC [0x40]", &[b(0x21, 0xF4), 0x0040]),
        ("DEC half [r3]", &[b(0x2D, 0xB3)]),
        ("INC r5", &[b(0xD2, 0x55)]),
        ("JMP r3", &[b(0xF0, 0x03)]),
        ("CALL [r1]", &[b(0xF1, 0x21)]),
        ("CALL #0x1234", &[b(0xF1, 0xF0), 0x1234]),
        // LEA
        ("LEA r1, [r2 + 8]", &[b(0x04, 0x12), 0x0008]),
        ("LEA r1, [sp + 8]", &[b(0x05, 0x12)]),
        ("LEA r1, [r2 + r3*2]", &[b(0x06, 0x12), 0x3600]),
        ("LEA r1, here", &[b(0x07, 0x14), 0x0100]),
        ("LEA r1, [pc + here]", &[b(0x07, 0x1A), 0xFFFC]),
        ("LEA r1, [table + r2*4]", &[b(0x07, 0x1D), 0x2A23, 0x4560]),
        ("LEA r1, [r2]", &[b(0x10, 0x12)]),
        // registers only
        ("ADC r1, r2", &[b(0xE0, 0x12)]),
        ("DIVUL r1, r2", &[b(0xE9, 0x12)]),
        ("ADD.B4 r1, r2", &[b(0x08, 0x12)]),
        ("MERGE r1, r2", &[b(0xEE, 0x12)]),
        ("MULA r1, r2", &[b(0xE6, 0x12)]),
        ("TMOV r1, r2", &[b(0x09, 0x12)]),
        ("TADD r1, r2", &[b(0x0B, 0x12)]),
        ("TTST r1, r1", &[b(0x0A, 0x11)]),
        ("TCMP r1, r2", &[b(0x0D, 0x12)]),
        // mode E, the slot mode at r14, for every operation that has modes
        ("ADD r3, [r14 + 60]", &[b(0x4E, 0x3F)]),
        ("MOV [r14 + 4], r5", &[b(0x2E, 0x51)]),
        ("AND r1, [r14 + 4]", &[b(0x8E, 0x11)]),
        ("MOVS r2, [r14 + 12]", &[b(0x3E, 0x23)]),
        ("CLR [r14 + 8]", &[b(0x20, 0xE2)]),
        ("JMP [r14 + 20]", &[b(0xF0, 0xE5)]),
        ("MOV r1, [r14]", &[b(0x12, 0x1E)]),
        ("MOV r1, [r14 + 64]", &[b(0x13, 0x1E), 0x0040]),
        ("MOV r1, byte [r14 + 4]", &[b(0x19, 0x1E), 0x0004]),
        ("LEA r1, [r14 + 8]", &[b(0x04, 0x1E), 0x0008]),
        ("MULFX r1, r2, #16", &[b(0xFD, 0x00), 0x1210]),
        // row D, shifts
        ("SXH r1, r2", &[b(0xD8, 0x12)]),
        ("REV r1", &[b(0xDE, 0x11)]),
        ("SETGE r1", &[b(0xDF, 0x1A)]),
        ("LSL r1, #20", &[b(0xC0, 0x1A)]),
        ("LSR r1, #3", &[b(0xC5, 0x11)]),
        ("ROR r1, r2", &[b(0xCE, 0x12)]),
        // branches and jumps
        ("BSR here", &[b(0xBF, 0xFF)]),
        ("BRA far", &[b(0xF3, 0xE0), 0x0000, 0x0003]),
        ("JMP far", &[b(0xF3, 0xE0), 0x0000, 0x0003]),
        ("CALL here", &[b(0xF2, 0xF0), 0xFFFE]),
        ("JNE here", &[b(0xF2, 0x10), 0xFFFE]),
        ("DBNZ r3, here", &[b(0xF6, 0x30)]),
        ("DBNZ r3, here - 30", &[b(0xF6, 0x3F)]),
        // system and the extension grids
        ("SAVE r8-r11", &[b(0xF4, 0x8B)]),
        ("RESTORE r0-r14", &[b(0xF5, 0x0E)]),
        ("LDM r1, r4-r7", &[b(0x01, 0x41), 0x7000]),
        ("STM sp, r0", &[b(0x02, 0x0F), 0x0000]),
        ("MFSR r1, hi", &[b(0x0E, 0x11)]),
        ("MTSR lo, r2", &[b(0x0F, 0x22)]),
        ("PUSH r1", &[b(0x27, 0x1F)]),
        ("POP r2", &[b(0x16, 0x2F)]),
        ("MFHI r1", &[b(0x0E, 0x11)]),
        ("MFLO r3", &[b(0x0E, 0x32)]),
        ("MTHI r2", &[b(0x0F, 0x12)]),
        ("MTLO r2", &[b(0x0F, 0x22)]),
        ("MFSR r1, flags", &[b(0x0E, 0x10)]),
        ("SWI #42", &[b(0xFC, 0x2A)]),
        ("NOP", &[b(0x10, 0x00)]),
        ("JMP r7", &[b(0xF0, 0x07)]),
        ("JMP [sp]+", &[b(0xF0, 0x6F)]),
        ("EI", &[b(0xFE, 0x00)]),
        ("RTI", &[b(0xFE, 0x02)]),
        ("MFUR r1, sp", &[b(0x31, 0x1F)]),
        ("MTUR r2, r3", &[b(0x3D, 0x23)]),
    ];
    for (line, words) in cases {
        assert_eq!(encode(line), *words, "{line}");
    }
}

#[test]
fn errors() {
    let cases = [
        (
            "ST r1, [r2]",
            "draft 2 has no ST: a store is written MOV [address], rs",
        ),
        ("MVI r1, #3", "draft 2 has no MVI: write MOV rd, #value"),
        ("LI r1, #3", "draft 2 has no LI: write MOV rd, #value"),
        (
            "MOV [r1], #3",
            "there is no store of a constant: only MOV [address], #0 (CLR)",
        ),
        ("MOVS r1, half [r2]+", "there is no half [r]+ mode"),
        ("CLR #3", "CLR needs a register or a memory operand"),
        ("ADC r1, #1", "ADC only works on two registers"),
        (
            "DBNZ r1, here + 2",
            "DBNZ branches back 1-16 parcels from the next instruction",
        ),
        (
            "LEA r1, [r2]+",
            "LEA needs a memory operand without auto-increment",
        ),
        ("JMP byte [r1]", "JMP through memory needs a word"),
        (
            "SAVE r3-r1",
            "register range must be within r0-r14, low to high",
        ),
        (
            "MOV r1, [r2 + r3*4 + 200]",
            "the indexed mode's displacement must fit in 8 bits",
        ),
        ("frob r1", "unknown instruction frob"),
    ];
    for (line, msg) in cases {
        let e = error(&format!("        .org 0x100\nhere:   {line}\n"));
        assert_eq!(e, format!("t.s:2: {msg}"), "{line}");
    }
}

#[test]
fn relocations() {
    // a call to another file's function, a near load, a table indexed
    // without a base register, and the same PC-relative
    let src = "f:      CALL ext\n\
               \x20       MOV r1, [near]\n\
               \x20       MOV r2, [tab + r3*4]\n\
               \x20       MOV r2, [pc + tab + r3*4]\n\
               \x20       .data\n\
               tab:    .word f\n";
    let mut a = Assembler::new(encoder("v2").unwrap(), true);
    a.load("t.s", Some(src)).unwrap();
    let o = a.assemble_object("t.o").unwrap();
    let kinds: Vec<(u32, u32)> = o.relocs.iter().map(|r| (r.kind, r.offset)).collect();
    assert_eq!(
        kinds,
        [
            (obj::PC16H, 2),
            (obj::ABS16S, 6),
            (obj::ABS24H, 10),
            (obj::ABS24L, 12),
            (obj::PC24H, 16),
            (obj::PC24L, 18),
            (obj::ABS32, 0),
        ]
    );
    // the index parcels keep the register, the scale and the size
    assert_eq!(&o.sections[0].data[10..14], &[0x00, 0x3A, 0x00, 0x00]);
    assert_eq!(
        obj::reloc_value(obj::ABS24H, 0x12_3456, 0, 0),
        Ok(vec![0x12])
    );
    assert_eq!(
        obj::reloc_value(obj::ABS24L, 0x12_3456, 0, 0),
        Ok(vec![0x56, 0x34])
    );
    assert!(obj::reloc_value(obj::ABS24H, 0x80_0000, 0, 0).is_err());
    assert_eq!(
        obj::reloc_value(obj::PC24H, 0, 0, 0x10_0000),
        Ok(vec![0xF0])
    );
}

/// Assemble `body` after a reset vector and a trap handler (which halts with
/// r14 = 0x7E), run it, and return the machine.
fn run(body: &str) -> Machine {
    let src = format!(
        "        .org 0\n        JMP  start\n        .org 0x08\n        JMP  trap\n\
         \x20       .org 0x10\n        JMP  trap\n        .org 0x14\n        JMP  trap\n\
         \x20       .org 0x18\n        JMP  trap\n\
         \x20       .org 0x40\ntrap:   MOV  r14, #0x7E\n        HALT\n\
         start:  MOV  sp, #0x8000\n{body}\n        HALT\n"
    );
    let mut a = Assembler::new(encoder("v2").unwrap(), false);
    a.load("t.s", Some(&src)).unwrap();
    let img = a.assemble().unwrap_or_else(|e| panic!("{e}"));
    let mut mem = vec![0u8; 0x10000];
    for (&addr, &v) in &img.mem {
        mem[addr as usize] = v;
    }
    let mut m = Machine::new(&mem, b"", Config::named("D16-overlap").unwrap());
    m.run(100_000).unwrap();
    m
}

fn flags(m: &Machine) -> String {
    [(m.n, 'N'), (m.z, 'Z'), (m.c, 'C'), (m.v, 'V')]
        .iter()
        .map(|&(f, c)| if f != 0 { c } else { '-' })
        .collect()
}

#[test]
fn r0_is_a_general_register() {
    let m = run("        MOV r0, #7\n        ADD r0, r0\n        MOV [0x100], r0");
    assert_eq!(m.r[0], 14);
    assert_eq!(&m.mem[0x100..0x104], &14u32.to_le_bytes());
}

#[test]
fn mov_leaves_the_flags_and_movs_sets_n_and_z() {
    // 0 - 1: N, and a borrow (C clear)
    let m = run("        CMP r1, #1\n        MOV r2, #0\n        MOV r3, [0x200]");
    assert_eq!(flags(&m), "N---");
    let m = run("        CMP r1, #1\n        MOVS r3, [0x200]");
    assert_eq!(flags(&m), "-Z--");
    let m = run("        MOV r1, #-1\n        MOVS r2, r1");
    assert_eq!(flags(&m), "N---");
}

#[test]
fn clr_inc_and_dec() {
    let m = run(
        "        MOV r1, #0x1FF\n        MOV [0x200], r1\n        CLR byte [0x200]\n\
         \x20       MOV r2, #0x2FF\n        MOV half [0x204], r2\n        INC byte [0x204]\n\
         \x20       MOV r9, [0x200]\n        MOV r10, [0x204]\n        MOV r4, #3\n        CLR r4",
    );
    assert_eq!((m.r[9], m.r[10], m.r[4]), (0x100, 0x200, 0));
    // the byte wrapped to zero: Z; INC leaves C and V
    assert_eq!(flags(&m), "-Z--");
    let m = run(
        "        MOV r1, #0x80\n        MOV [0x200], r1\n        DEC [0x200]\n        DEC [0x200]",
    );
    assert_eq!(m.mem[0x200], 0x7E);
}

#[test]
fn dbnz_counts_down_and_keeps_the_flags() {
    let m = run("        MOV r1, #5\n        CLR r2\n        SUB r3, #1\n\
         .loop:  LEA r2, [r2 + 3]\n        DBNZ r1, .loop");
    assert_eq!((m.r[1], m.r[2]), (0, 15));
    // the flags are still SUB's: 0 - 1
    assert_eq!(flags(&m), "N---");
}

#[test]
fn tables_without_a_base_register() {
    let m = run(
        "        MOV r2, #2\n        MOV r1, [table + r2*4]\n        MOV r3, half [pc + table + r2*2]\n\
         \x20       LEA r4, [table + r2*4]\n        JMP [pc + jumps + r2*4]\n\
         \x20       HALT\n\
         t0:     MOV r5, #10\n        HALT\n\
         t2:     MOV r5, #12\n        HALT\n\
         \x20       .align 4\n\
         table:  .word 0x11, 0x22, 0x33, 0x44\n\
         jumps:  .word t0, t0, t2",
    );
    assert_eq!((m.r[1], m.r[3], m.r[5]), (0x33, 0x22, 12));
    assert_eq!(m.r[4] & 3, 0);
}

#[test]
fn calls_leave_the_return_address_in_r7() {
    // a call nests by saving r7 with the registers it keeps; a function can
    // also push its return address and return with JMP [sp]+
    let m = run("        BSR  outer\n        CALL #pushed\n        HALT\n\
         outer:  SAVE r7-r8\n        MOV  r8, #3\n        BSR  inner\n        ADD  r1, r8\n\
         \x20       RESTORE r7-r8\n        RET\n\
         inner:  MOV  r1, #4\n        RET\n\
         pushed: PUSH r7\n        BSR  inner\n        ADD  r1, #10\n        JMP  [sp]+");
    assert_eq!(m.r[1], 14);
    assert_eq!(m.r[15], 0x8000);
    // nothing is pushed: below the stack, memory is untouched
    assert!(m.mem[0x7FE0..0x7FF8].iter().all(|&b| b == 0));
}

#[test]
fn align_pads_with_nop() {
    let mut a = Assembler::new(encoder("v2").unwrap(), false);
    a.load(
        "t.s",
        Some(
            "        .org 0x101
        .align 8
        HALT
",
        ),
    )
    .unwrap();
    let img = a.assemble().unwrap();
    let pad: Vec<u8> = (0x101..0x108).map(|i| img.mem[&i]).collect();
    assert_eq!(pad, [0x00, 0x10, 0x00, 0x10, 0x00, 0x10, 0x00]);
}

#[test]
fn mode_e_is_a_slot_at_r14() {
    let m = run(
        "        MOV r14, #0x300\n        MOV r1, #5\n        MOV [r14 + 8], r1\n\
         \x20       ADD r1, [r14 + 8]\n        INC [r14 + 8]\n        MOVS r2, [r14 + 8]\n\
         \x20       MOV r9, #-1\n        MOV [r14 + 60], r9\n        CLR [r14 + 60]\n\
         \x20       MOV r3, #there\n        MOV [r14 + 20], r3\n        JMP [r14 + 20]\n\
         \x20       HALT\n\
         there:  MOV r4, #9",
    );
    assert_eq!((m.r[1], m.r[2], m.r[4]), (10, 6, 9));
    assert_eq!(&m.mem[0x308..0x30C], &6u32.to_le_bytes());
    assert_eq!(&m.mem[0x33C..0x340], &0u32.to_le_bytes());
}

#[test]
fn ldm_stm_and_save_with_r0() {
    let m = run(
        "        MOV r0, #1\n        MOV r1, #2\n        MOV r2, #3\n        MOV r9, #0x300\n\
         \x20       STM r9, r0-r2\n        CLR r0\n        CLR r1\n        CLR r2\n\
         \x20       LDM r9, r1-r3\n        MOV r0, #9\n        SAVE r0-r1\n        CLR r0\n\
         \x20       RESTORE r0-r1",
    );
    assert_eq!(&m.r[0..4], &[9, 1, 2, 3]);
    assert_eq!(m.r[9], 0x300);
    assert_eq!(m.r[15], 0x8000);
}

#[test]
fn tentative_instructions() {
    let m = run(
        "        MOV r1, #0x01FF80F0\n        MOV r2, #0x01020310\n        ADD.B4 r1, r2\n\
         \x20       MOV r3, #0x80\n        FFS r4, r3\n        POPC r5, r1\n\
         \x20       MOV r6, #0x11223344\n        REV r6\n        CLR r7\n        FFS r7",
    );
    assert_eq!(m.r[1], 0x0201_8300);
    assert_eq!((m.r[4], m.r[5], m.r[6], m.r[7]), (7, 5, 0x4433_2211, 32));
    // MULA accumulates into HI:LO; MERGE takes rs's bits where HI has a 1
    let m = run(
        "        MOV r1, #-3\n        MOV r2, #5\n        MTSR hi, r0\n        MTSR lo, r0\n\
         \x20       MULA r1, r2\n        MULA r2, r2\n        MFSR r3, hi\n        MFSR r4, lo\n\
         \x20       MOV r5, #0xFF00\n        MTSR hi, r5\n        MOV r6, #0x1234\n\
         \x20       MOV r7, #0xABCD\n        MERGE r6, r7",
    );
    assert_eq!((m.r[3], m.r[4]), (0, 10));
    assert_eq!(m.r[6], 0xAB34);
    // MULFX: a fixed-point product, 16.16
    let m = run("        MOV r1, #0x18000\n        MOV r2, #-0x28000\n        MULFX r1, r2, #16");
    assert_eq!(m.r[1] as i32, -0x3C000);
    assert_eq!(flags(&m), "N---");
}

#[test]
fn tagged_operations_check_bit_0() {
    let m = run("        MOV r1, #4\n        MOV r2, #6\n        TADD r1, r2\n        TMOV r3, r1");
    assert_eq!((m.r[1], m.r[3], m.r[14]), (10, 10, 0));
    let m = run("        MOV r1, #4\n        MOV r2, #7\n        TCMP r1, r2");
    assert_eq!(m.r[14], 0x7E);
    assert_eq!(m.traps.len(), 1);
}

#[test]
fn illegal_cells_trap() {
    // MFUR is the supervisor's, and there is no supervisor yet
    for cell in [
        "0x00", "0x03", "0x31", "0xC3", "0xF7", "0xFF", "0x10FE", "0xFDFD",
    ] {
        let m = run(&format!("        .half {cell}"));
        assert_eq!(m.r[14], 0x7E, "{cell}");
        assert_eq!(m.traps[0].1, "illegal instruction", "{cell}");
    }
}

#[test]
fn timing_of_the_new_kinds() {
    let cycles = |n, kind| {
        CONFIGS
            .iter()
            .map(|&(_, c)| c.cycles(Key { n, p2: 0, kind }))
            .collect::<Vec<u32>>()
    };
    // DBNZ takes fewer cycles than DEC and a taken BNE in every
    // configuration: on D32-overlap 3 against 4, RFC 0028's estimate
    let dec = cycles(1, Kind::Alu { wb: 1 });
    let bne = cycles(1, Kind::Br { taken: 1, x: 0 });
    let dbnz = cycles(1, Kind::Dbnz { taken: 1, x: 0 });
    for i in 0..CONFIGS.len() {
        assert!(dbnz[i] < dec[i] + bne[i], "{}", CONFIGS[i].0);
    }
    assert_eq!((dbnz[4], dec[4] + bne[4]), (3, 4));
    // INC [abs] beats a load, an INC and a store
    let (ea, size, x) = (Ea::Abs, 4, 0);
    let rmw = cycles(2, Kind::Rmw { ea, size, x });
    let ld = cycles(2, Kind::Ld { ea, size, x });
    let st = cycles(2, Kind::St { ea, size, x });
    for i in 0..CONFIGS.len() {
        assert!(rmw[i] < ld[i] + dec[i] + st[i], "{}", CONFIGS[i].0);
    }
    assert_eq!(rmw[1], 9);
}
