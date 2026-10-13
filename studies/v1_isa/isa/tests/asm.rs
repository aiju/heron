//! The draft 1 encoders through the assembler core. The expected
//! encodings came from the Python assembler the Rust one replaced.

use toolchain::asm::Assembler;
use toolchain::obj;
use v1_isa::asm::encoder;

/// The parcels of `line`, assembled at 0x100 with `here` at its address
/// and `far` at 0x30000.
fn encode(isa: &str, line: &str) -> Vec<u16> {
    let src = format!("        .org 0x100\nhere:   {line}\n        .org 0x30000\nfar:    HALT\n");
    let mut a = Assembler::new(encoder(isa).unwrap(), false);
    a.load("t.s", Some(&src)).unwrap();
    a.assemble().unwrap_or_else(|e| panic!("{line}: {e}"));
    a.stmts()
        .iter()
        .find(|s| s.kind == toolchain::asm::Kind::Insn)
        .unwrap()
        .words
        .clone()
}

fn error(isa: &str, src: &str) -> String {
    let mut a = Assembler::new(encoder(isa).unwrap(), false);
    a.load("t.s", Some(src)).unwrap();
    a.assemble().err().unwrap().to_string()
}

#[test]
fn v1a() {
    let cases: &[(&str, &[u16])] = &[
        ("MOV r1, #5", &[0xC105]),
        ("MOV r1, #300", &[0x8108, 0x012C]),
        ("MOV r1, #0x12340000", &[0x8128, 0x1234]),
        ("MOV r1, #0x12345678", &[0x8138, 0x5678, 0x1234]),
        ("ADD r2, r3", &[0x1230]),
        ("ADDI r4, -3", &[0xD4FD]),
        ("LD r1, [r2 + 8]", &[0x4122]),
        ("LDB r1, [r2 + 3]", &[0x6123]),
        ("LD r1, [r2 + 100]", &[0xA120, 0x0064]),
        ("LD r1, [r2 + 0x12345]", &[0xA12A, 0x2345, 0x0001]),
        ("LDH r1, [r2 - 2]", &[0xA124, 0xFFFE]),
        ("LEA r1, here", &[0xA109, 0xFFFC]),
        ("SAVE r8-r11", &[0x08B5]),
        ("LSL r1, #20", &[0xB144]),
        ("ASR r1, r2", &[0xB12A]),
        ("NEG r3", &[0x2331]),
        ("SETNE r1", &[0x011D]),
        ("SWI #42", &[0x02AC]),
        ("MFSR r1, hi", &[0x011A]),
        ("MTSR flags, r2", &[0x002B]),
        ("BEQ here", &[0x30FF]),
        ("JNE far", &[0x9110, 0x0000, 0x0003]),
        ("CALL far", &[0x9F10, 0x0000, 0x0003]),
        ("JMP r1", &[0x0012]),
        ("LI r1, -1", &[0xC1FF]),
        ("PUSH r8-r9", &[0x0895]),
        ("HALT", &[0x0000]),
    ];
    for (line, words) in cases {
        assert_eq!(encode("v1a", line), *words, "{line}");
    }
}

#[test]
fn v1b() {
    let cases: &[(&str, &[u16])] = &[
        ("MOV r1, #5", &[0x1115]),
        ("MOV r1, #-3", &[0x11D2]),
        ("MOV r1, #300", &[0x11F0, 0x012C]),
        ("MOV r1, #0x12345678", &[0x11F3, 0x5678, 0x1234]),
        ("ADD r2, r3", &[0x4203]),
        ("ADD r2, [r3]", &[0x4223]),
        ("MOV r1, [r2 + 8]", &[0x1132, 0x0008]),
        ("MOV r1, [sp + 8]", &[0x1142]),
        ("MOV r1, byte [r2 + 3]", &[0x1192, 0x0003]),
        ("MOV r1, half [r2]", &[0x11B2]),
        ("MOV r1, [r2]+", &[0x1162]),
        ("ST r1, -[sp]", &[0x217F]),
        ("MOV r1, [r2 + r3*4 + 1]", &[0x1152, 0x3A01]),
        ("MOV r1, [0x1234]", &[0x11F4, 0x1234]),
        ("MOV r1, [0x123456]", &[0x11F7, 0x3456, 0x0012]),
        ("MOV r1, [pc + here]", &[0x11FA, 0xFFFC]),
        ("LEA r1, here", &[0x31F4, 0x0100]),
        ("JMP [r1]", &[0xB021]),
        ("CALL #0x1234", &[0xB1F0, 0x1234]),
        ("ADC r1, r2", &[0xF120]),
        ("PUSH r1", &[0x217F]),
        ("POP r2", &[0x126F]),
        ("BSR here", &[0xEFFF]),
        ("JMP far", &[0xAE10, 0x0000, 0x0003]),
        ("SAVE r8-r11", &[0x08B5]),
        ("LSL r1, #20", &[0xD144]),
        ("SETGE r1", &[0x01AD]),
        ("LI r1, 0x10000", &[0x11F2, 0x0001]),
    ];
    for (line, words) in cases {
        assert_eq!(encode("v1b", line), *words, "{line}");
    }
}

#[test]
fn errors() {
    assert_eq!(
        error("v1a", "  MOV r1, [r2]+\n"),
        "t.s:1: MOV needs 'rd, rs' or 'rd, #imm'"
    );
    assert_eq!(
        error("v1a", "  LD r1, [r2 + r3]\n").split(": ").nth(1),
        Some("draft 1a has no register + register addressing")
    );
    assert_eq!(
        error("v1b", "  MVI r1, 3\n"),
        "t.s:1: draft 1b has no MVI: use MOV/ADD/CMP with #value"
    );
    assert_eq!(
        error("v1b", "  MOV r1, half [r2]+\n"),
        "t.s:1: there is no half [r]+ mode"
    );
    assert_eq!(
        error("v1b", "  SAVE r3-r1\n"),
        "t.s:1: register range must be within r1-r14, low to high"
    );
    assert_eq!(
        error("v1b", "  BRA 3\n"),
        "t.s:1: BRA target is at an odd address"
    );
    assert_eq!(
        error("v1b", "  frob r1\n"),
        "t.s:1: unknown instruction frob"
    );
}

#[test]
fn relocations() {
    // a call to another file's function (PC-relative, .far or not), a load
    // of a near variable, and a branch the assembler resolves itself
    let src = "        .far ext\n\
               f:      CALL ext\n\
               \x20       MOV r1, [near]\n\
               \x20       BRA f\n\
               \x20       .data\n\
               \x20       .word f\n";
    let mut a = Assembler::new(encoder("v1b").unwrap(), true);
    a.load("t.s", Some(src)).unwrap();
    let o = a.assemble_object("t.o").unwrap();
    let names: Vec<&str> = o.symbols.iter().map(|s| s.name.as_str()).collect();
    assert_eq!(names, [".text", ".data", "f", "ext", "near"]);
    let kinds: Vec<u32> = o.relocs.iter().map(|r| r.kind).collect();
    assert_eq!(kinds, [obj::PC16H, obj::ABS16S, obj::ABS32]);
    assert_eq!(o.symbols[3].flags, obj::SYM_GLOBAL | obj::SYM_FAR);
    assert_eq!(o.sections[0].size, 4 + 4 + 2);
}
