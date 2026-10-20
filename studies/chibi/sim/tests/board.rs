//! The board's devices against their datasheets and board2.py's netlist,
//! and the run loop on a small hand-made control store. The microcode's
//! own tests are Python's (studies/chibi/tests/test_sim.py), against
//! rtl2.py and draft 2's simulator.

use chibi_sim::board::US;
use chibi_sim::flash::Flash;
use chibi_sim::ps2::{Kind, Port};
use chibi_sim::store::{Aop, Carry, Cond, Store, WORDS, Word};
use chibi_sim::video::{LINE_TICKS, LINES, Palette, Video};
use chibi_sim::{Config, Machine, Status};

#[test]
fn flash_commands() {
    let mut f = Flash::new(US);
    let cmd = |f: &mut Flash, seq: &[(u32, u8)], t: u64| {
        for &(a, v) in seq {
            f.write(a, v, t);
        }
    };
    let unlock = [(0x5555, 0xAA), (0x2AAA, 0x55)];
    // program a byte: bits only go from 1 to 0, and it takes 20 µs
    cmd(&mut f, &unlock, 0);
    cmd(&mut f, &[(0x5555, 0xA0), (0x123, 0x5A)], 0);
    assert!(f.busy(10));
    let a = f.read(0x123, 10);
    let b = f.read(0x123, 11);
    assert_eq!(a & 0x80, !0x5A & 0x80, "data# polling");
    assert_ne!(a & 0x40, b & 0x40, "the toggle bit");
    let done = (21.0 * US) as u64;
    assert_eq!(f.read(0x123, done), 0x5A);
    cmd(&mut f, &unlock, done);
    cmd(&mut f, &[(0x5555, 0xA0), (0x123, 0xF0)], done);
    assert_eq!(f.read(0x123, 2 * done), 0x50);
    // the software ID, and back
    cmd(&mut f, &unlock, 2 * done);
    cmd(&mut f, &[(0x5555, 0x90)], 2 * done);
    assert_eq!((f.read(0, 2 * done), f.read(1, 2 * done)), (0xBF, 0xB5));
    cmd(&mut f, &[(0, 0xF0)], 2 * done);
    assert_eq!(f.read(0, 2 * done), 0xFF);
    // a sector erase: the 4 KB around the address
    f.data[0x1FFF] = 0;
    cmd(&mut f, &unlock, 2 * done);
    cmd(
        &mut f,
        &[
            (0x5555, 0x80),
            (0x5555, 0xAA),
            (0x2AAA, 0x55),
            (0x0100, 0x30),
        ],
        2 * done,
    );
    let after = 2 * done + (25_001.0 * US) as u64;
    assert_eq!(f.read(0x123, after), 0xFF);
    assert_eq!(f.read(0x1FFF, after), 0, "the next sector");
    // a wrong sequence does nothing
    cmd(
        &mut f,
        &[
            (0x5555, 0xAA),
            (0x2AAB, 0x55),
            (0x5555, 0xA0),
            (0x1FFF, 0xFF),
        ],
        after,
    );
    assert_eq!(f.read(0x1FFF, after + 1), 0);
}

#[test]
fn palette() {
    let mut p = Palette::default();
    p.write(0, 5);
    for v in [63, 32, 0, 1, 2, 3] {
        p.write(1, v);
    }
    assert_eq!(p.rgb[5], [63, 32, 0]);
    assert_eq!(p.rgb[6], [1, 2, 3]);
    assert_eq!(p.colour(5), 0xFF_82_00);
    p.write(3, 6);
    assert_eq!([p.read(1), p.read(1), p.read(1)], [1, 2, 3]);
    p.write(2, 0x0F);
    assert_eq!(p.colour(0x15), p.colour(5), "the pixel mask");
}

/// A port's device sends a byte; the GAL's E at each fall, the data
/// sampled then: the byte, its parity and stop bit.
#[test]
fn ps2_device_to_host() {
    let mut p = Port::new(Kind::Keyboard, US, 50.0);
    p.push(&[0x1C], 0);
    let mut bits = Vec::new();
    let mut t = 0;
    while bits.len() < 11 && t < (2000.0 * US) as u64 {
        t += 10;
        p.advance(t);
        if p.e {
            bits.push(p.read() & 1);
            p.take_edge();
        }
    }
    let frame: u16 = bits.iter().enumerate().map(|(i, &b)| b << i).sum();
    // 0x1C has three ones: the odd parity bit is 0
    assert_eq!(frame, 0x1C << 1 | 1 << 10, "start, data, odd parity, stop");
}

