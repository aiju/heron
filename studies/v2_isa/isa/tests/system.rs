//! Draft 2 in system mode (RFC 0029): modes and privilege, the window and
//! the page map, precise faults, register banks, the status register,
//! interrupts by level, HALT's wait, trace, and the tentative BCOPY. The
//! machine without a supervisor is tests/v2.rs's.

use toolchain::asm::Assembler;
use v2_isa::asm::encoder;
use v2_isa::sys::*;
use v2_isa::timing::Config;
use v2_isa::{Machine, RunStatus};

/// A board for the tests, at physical 0x1000_0000:
///   +0   W: a byte to the console       R: the levels set by +4
///   +4   W: the interrupt levels requesting (a bit per level)
///   +8   R: the cycle count
///   +C   W: interrupt at level 3 this many cycles from now
///   +10  W: acknowledge that interrupt
struct TestBus {
    out: Vec<u8>,
    levels: u8,
    timer_at: u64,
    timer_on: bool,
}

const DEV: u32 = 0x1000_0000;

impl Bus for TestBus {
    fn read(&mut self, pa: u32, _size: u32, cycles: u64) -> Option<u32> {
        match pa {
            DEV => Some(self.levels as u32),
            0x1000_0008 => Some(cycles as u32),
            0x1000_0004 | 0x1000_000C | 0x1000_0010 => Some(0),
            _ => None,
        }
    }

    fn write(&mut self, pa: u32, _size: u32, v: u32, cycles: u64) -> bool {
        match pa {
            DEV => self.out.push(v as u8),
            0x1000_0004 => self.levels = v as u8,
            0x1000_000C => {
                self.timer_at = cycles + v as u64;
                self.timer_on = true;
            }
            0x1000_0010 => self.timer_on = false,
            _ => return false,
        }
        true
    }

    fn irq(&mut self, cycles: u64) -> (u8, u64) {
        let mut mask = self.levels;
        let mut next = u64::MAX;
        if self.timer_on {
            if cycles >= self.timer_at {
                mask |= 1 << 3;
            } else {
                next = self.timer_at;
            }
        }
        (mask, next)
    }
}

/// Assemble `src` (which places itself with .org, the kernel at
/// 0x8000_0000 and up) and load it into a system-mode machine with 1 MB of
/// RAM: window addresses at their physical address, the rest as they are.
fn machine(src: &str) -> Machine {
    let mut a = Assembler::new(encoder("v2").unwrap(), false);
    a.load("t.s", Some(src)).unwrap();
    let img = a.assemble().unwrap_or_else(|e| panic!("{e}"));
    let bus = TestBus {
        out: Vec::new(),
        levels: 0,
        timer_at: 0,
        timer_on: false,
    };
    let mut m = Machine::new_system(0x10_0000, Box::new(bus), Config::named("D16-overlap").unwrap());
    for (&addr, &v) in &img.mem {
        m.mem[(addr as u32 & 0x7FFF_FFFF) as usize] = v;
    }
    m
}

fn run(src: &str) -> Machine {
    let mut m = machine(src);
    let st = m.run_system(1_000_000, u64::MAX).unwrap();
    assert_eq!(st, RunStatus::Halted, "pc {:08X}", m.pc);
    m
}

fn out(m: &mut Machine) -> String {
    String::from_utf8(m.sys_mut().bus_as::<TestBus>().unwrap().out.clone()).unwrap()
}

/// The vectors: every exception goes to `fault`, which prints the vector's
/// offset as a letter ('A' + offset / 4) and halts, unless a test defines
/// its own handlers after. SWIs go to `swi`, interrupts to `irqN`.
const VECTORS: &str = "
        .org 0x80000000
        JMP  reset
        .org 0x80000008
        JMP  ex08
        .org 0x8000000C
        JMP  ex0C
        .org 0x80000010
        JMP  ex10
        .org 0x80000014
        JMP  ex14
        .org 0x8000001C
        JMP  ex1C
        .org 0x80000020
        JMP  ex20
        .org 0x80000024
        JMP  ex24
        .org 0x8000004C
        JMP  irq3
        .org 0x80000050
        JMP  irq4
        .org 0x80000054
        JMP  irq5
        .org 0x80000114
        JMP  swi5
        .org 0x80001000
