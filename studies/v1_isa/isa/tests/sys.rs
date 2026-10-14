//! v1bs, the kernel study's system extensions (src/sys.rs): a supervisor
//! enters user mode through a map, a user page fault is restarted, and
//! user mode can't run privileged instructions. The study's own tests
//! (studies/kernel/tests) cover the rest from Python.

use toolchain::asm::Assembler;
use v1_isa::asm::encoder;
use v1_isa::sys::{FSR_INVALID, FSR_STORE};
use v1_isa::timing::Config;
use v1_isa::{Isa, Machine};

fn machine(src: &str) -> Machine {
    let mut a = Assembler::new(encoder("v1bs").unwrap(), false);
    a.load("t.s", Some(src)).unwrap();
    let img = a.assemble().unwrap_or_else(|e| panic!("{e}"));
    let top = *img.mem.keys().last().unwrap() as usize + 1;
    let mut bytes = vec![0u8; top];
    for (&addr, &b) in &img.mem {
        bytes[addr as usize] = b;
    }
    Machine::new(
        Isa::V1bs,
        &bytes,
        b"",
        Config::named("D32-separate").unwrap(),
    )
}

/// A supervisor that maps virtual page 0 of context 1 to the user code at
/// 0x1000 and page 1 to a stack, enters user mode at 0, and maps page 2
/// when the user faults on it. Privilege violations halt with r9 = the
/// faulting PC.
const PROGRAM: &str = "
        .org 0x00
        JMP  start
        .org 0x0C
        JMP  swi
        .org 0x1C
        JMP  priv
        .org 0x20
        JMP  fault
        .org 0x40
start:  MOV  sp, #0x800
        MOV  r1, #1
        MTSR ctx, r1
        MOV  r1, #0x1000        ; context 1, page 0
        MTSR mapa, r1
        MOV  r1, #0x1007        ; physical 0x1000, valid, writable, executable
        MTSR mapd, r1
        MOV  r1, #0x2003        ; page 1: physical 0x2000, valid, writable
        MTSR mapd, r1
        MOV  r1, #0x2000        ; the user's sp
        MTUR sp, r1
        ST   r0, -[sp]          ; its PC
        ST   r0, -[sp]          ; its flags: user mode
        RTI
swi:    MFUR r6, r1
        ADD  r6, #100
        MTUR r1, r6
        RTI
fault:  PUSH r1                 ; (no banks: these are the user's registers)
        MFSR r7, far
        MFSR r8, fsr
        MOV  r1, #0x1002        ; page 2: physical 0x3000
        MTSR mapa, r1
        MOV  r1, #0x3003
        MTSR mapd, r1
        POP  r1
        RTI
priv:   MOV  r9, [sp + 4]       ; the saved PC
        HALT

        .org 0x1000             ; the user's code, at virtual 0
        MOV  r1, #5
        SWI  #1                 ; r1 = 105
        PUSH r1
        MOV  r2, #0x2000
        ST   r1, [r2]+          ; faults the first time: r2 must not move
        MOV  r3, [r2 - 4]
        HALT                    ; privileged
";

#[test]
fn user_mode_through_the_map() {
    let mut m = machine(PROGRAM);
    m.run(10_000).unwrap();
    let sys = m.sys.as_deref().unwrap();
    // the system call, the push to the user stack (virtual 0x1FFC, in
    // page 1 at physical 0x2000), the faulting store restarted once and
    // then done
    assert_eq!(m.r[3], 105);
    assert_eq!(&m.mem[0x2FFC..0x3000], &105u32.to_le_bytes());
    assert_eq!(&m.mem[0x3000..0x3004], &105u32.to_le_bytes());
    assert_eq!(m.r[7], 0x2000);
    assert_eq!(m.r[8], FSR_INVALID | FSR_STORE);
    assert_eq!(sys.page_faults, 1);
    // HALT in user mode is a privilege violation at its own address
    assert_eq!(m.r[9], 0x10);
    assert_eq!(m.traps, [(0x10, "privileged instruction".to_string())]);
    assert_eq!(sys.s, 1);
}

#[test]
fn plain_1b_has_no_system_registers() {
    // MFSR r1, far on plain 1b is illegal: assembled as v1bs, run as v1b
    let mut a = Assembler::new(encoder("v1bs").unwrap(), false);
    a.load(
        "t.s",
        Some("        MOV sp, #0x800\n        MFSR r1, far\n        HALT\n"),
    )
    .unwrap();
    let img = a.assemble().unwrap();
    let bytes: Vec<u8> = img.mem.values().copied().collect();
    let mut m = Machine::new(
        Isa::V1b,
        &bytes,
        b"",
        Config::named("D32-separate").unwrap(),
    );
    m.run(1000).unwrap();
    assert_eq!(m.traps.len(), 1);
    assert_eq!(m.traps[0].1, "illegal instruction");
}
