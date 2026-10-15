//! A fixed-base mode E, `[rT + 4R]` (draft 2's proposal, RFC 0028 10.1),
//! on 1b: `v1b+rtN` and the other `+rtN` names (Isa::parse). The
//! assembler picks the mode for `[rT + 0..60]` words, the machine reads
//! it as the word at rT + 4R, and in `v1bx+rtN` the tagged register
//! operations move to op F.

use toolchain::asm::Assembler;
use v1_isa::asm::encoder;
use v1_isa::timing::Config;
use v1_isa::{Isa, Machine};

fn assemble(isa: &str, src: &str) -> Vec<u8> {
    let mut a = Assembler::new(encoder(isa).unwrap(), false);
    a.load("t.s", Some(src)).unwrap();
    let img = a.assemble().unwrap_or_else(|e| panic!("{e}"));
    let top = *img.mem.keys().last().unwrap() as usize + 1;
    let mut bytes = vec![0u8; top];
    for (&addr, &b) in &img.mem {
        bytes[addr as usize] = b;
    }
    bytes
}

fn run(name: &str, src: &str) -> Machine {
    let (isa, rt) = Isa::parse(name).unwrap();
    let mut m = Machine::new(
        isa,
        &assemble(name, src),
        b"",
        Config::named("D32-separate").unwrap(),
    );
    m.rt = rt;
    m.run(10_000).unwrap();
    assert!(m.halted, "{name}: didn't halt");
    m
}

fn parcels(isa: &str, line: &str) -> Vec<u16> {
    let b = assemble(isa, &format!("        .org 0\n        {line}\n"));
    b.chunks(2)
        .map(|c| c[0] as u16 | (*c.get(1).unwrap_or(&0) as u16) << 8)
        .collect()
}

#[test]
fn names() {
    assert_eq!(Isa::parse("v1b"), Some((Isa::V1b, None)));
    assert_eq!(Isa::parse("v1b+rt14"), Some((Isa::V1b, Some(14))));
    assert_eq!(Isa::parse("v1bs+rt6"), Some((Isa::V1bs, Some(6))));
    assert_eq!(Isa::parse("v1a+rt1"), None);
    assert_eq!(Isa::parse("v1b+rt16"), None);
    // objects are named for the base ISA, so they link with its own
    assert_eq!(encoder("v1b+rt11").unwrap().name(), "v1b");
    assert_eq!(encoder("v1bs+rt14").unwrap().name(), "v1bs");
}

#[test]
fn encodings() {
    let cases: &[(&str, &[u16])] = &[
        ("MOV r1, [r11 + 8]", &[0x11E2]),
        ("ST r1, [r11 + 60]", &[0x21EF]),
        ("ADD r2, [r11 + 4]", &[0x42E1]),
        ("LEA r11, [r11 + 24]", &[0x3BE6]),
        ("JMP [r11 + 20]", &[0xB0E5]),
        // [r11] stays mode 2; beyond 60, unaligned, bytes and other bases
        // take the displacement mode
        ("MOV r1, [r11]", &[0x112B]),
        ("MOV r1, [r11 + 64]", &[0x113B, 0x0040]),
        ("MOV r1, [r11 + 6]", &[0x113B, 0x0006]),
        ("MOV r1, [r11 - 4]", &[0x113B, 0xFFFC]),
        ("MOV r1, byte [r11 + 8]", &[0x119B, 0x0008]),
        ("MOV r1, [r10 + 8]", &[0x113A, 0x0008]),
        ("MOV r1, [sp + 8]", &[0x1142]),
    ];
    for (line, want) in cases {
        assert_eq!(parcels("v1b+rt11", line), *want, "{line}");
    }
    assert_eq!(parcels("v1b", "MOV r1, [r11 + 8]"), [0x113B, 0x0008]);
    assert_eq!(parcels("v1bs+rt14", "ST r2, [r14 + 12]"), [0x22E3]);
}

#[test]
fn the_mode_reads_and_writes_rt_plus_4r() {
    let src = "
        .org 0
        MOV  r11, #data
        MOV  r1, [r11 + 8]
        ADD  r1, [r11 + 12]
        ST   r1, [r11 + 16]
        LEA  r2, [r11 + 60]
        MOV  r3, [r11 + 16]
        HALT
        .align 4
data:   .word 0, 0, 5, 7, 0
";
    let plain = run("v1b", src);
    let rt = run("v1b+rt11", src);
    let data = rt.r[11];
    assert_eq!((rt.r[1], rt.r[3]), (12, 12));
    assert_eq!(rt.r[2], data + 60);
    assert_eq!(rt.mem[data as usize + 16], 12);
    assert_eq!((plain.r[1], plain.r[2] - plain.r[11]), (12, 60));
    // five instructions a parcel shorter, a cycle each on D32-separate
    assert_eq!(plain.instructions, rt.instructions);
    assert_eq!(plain.cycles - rt.cycles, 5);
}

#[test]
fn without_rt_mode_e_is_illegal() {
    // 1b reserves mode E: the illegal-instruction vector at 8
    let mut m = Machine::new(
        Isa::V1b,
        &[0xE2, 0x11, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        b"",
        Config::named("D32-separate").unwrap(),
    );
    m.step().unwrap();
    assert_eq!(m.pc, 8);
}

#[test]
fn v1bx_with_rt_has_the_tagged_operations_in_op_f() {
    // ADD.T r1, r2 is F 1 2 A; CMP.T r3, r0 is F 3 0 C
    let src = "
        .org 0
        MOV  r1, #20
        MOV  r2, #22
        .half 0xF12A
        .half 0xF30C
        HALT
        .org 0x18
        HALT
";
    let m = run("v1bx+rt14", src);
    assert_eq!(m.r[1], 42);
    let bad = src.replace("MOV  r2, #22", "MOV  r2, #23");
    let m = run("v1bx+rt14", &bad);
    assert_eq!(m.pc, 0x1A, "an odd operand takes the tag trap");
}