reset:  MOV  sp, #0x80008000
        MOV  r13, #0x90000000       ; the console, through the window
";

/// A report of the exception, and HALT with interrupts off.
const FAULT: &str = "
ex08:   MOV  r1, #'I'
        BRA  report
ex0C:   MOV  r1, #'B'
        BRA  report
ex10:   MOV  r1, #'D'
        BRA  report
ex14:   MOV  r1, #'A'
        BRA  report
ex1C:   MOV  r1, #'P'
        BRA  report
ex20:   MOV  r1, #'F'
        BRA  report
ex24:   MOV  r1, #'T'
        BRA  report
irq3:
irq4:
irq5:
swi5:   MOV  r1, #'?'
report: MOV  [r13], r1
        DI
        HALT
";

/// Map page `va` of context `ctx` to physical page `pa` with `bits`, in
/// supervisor code (clobbers r1, r2).
fn map(ctx: u32, va: u32, pa: u32, bits: u32) -> String {
    format!(
        "        MOV  r1, #{}\n        MTSR mapa, r1\n        MOV  r2, #{}\n        MTSR mapd, r2\n",
        ctx * 4096 + (va >> 12),
        (pa & !0xFFF) | bits
    )
}

/// Enter user mode at `pc` in context `ctx` and bank `bank`, with `sr`
/// (S clear), through RTI.
fn to_user(ctx: u32, bank: u32, pc: u32, sr: u32) -> String {
    format!(
        "        MOV  r1, #{ctx}\n        MTSR ctx, r1\n        MOV  r1, #{bank}\n        MTSR bank, r1\n\
         \x20       MOV  r1, #{pc}\n        PUSH r1\n        MOV  r1, #{sr}\n        PUSH r1\n        RTI\n"
    )
}

#[test]
fn reset_starts_in_supervisor_mode_at_the_window() {
    let mut m = run(&format!(
        "{VECTORS}
        MFSR r1, sr
        MOV  r2, r1
        LSR  r2, #24
        LSR  r2, #4
        ADD  r2, #'0'
        MOV  [r13], r2              ; 8: S set, I T and IPL clear
        DI
        HALT
{FAULT}"
    ));
    assert_eq!(out(&mut m), "8");
    assert_eq!(m.r[1], SR_S);
    assert!(m.sys().supervisor);
}

#[test]
fn user_mode_runs_in_its_bank_and_context() {
    // page 0 of context 5 is physical 0x20000; user code there sets r1-r3
    // and makes a system call, which the supervisor reads with MFUR
    let mut m = run(&format!(
        "{VECTORS}
{}{}
{}
{FAULT}
        .org 0x80020000
        MOV  r1, #'u'
        MOV  r2, #'s'
        MOV  r3, #'r'
        SWI  #5
        .org 0x80003000
swi5:   MOV  r1, #11                ; the supervisor's own r1
        MFUR r4, r1
        MOV  [r13], r4
        MFUR r4, r2
        MOV  [r13], r4
        MFUR r4, r3
        MOV  [r13], r4
        MOV  r5, #'!'
        MTUR r9, r5                 ; the user's r9
        MFSR r6, sr                 ; S, interrupts as the trap left them
        MOV  r7, [sp]               ; the saved sr: user mode
        MOV  r8, [sp + 4]           ; the saved PC: after the SWI
        DI
        HALT
",
        map(5, 0, 0x20000, PTE_V | PTE_X),
        "",
        to_user(5, 9, 0, 0),
    ).replace("swi5:   MOV  r1, #'?'", "")
    .replace("irq5:\n", "irq5:   MOV  r1, #'?'\n"));
    assert_eq!(out(&mut m), "usr");
    assert_eq!(m.r[1], 11, "the supervisor's r1 is its own");
    assert_eq!(m.r[6], SR_S);
    assert_eq!(m.r[7] & SR_S, 0);
    assert_eq!(m.r[8], 8);
    let s = m.sys();
    assert_eq!(s.banks[9][1], b'u' as u32);
    assert_eq!(s.banks[9][9], b'!' as u32);
    assert_eq!(s.cur_bank, 0);
}

