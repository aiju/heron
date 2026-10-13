//! The draft 1 machine on hand-encoded draft 1b programs, and the timing
//! model on a few keys. The whole programs are checked against their
//! expected output from Python (heron v1_isa test).

use v1_isa::key::{Ea, How, Key, Kind};
use v1_isa::timing::{CONFIGS, Config};
use v1_isa::{Isa, Machine};

/// A machine with 16-bit parcels at address 0.
fn machine(parcels: &[u16]) -> Machine {
    let image: Vec<u8> = parcels.iter().flat_map(|p| p.to_le_bytes()).collect();
    Machine::new(Isa::V1b, &image, b"", Config::named("D16-overlap").unwrap())
}

const HALT: u16 = 0x0000;

#[test]
fn moves_adds_and_halts() {
    // MOV r1, #5; ADD r1, #3; HALT
    let mut m = machine(&[0x1115, 0x4113, HALT]);
    m.run(1000).unwrap();
    assert_eq!((m.r[1], m.instructions, m.halted), (8, 3, true));
    assert_eq!((m.n, m.z, m.c, m.v), (0, 0, 0, 0));
}

#[test]
fn divide_by_zero_traps_to_its_vector() {
    // MOV sp, #0x8000; MOV r1, #5; DIVU r1, r2 (r2 = 0); and HALT at the
    // divide vector (0x10, zero)
    let mut m = machine(&[0x1FF1, 0x8000, 0x1115, 0xF126]);
    m.run(1000).unwrap();
    assert_eq!(m.traps, [(6, "divide by zero".to_string())]);
    assert!(m.in_trap);
    assert_eq!(m.pc, 0x12);
    // the trap pushed the faulting PC, then the flags
    assert_eq!(m.r[15], 0x8000 - 8);
    assert_eq!(&m.mem[0x8000 - 4..0x8000], &6u32.to_le_bytes());
}

#[test]
fn a_store_into_decoded_code_is_seen() {
    //     mov r1, #1
    //     mov r2, #0
    // loop:
    // site:
    //     nop                     ; patched to "add r1, #3" the first time round
    //     add r2, #1
    //     cmp r2, #2
    //     beq done
    //     mov r3, #0x4113         ; add r1, #3
    //     st r3, half [site]
    //     bra loop
    // done:
    //     halt
    let mut m = machine(&[
        0x1111, 0x1210, 0x0001, 0x4211, 0x6212, 0xE005, 0x13F0, 0x4113, 0x23F6, 0x0004, 0xEEF7,
        HALT,
    ]);
    m.run(1000).unwrap();
    assert_eq!((m.r[1], m.r[2], m.instructions), (4, 2, 14));
}

#[test]
fn unmapped_access_is_an_error() {
    // MOV r1, [abs32 0x200000]
    let mut m = machine(&[0x11F7, 0x0000, 0x0020]);
    let e = m.run(1000).unwrap_err();
    assert_eq!(e, "access to unmapped address 00200000 at pc 00000000");
}

#[test]
fn timing_keys_cost_what_timing32_says() {
    let cycles =
        |n, p2, kind, config: &str| Config::named(config).unwrap().cycles(Key { n, p2, kind });
    assert_eq!(cycles(1, 0, Kind::Alu { wb: 1 }, "D16-overlap"), 3);
    assert_eq!(
        cycles(
            2,
            2,
            Kind::Ld {
                ea: Ea::Rd,
                size: 4,
                x: 1
            },
            "D16-wide"
        ),
        5
    );
    assert_eq!(
        cycles(
            1,
            0,
            Kind::Call {
                how: How::Rel,
                x: 0
            },
            "D32-separate"
        ),
        4
    );
    assert_eq!(cycles(1, 0, Kind::Div { signed: 1 }, "D16-separate"), 70);
    assert_eq!(CONFIGS.len(), 6);
}

#[test]
fn restore_wraps_past_the_top_of_memory() {
    // MOV sp, #-4; RESTORE r1-r2; HALT: r1 comes from the last word of the
    // I/O page, r2 from address 0 (the program's first two parcels), as a
    // 32-bit address counter would have it
    let mut m = machine(&[0x1FD3, 0x0126, HALT]);
    m.run(1000).unwrap();
    assert_eq!(m.r[2], 0x0126_1FD3);
    assert_eq!(m.r[15], 4);
    assert!(m.halted);
}