/// The host sends a byte by holding the clock, pulling the data and
/// letting go; it puts each bit on as the clock falls. The device acks
/// and answers.
#[test]
fn ps2_host_to_device() {
    let mut p = Port::new(Kind::Mouse, US, 0.0);
    let byte = 0xF4u8;
    let frame: u16 = byte as u16 | ((byte.count_ones() & 1 == 0) as u16) << 8 | 1 << 9;
    let mut t = 100;
    p.write_control(16, t); // the clock low
    t += (120.0 * US) as u64;
    p.write_control(16 | 32, t); // and the data
    t += 100;
    p.write_control(32, t); // the clock let go: a request to send
    let (mut bit, mut acked) = (0, false);
    let mut clk = true;
    while t < (5000.0 * US) as u64 {
        t += 10;
        p.advance(t);
        let c = p.clk_line();
        if clk && !c {
            if bit < 10 {
                let pull = frame >> bit & 1 == 0;
                p.write_control(if pull { 32 } else { 0 }, t);
                bit += 1;
            } else if !p.data_line() {
                acked = true;
            }
        }
        clk = c;
    }
    assert!(acked, "the ack");
    assert_eq!(p.received, vec![0xF4]);
    assert!(p.reporting);
    assert_eq!(p.queue.front(), None, "the ack (FA) sent");
}

#[test]
fn video_timing() {
    let mut v = Video::new();
    let ram = vec![0u8; 0x20_0000];
    v.write_control(4, 0, &ram); // the frame interrupt on
    // the scanline: U_LINE's count, 0-12 again in the blank's last lines
    v.advance(LINE_TICKS * 479, &ram);
    assert_eq!((v.frame_line(), v.scanline()), (479, 479));
    assert!(!v.irq());
    v.advance(LINE_TICKS * 481, &ram);
    assert!(v.irq(), "the frame interrupt at line 481");
    v.write_control(4, LINE_TICKS * 481, &ram);
    assert!(!v.irq(), "acknowledged");
    v.advance(LINE_TICKS * 515, &ram);
    assert_eq!((v.frame_line(), v.scanline()), (515, 3));
    v.write_target(0x8000 | 3);
    assert!(v.copreq());
    v.advance(LINE_TICKS * LINES, &ram);
    assert_eq!(v.frame_count, 1);
    assert!(!v.copreq());
}

/// Phase F's reads with the display on: the shifter takes a word each 8
/// ticks while a line is shown. Short cycles keep the buffer full once it
/// has filled; longer ones empty it, and F stretches to read two; past 14
/// ticks even two a cycle aren't enough.
#[test]
fn video_buffer() {
    let ram = vec![0u8; 0x20_0000];
    for (cycle, stretched, starved) in [(6, false, false), (12, true, false), (16, true, true)] {
        let mut v = Video::new();
        v.write_control(2, 0, &ram);
        let mut t = 0;
        let mut extra = 0;
        while t < LINE_TICKS * 10 {
            let x = v.phase_f(t);
            if t >= LINE_TICKS {
                extra += x;
            }
            t += cycle + x;
            v.advance(t, &ram);
        }
        assert_eq!(extra > 0, stretched, "cycles of {cycle} ticks");
        assert_eq!(v.underflows > 0, starved, "cycles of {cycle} ticks");
    }
}

/// A store of three words: 0 goes to 1, 1 to 2, 2 is the stopped
/// machine's (a loop on itself).
fn tiny_store() -> Store {
    let mut s = Store {
        words: vec![Word::nop(0); WORDS],
        aops: [[Aop::new(0b1111, true, Carry::Zero); 2]; 32],
        imm: vec![[0; 3]; 32 * 256],
        entry_base: 0x100,
        task_base: 0x1F80,
        device_base: 0x1F80,
        copper_base: 0x1FC0,
        nochk: 0x1000,
    };
    s.set_word(0, Word::nop(1));
    s.set_word(1, Word::nop(2));
    let mut stop = Word::nop(2);
    stop.halt = true;
    stop.cond = Cond::Odt;
    stop.jt = 2; // ODT asked for: 3, else itself
    s.set_word(2, stop);
    s.set_word(3, Word::nop(3));
    s
}

#[test]
fn run_and_stop() {
    let mut m = Machine::new(tiny_store(), Config::default());
    assert_eq!(m.run(u64::MAX, 100), Ok(Status::Halted));
    // three cycles of F (3 ticks), a TCHG-free low half of 2
    assert_eq!((m.cpu.cycles, m.cpu.ticks), (3, 15));
    assert!(m.stopped());
    // stopped, it waits, skipping ahead
    m.stop_on_halt = false;
    let until = 1_000_000;
    assert_eq!(m.run(until, u64::MAX), Ok(Status::Limit));
    assert!(m.cpu.ticks >= until && m.cpu.ticks < until + 5);
    assert_eq!(m.cpu.ticks, 5 * m.cpu.cycles);
    assert!(m.skipped > 0);
    // the halt button: on to word 3
    m.press_halt();
    m.run(m.cpu.ticks + 20, u64::MAX).unwrap();
    assert_eq!(m.cpu.upc, 3);
}