/// Run user code at virtual 0 of context 1 (physical 0x20000, executable,
/// not writable) with page 1 (physical 0x21000) writable data, and every
/// exception reported; `regs` are the user's registers to start with.
fn user_with(code: &str, regs: &[(u32, u32)]) -> Machine {
    let mut set = String::new();
    for (r, v) in regs {
        set += &format!("        MOV  r1, #{v}\n        MTUR r{r}, r1\n");
    }
    run(&format!(
        "{VECTORS}
{}{}        MOV  r1, #1\n        MTSR bank, r1\n{set}{}
{FAULT}
        .org 0x80020000
{code}
        .org 0x80021000
data:   .word 0x12345678
",
        map(1, 0, 0x20000, PTE_V | PTE_X),
        map(1, 0x1000, 0x21000, PTE_V | PTE_W),
        to_user(1, 1, 0, 0),
    ))
}

fn user(code: &str) -> Machine {
    user_with(code, &[])
}

#[test]
fn privileged_instructions_trap_in_user_mode() {
    for insn in [
        "HALT",
        "EI",
        "DI",
        "RTI",
        "SPL #3",
        "MFSR r1, sr",
        "MTSR sr, r1",
        "MTSR ctx, r1",
        "MFSR r1, far",
        "MFUR r1, r2",
        "MTUR r1, r2",
        "BCOPY r1, r2",
    ] {
        let mut m = user(&format!("        MOV r9, #1\n        {insn}\n"));
        assert_eq!(out(&mut m), "P", "{insn}");
        // the saved PC is the instruction's own
        assert_eq!(m.rd32(m.r[15] + 4).unwrap(), 2, "{insn}");
    }
}

#[test]
fn user_mode_reads_and_writes_ccr() {
    let mut m = user(
        "        MOV  r1, #-1
        MOVS r1, r1                 ; N
        MFSR r2, ccr
        MOV  r3, #4                 ; Z
        MTSR ccr, r3
        BNE  bad
        MOV  r4, #'0'
        ADD  r4, r2
        MOV  r5, #0x1000
        MOV  [r5], r4
        SWI  #5
bad:    SWI  #6
",
    );
    // the SWI reports '?'; the data page has '8' (N is bit 3)
    assert_eq!(out(&mut m), "?");
    assert_eq!(m.mem[0x21000], b'8');
}

#[test]
fn page_faults_are_precise_and_say_why() {
    // (instruction, the access's address, fsr)
    let cases = [
        ("MOV r1, [r2]+", 0x5000, FSR_INVALID),
        ("MOV [r2], r1", 0x0000, FSR_NOWRITE | FSR_STORE),
        ("MOV r1, [r2]", 0x8000_0100, FSR_WINDOW),
        ("MOV r1, [r2]", 0x0100_0000, FSR_RANGE),
        ("JMP r2", 0x1000, FSR_NOEXEC | FSR_FETCH),
        ("CALL r2", 0x7000, FSR_INVALID | FSR_FETCH),
        ("INC [r2]", 0x0004, FSR_NOWRITE | FSR_STORE),
    ];
    for (insn, addr, fsr) in cases {
        // the instruction at 2, with r2 set before user mode starts
        let mut m = user_with(&format!("        MOV  r7, #77\n        {insn}\n"), &[(2, addr)]);
        assert_eq!(out(&mut m), "F", "{insn}");
        let s = m.sys();
        assert_eq!((s.far, s.fsr), (addr, fsr), "{insn}");
        let frame = m.r[15];
        let pc = m.rd32(frame + 4).unwrap();
        // a fault fetching the target is the jump's target, not the jump
        let want = if fsr & FSR_FETCH != 0 { addr } else { 2 };
        assert_eq!(pc, want, "{insn}");
        let b = &m.sys().banks[1];
        assert_eq!(b[2], addr, "{insn}: the address register is unchanged");
        if insn.starts_with("CALL") {
            // the call happened, and the fault is at its target
            assert_eq!(b[7], 4);
        } else {
            assert_eq!(b[7], 77);
        }
    }
}

