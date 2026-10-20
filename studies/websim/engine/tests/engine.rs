//! The engine: descriptions and their mistakes, the plain board's console
//! that waits for the terminal, and the mouse given to a machine a sample
//! at a time. The studies' machines themselves are checked from Python
//! (studies/websim/tests), which builds them.

use std::sync::{Arc, Mutex};

use toolchain::asm::Assembler;
use websim::{Board, Session, Setup, Status};

fn setup(board: &str, params: &[(&str, &str)]) -> Setup {
    let mut s = Setup::new(board);
    for (n, v) in params {
        s.param(n, v);
    }
    s
}

fn error(s: Setup) -> String {
    s.start().err().expect("an error")
}

#[test]
fn mistakes_in_a_description() {
    assert_eq!(error(setup("pdp11", &[])), "no board \"pdp11\"");
    assert_eq!(
        error(setup("plain", &[("speed", "3")])),
        "the plain board takes no speed"
    );
    assert_eq!(error(setup("plain", &[("isa", "v3")])), "no ISA \"v3\"");
    assert!(error(setup("fen", &[("ram_size", "lots")])).contains("not a number"));
    assert!(error(setup("fen", &[("ram_size", "-4")])).contains("32-bit whole number"));
    let mut s = setup("plain", &[]);
    s.load("disk", 0, vec![1]);
    assert!(error(s).contains("nothing to load called \"disk\""));
    let mut s = setup("plain", &[]);
    s.load("ram", 0xFFFF0, vec![0; 32]);
    assert!(error(s).contains("don't fit in RAM"));
}

/// Draft 2: the console's bytes back in capitals, until its end.
const UPCASE: &str = "\
loop:   MOV  r1, [0xFFFFFF00]
        CMP  r1, #-1
        BEQ  done
        CMP  r1, #'a'
        BLO  out
        CMP  r1, #'z'
        BHI  out
        SUB  r1, #32
out:    MOV  byte [0xFFFFFF00], r1
        BRA  loop
done:   HALT
";

fn image(src: &str) -> Vec<u8> {
    assemble(v2_isa::asm::encoder("v2").unwrap(), src)
}

fn assemble(enc: &'static dyn toolchain::asm::Encoder, src: &str) -> Vec<u8> {
    let mut a = Assembler::new(enc, false);
    a.load("t.s", Some(src)).unwrap();
    let img = a.assemble().unwrap_or_else(|e| panic!("{e}"));
    let mut mem = vec![0u8; 0x100];
    for (&addr, &v) in &img.mem {
        mem[addr as usize] = v;
    }
    mem
}

#[test]
fn the_plain_console_waits_for_the_terminal() {
    let mut s = setup("plain", &[("isa", "v2"), ("clock_hz", "6e6")]);
    s.load("ram", 0, image(UPCASE));
    s.load("console", 0, b"ok ".to_vec());
    let mut m = s.start().unwrap();
    assert_eq!(m.board_ref().clock_hz(), 6e6);
    assert_eq!(m.run(1_000_000, 1_000_000), Ok(Status::Waiting));
    assert_eq!(m.board().take_output(), b"OK ");
    // waiting costs nothing
    let c = m.board_ref().cycles();
    assert_eq!(m.run(1_000_000, 1_000_000), Ok(Status::Waiting));
    assert_eq!(m.board_ref().cycles(), c);
    m.board().send(b"hi\n");
    assert_eq!(m.run(1_000_000, 1_000_000), Ok(Status::Waiting));
    assert_eq!(m.board().take_output(), b"HI\n");
    m.board().close();
    assert_eq!(m.run(1_000_000, 1_000_000), Ok(Status::Halted));
    let regs = m.board_ref().registers();
    assert_eq!(regs[1], ("r1".to_string(), 0xFFFF_FFFF));
    assert_eq!(&m.board_ref().peek(0, 2)[..], &image(UPCASE)[..2]);
}

#[test]
fn a_slice_stops_at_its_steps_or_cycles() {
    let mut s = setup("plain", &[("isa", "v1b")]);
    let spin = assemble(v1_isa::asm::encoder("v1b").unwrap(), "here:   BRA  here\n");
    s.load("ram", 0, spin);
    let mut m = s.start().unwrap();
    assert_eq!(m.run(u64::MAX, 100), Ok(Status::Ran));
    assert_eq!(m.board_ref().instructions(), 100);
    // 500 cycles more, to the end of the instruction that reaches them
    let c = m.board_ref().cycles();
    assert_eq!(m.run(500, u64::MAX), Ok(Status::Ran));
    let ran = m.board_ref().cycles() - c;
    assert!((500..510).contains(&ran), "{ran}");
}

/// What the mouse was given, with when.
type Given = Arc<Mutex<Vec<(u64, i32, i32, u8)>>>;

/// A board that only has a screen and a mouse.
#[derive(Default)]
struct Mouse {
    cycles: u64,
    given: Given,
}

impl Board for Mouse {
    fn run(&mut self, until: u64, _steps: u64) -> Result<Status, String> {
        self.cycles = until;
        Ok(Status::Ran)
    }
    fn cycles(&self) -> u64 {
        self.cycles
    }
    fn instructions(&self) -> u64 {
        0
    }
    fn clock_hz(&self) -> f64 {
        1e6
    }
    fn send(&mut self, _bytes: &[u8]) {}
    fn take_output(&mut self) -> Vec<u8> {
        Vec::new()
    }
    fn screen_size(&self) -> Option<(u32, u32)> {
        Some((640, 480))
    }
    fn has_mouse(&self) -> bool {
        true
    }
    fn mouse(&mut self, dx: i32, dy: i32, buttons: u8) {
        self.given
            .lock()
            .unwrap()
            .push((self.cycles, dx, dy, buttons));
    }
    fn registers(&self) -> Vec<(String, u32)> {
        Vec::new()
    }
    fn peek(&self, _addr: u32, _len: u32) -> Vec<u8> {
        Vec::new()
    }
}

#[test]
fn the_mouse_goes_a_sample_at_a_time() {
    let given = Given::default();
    let mut s = Session::new(Box::new(Mouse {
        cycles: 0,
        given: given.clone(),
    }));
    let take = || std::mem::take(&mut *given.lock().unwrap());
    // from the middle of the screen, past its corner: it stops at the edge
    s.mouse_to(700, 470, 0);
    assert!(s.mouse_busy());
    s.run(1_000_000, u64::MAX).unwrap();
    assert!(!s.mouse_busy());
    // 25 ms apart at 1 MHz, at most 200 counts each way
    assert_eq!(take(), vec![(0, 200, 200, 0), (25_000, 119, 30, 0)]);
    // a click: the press and the release in samples of their own, and
    // motion while a button is held doesn't move the press
    s.mouse_to(639, 470, 1);
    s.mouse_to(600, 400, 1);
    s.mouse_to(600, 400, 0);
    s.run(1_000_000, u64::MAX).unwrap();
    assert_eq!(
        take(),
        vec![
            (1_000_000, 0, 0, 1),
            (1_025_000, -39, -70, 1),
            (1_050_000, 0, 0, 0)
        ]
    );
}