#[test]
fn a_faulting_instruction_runs_again_after_rti() {
    // demand paging: the fault handler maps the page and returns, and the
    // load with auto-increment then completes once
    let mut m = run(&format!(
        "{VECTORS}
{}{}
{FAULT}
        .org 0x80020000
        MOV  r2, #0x5000
        MOV  r1, [r2]+
        MOV  r3, [r2]
        SWI  #5
        .org 0x80003000
ex20:   MFSR r9, far
        MFSR r10, fsr
        MOV  r1, #4096 + 5          ; context 1, page 5
        MTSR mapa, r1
        MOV  r1, #0x22000 + 3       ; V W
        MTSR mapd, r1
        MOV  r1, #0x80022000
        MOV  r2, #'x'
        MOV  [r1], r2
        MOV  r2, #'y'
        MOV  [r1 + 4], r2
        RTI
swi5:   MFUR r1, r1
        MOV  [r13], r1
        MFUR r1, r3
        MOV  [r13], r1
        MFUR r1, r2
        DI
        HALT
",
        map(1, 0, 0x20000, PTE_V | PTE_X),
        to_user(1, 1, 0, 0),
    )
    .replace("ex20:   MOV  r1, #'F'\n        BRA  report\n", "")
    .replace("swi5:   MOV  r1, #'?'", "        MOV  r1, #'?'"));
    assert_eq!(out(&mut m), "xy");
    assert_eq!(m.r[1], 0x5004, "incremented once");
    assert_eq!((m.r[9], m.r[10]), (0x5000, FSR_INVALID));
}

#[test]
fn the_supervisor_uses_user_pointers_through_the_map() {
    // a system call reads the user's buffer at its own address; a bad one
    // faults with fsr bit 7 set
    let mut m = run(&format!(
        "{VECTORS}
{}{}{}
{FAULT}
        .org 0x80020000
        MOV  r1, #0x1000
        SWI  #5
        .org 0x80021000
        .word 'k'
        .org 0x80003000
swi5:   MFUR r2, r1
        MOV  r3, [r2]
        MOV  [r13], r3
        MOV  r2, #0x9000
        MOV  r3, [r2]
        DI
        HALT
",
        map(1, 0, 0x20000, PTE_V | PTE_X),
        map(1, 0x1000, 0x21000, PTE_V | PTE_W),
        to_user(1, 1, 0, 0),
    )
    .replace("swi5:   MOV  r1, #'?'", "        MOV  r1, #'?'"));
    assert_eq!(out(&mut m), "kF");
    assert_eq!(m.sys().fsr, FSR_INVALID | FSR_SUPER);
}

#[test]
fn mtsr_sr_leaves_s_and_rti_restores_the_mode() {
    let mut m = run(&format!(
        "{VECTORS}
        MOV  r1, #0                 ; S clear in what is written
        MTSR sr, r1
        MFSR r2, sr                 ; still supervisor: a privileged read works
        MOV  r3, #0x45000000        ; I, IPL 5
        MTSR sr, r3
        MFSR r4, sr
        DI
        HALT
{FAULT}"
    ));
    assert_eq!(out(&mut m), "");
    assert_eq!(m.r[2], SR_S);
    assert_eq!(m.r[4], SR_S | SR_I | 5 << 24);
}

#[test]
fn map_entries_read_back_and_mapd_moves_on() {
    let m = run(&format!(
        "{VECTORS}
        MOV  r1, #4096 * 3 + 10
        MTSR mapa, r1
        MOV  r2, #0x12345FFF        ; bits 11-3 read as 0
        MTSR mapd, r2
        MOV  r2, #0x00042001
        MTSR mapd, r2
        MFSR r5, mapa
        MTSR mapa, r1
        MFSR r3, mapd
        INC  r1
        MTSR mapa, r1
        MFSR r4, mapd
        DI
        HALT
{FAULT}"
    ));
    assert_eq!(m.r[3], 0x12345007);
    assert_eq!(m.r[4], 0x00042001);
    assert_eq!(m.r[5], 4096 * 3 + 12);
}

#[test]
fn interrupts_by_level_with_ipl() {
    // levels 3 and 5 request; with IPL 4 only 5 is taken, and it runs with
    // IPL 6; an EI in its handler doesn't let 3 in until IPL drops
    let mut m = run(&format!(
        "{VECTORS}
        MOV  r9, #0x90000004        ; the levels
        MOV  r1, #(1 << 3) | (1 << 5)
        MOV  [r9], r1
        SPL  #4
        EI
        NOP
        MOV  r1, #'.'
        MOV  [r13], r1
        SPL  #0
        NOP
        DI
        HALT
{FAULT}
        .org 0x80003000
irq5:   MFSR r2, sr
        MOV  r1, #'5'
        MOV  [r13], r1
        MOV  r1, #1 << 3            ; level 5 goes away
        MOV  [r9], r1
        EI
        NOP
        RTI
irq3:   MFSR r3, sr
        MOV  r1, #'3'
        MOV  [r13], r1
        CLR  [r9]
        RTI
"
    )
    .replace("irq3:\nirq4:\nirq5:\n", "irq4:\n"));
    assert_eq!(out(&mut m), "5.3");
    assert_eq!(m.r[2], SR_S | 6 << 24, "level 5 runs at IPL 6 with I clear");
    assert_eq!(m.r[3], SR_S | 4 << 24);
    assert_eq!(m.sys().interrupts[5], 1);
    assert_eq!(m.sys().interrupts[3], 1);
}

#[test]
fn no_interrupt_straight_after_ei() {
    let mut m = run(&format!(
        "{VECTORS}
        MOV  r9, #0x90000004
        MOV  r1, #1 << 4
        MOV  [r9], r1
        MOV  r12, #'a'
        EI
        MOV  [r13], r12             ; runs before the interrupt
        MOV  r1, #'c'
        MOV  [r13], r1
        DI
        HALT
{FAULT}
        .org 0x80003000
irq4:   MOV  r2, #'b'
        MOV  [r13], r2
        CLR  [r9]
        RTI
"
    )
    .replace("irq3:\nirq4:\nirq5:\n", "irq3:\nirq5:\n"));
    assert_eq!(out(&mut m), "abc");
}

#[test]
fn halt_waits_for_an_interrupt_and_skips_the_time() {
    let mut m = run(&format!(
        "{VECTORS}
        MOV  r9, #0x9000000C
        MOV  r1, #100000
        MOV  [r9], r1               ; level 3 in 100,000 cycles
        EI
        HALT
        MOV  r1, #'z'
        MOV  [r13], r1
        DI
        HALT
{FAULT}
        .org 0x80003000
irq3:   MOV  r1, #'w'
        MOV  [r13], r1
        MOV  r1, #0x90000010
        MOV  [r1], r1               ; acknowledge
        RTI
"
    )
    .replace("irq3:\nirq4:\nirq5:\n", "irq4:\nirq5:\n"));
    assert_eq!(out(&mut m), "wz");
    assert!(m.cycles > 100_000);
    assert!(m.idle_cycles > 99_000);
    assert!(m.instructions < 40);
}

#[test]
fn halt_with_nothing_to_wait_for_is_idle() {
    let mut m = machine(&format!("{VECTORS}\n        EI\n        HALT\n{FAULT}"));
    assert_eq!(m.run_system(1_000_000, u64::MAX).unwrap(), RunStatus::Idle);
    // something from outside, and it carries on
    m.sys_mut().bus_as::<TestBus>().unwrap().levels = 1 << 3;
    m.sys_mut().touched();
    assert_eq!(m.run_system(1_000_000, u64::MAX).unwrap(), RunStatus::Halted);
    assert_eq!(out(&mut m), "?");
}

#[test]
fn bcopy_copies_r0_to_r7_between_banks() {
    let m = run(&format!(
        "{VECTORS}
        MOV  r0, #100
        MOV  r1, #101
        MOV  r7, #107
        MOV  r8, #108
        MOV  r10, #4
        MOV  r11, #0
        BCOPY r10, r11              ; bank 0's r0-r7 into bank 4
        MOV  r10, #4
        MTSR bank, r10
        MFUR r12, r7
        MFUR r13, r8
        MFUR r14, r0
        MOV  r11, #5
        BCOPY r11, r10              ; bank 4 into bank 5, neither in use
        MOV  r0, #0
        MOV  r1, #0
        MOV  r11, #0
        MOV  r10, #5
        BCOPY r11, r10              ; and back into bank 0's
        DI
        HALT
{FAULT}"
    ));
    assert_eq!(m.r[12], 107);
    assert_eq!((m.r[0], m.r[1]), (100, 101));
    assert_eq!(&m.sys().banks[5][..8], &m.sys().banks[4][..8]);
    assert_eq!(m.r[13], 0, "r8 isn't copied");
    assert_eq!(m.r[14], 100);
    assert_eq!(&m.sys().banks[4][..8], &[100, 101, m.r[2], m.r[3], m.r[4], m.r[5], m.r[6], 107]);
}

#[test]
fn trace_traps_after_each_instruction() {
    // user code with T set: the trace handler counts and returns
    let m = run(&format!(
        "{VECTORS}
{}{}
{FAULT}
        .org 0x80020000
        NOP
        NOP
        NOP
        SWI  #5
        .org 0x80003000
ex24:   INC  r12
        RTI
swi5:   DI
        HALT
",
        map(1, 0, 0x20000, PTE_V | PTE_X),
        to_user(1, 1, 0, SR_T),
    )
    .replace("ex24:   MOV  r1, #'T'\n        BRA  report\n", "")
    .replace("swi5:   MOV  r1, #'?'", "        MOV  r1, #'?'"));
    // after each NOP and after the SWI's handler? No: SWI enters an
    // exception, which clears T
    assert_eq!(m.r[12], 3);
}

#[test]
fn nothing_answering_is_a_bus_error() {
    let mut m = run(&format!(
        "{VECTORS}
        MOV  r1, #0x90000100
        MOV  r2, [r1]
        DI
        HALT
{FAULT}"
    ));
    assert_eq!(out(&mut m), "B");
    assert_eq!(m.sys().far, 0x9000_0100);
}

#[test]
fn stores_to_code_forget_its_decode() {
    // the supervisor rewrites an instruction it has run
    let mut m = run(&format!(
        "{VECTORS}
        MOV  r5, #2
again:  BSR  patch
        DBNZ r5, again
        DI
        HALT
patch:  MOV  r1, #'1'              ; 71 16
        MOV  [r13], r1
        MOV  r2, #patch
        MOV  r3, #0x1672            ; MOV r1, #'2' is 72 16
        MOV  half [r2], r3
        RET
{FAULT}"
    ));
    assert_eq!(out(&mut m), "12");
}

#[test]
fn the_machine_without_a_supervisor_traps_the_system_half() {
    // MFUR, MTUR, SPL and BCOPY are illegal instructions there, as before
    let src = "        .org 0\n        JMP  start\n        .org 0x08\n        JMP  trap\n\
               \x20       .org 0x40\ntrap:   MOV  r14, #0x7E\n        HALT\n\
               start:  MOV  sp, #0x8000\n        INSN\n        HALT\n";
    for insn in ["MFUR r1, r2", "MTUR r1, r2", "SPL #2", "BCOPY r1, r2"] {
        let mut a = Assembler::new(encoder("v2").unwrap(), false);
        a.load("t.s", Some(&src.replace("INSN", insn))).unwrap();
        let img = a.assemble().unwrap();
        let mut mem = vec![0u8; 0x10000];
        for (&addr, &v) in &img.mem {
            mem[addr as usize] = v;
        }
        let mut m = Machine::new(&mem, b"", Config::named("D16-overlap").unwrap());
        m.run(100_000).unwrap();
        assert_eq!(m.r[14], 0x7E, "{insn}");
    }
}
