//! The 82C54 model against the datasheet's mode descriptions, and
//! `clock_n` against one pulse at a time.

use devices::i8254::Timer;

const CTRL: u8 = 3;

/// Program counter `c` for `mode`, LSB then MSB, and write `count`.
fn setup(t: &mut Timer, c: usize, mode: u8, bcd: bool, count: u16) {
    t.write(CTRL, ((c as u8) << 6) | 0x30 | (mode << 1) | bcd as u8);
    t.write(c as u8, count as u8);
    t.write(c as u8, (count >> 8) as u8);
}

/// OUT after each of `n` pulses.
fn trace(t: &mut Timer, c: usize, n: usize) -> Vec<bool> {
    (0..n)
        .map(|_| {
            t.clock(c);
            t.out(c)
        })
        .collect()
}

fn bits(s: &str) -> Vec<bool> {
    s.chars().filter(|&c| c != ' ').map(|c| c == '1').collect()
}

fn read16(t: &mut Timer, c: u8) -> u16 {
    let lo = t.read(c) as u16;
    lo | (t.read(c) as u16) << 8
}

#[test]
fn mode0_interrupt_on_terminal_count() {
    let mut t = Timer::new();
    setup(&mut t, 0, 0, false, 3);
    assert!(!t.out(0));
    // loaded on the first pulse, high N+1 pulses after the write, and it
    // stays high as the count wraps
    assert_eq!(trace(&mut t, 0, 8), bits("0001 1111"));
    // a new count sets OUT low at once
    t.write(0, 2);
    assert!(!t.out(0));
    t.write(0, 0);
    assert_eq!(trace(&mut t, 0, 4), bits("0011"));
}

#[test]
fn mode0_gate_and_two_byte_write() {
    let mut t = Timer::new();
    setup(&mut t, 1, 0, false, 4);
    t.clock(1); // load
    t.set_gate(1, false);
    assert_eq!(trace(&mut t, 1, 3), bits("000"));
    assert_eq!(read16(&mut t, 1), 4);
    t.set_gate(1, true);
    assert_eq!(trace(&mut t, 1, 4), bits("0001"));
    // the first byte of a new count stops counting and sets OUT low
    t.write(1, 2);
    assert!(!t.out(1));
    assert_eq!(trace(&mut t, 1, 5), bits("00000"));
    t.write(1, 0);
    assert_eq!(trace(&mut t, 1, 3), bits("001"));
}

#[test]
fn mode1_one_shot() {
    let mut t = Timer::new();
    t.set_gate(2, false);
    setup(&mut t, 2, 1, false, 3);
    assert!(t.out(2));
    // nothing without a trigger
    assert_eq!(trace(&mut t, 2, 4), bits("1111"));
    t.set_gate(2, true);
    assert_eq!(trace(&mut t, 2, 6), bits("0001 11"));
    // retriggered during the pulse: it starts again
    t.set_gate(2, false);
    t.set_gate(2, true);
    t.clock(2);
    t.clock(2);
    t.set_gate(2, false);
    t.set_gate(2, true);
    assert_eq!(trace(&mut t, 2, 5), bits("00011"));
    // a new count waits for the next trigger
    t.write(2, 5);
    t.write(2, 0);
    assert_eq!(trace(&mut t, 2, 3), bits("111"));
    t.set_gate(2, false);
    t.set_gate(2, true);
    assert_eq!(trace(&mut t, 2, 7), bits("00000 11"));
}

#[test]
fn mode2_rate_generator() {
    let mut t = Timer::new();
    setup(&mut t, 0, 2, false, 4);
    assert!(t.out(0));
    // low N pulses after the write, for one pulse, every N pulses
    assert_eq!(trace(&mut t, 0, 12), bits("1110 1110 1110"));
    // a new count takes effect at the end of the period
    t.clock(0);
    t.write(0, 3);
    t.write(0, 0);
    assert_eq!(trace(&mut t, 0, 9), bits("110 110 110"));
    // GATE low ends a low OUT at once and stops the count; going high
    // again reloads the count
    assert!(!t.out(0));
    t.set_gate(0, false);
    assert!(t.out(0));
    assert_eq!(trace(&mut t, 0, 4), bits("1111"));
    t.set_gate(0, true);
    assert_eq!(trace(&mut t, 0, 6), bits("1101 10"));
}

#[test]
fn mode3_square_wave() {
    let mut t = Timer::new();
    setup(&mut t, 0, 3, false, 6);
    // the high half starts with the pulse that loads the count
    assert_eq!(trace(&mut t, 0, 12), bits("111000 111000"));
    // odd counts: high (N+1)/2, low (N-1)/2
    setup(&mut t, 1, 3, false, 5);
    assert_eq!(trace(&mut t, 1, 10), bits("11100 11100"));
    setup(&mut t, 2, 3, false, 3);
    assert_eq!(trace(&mut t, 2, 6), bits("110 110"));
    // GATE low while OUT is low sets it high at once
    assert!(!t.out(2));
    t.set_gate(2, false);
    assert!(t.out(2));
    t.set_gate(2, true);
    assert_eq!(trace(&mut t, 2, 6), bits("110 110"));
}

#[test]
fn mode4_software_strobe() {
    let mut t = Timer::new();
    setup(&mut t, 0, 4, false, 3);
    assert!(t.out(0));
    // low for one pulse, N+1 pulses after the write, and only once
    assert_eq!(trace(&mut t, 0, 8), bits("1110 1111"));
    // GATE low pauses the count
    t.write(0, 2);
    t.write(0, 0);
    t.clock(0);
    t.set_gate(0, false);
    assert_eq!(trace(&mut t, 0, 3), bits("111"));
    t.set_gate(0, true);
    assert_eq!(trace(&mut t, 0, 3), bits("101"));
}

#[test]
fn mode5_hardware_strobe() {
    let mut t = Timer::new();
    t.set_gate(1, false);
    setup(&mut t, 1, 5, false, 2);
    assert_eq!(trace(&mut t, 1, 4), bits("1111"));
    t.set_gate(1, true);
    assert_eq!(trace(&mut t, 1, 6), bits("1101 11"));
    // retriggered before the strobe: N+1 pulses from the new trigger
    t.set_gate(1, false);
    t.set_gate(1, true);
    t.clock(1);
    t.set_gate(1, false);
    t.set_gate(1, true);
    assert_eq!(trace(&mut t, 1, 4), bits("1101"));
}

#[test]
fn bcd_counts() {
    let mut t = Timer::new();
    // 0x0012 in BCD is twelve
    setup(&mut t, 0, 0, true, 0x0012);
    let out = trace(&mut t, 0, 14);
    assert_eq!(out.iter().position(|&o| o), Some(12));
    assert_eq!(read16(&mut t, 0), 0x9999);
    t.clock(0);
    assert_eq!(read16(&mut t, 0), 0x9998);
    // 0 in BCD is ten thousand
    setup(&mut t, 1, 2, true, 0);
    t.clock(1);
    t.clock(1);
    assert_eq!(read16(&mut t, 1), 0x9999);
    assert_eq!(t.clock_n(1, 10_000 * 7), 7);
    assert_eq!(read16(&mut t, 1), 0x9999);
}

#[test]
fn latch_and_rw_modes() {
    let mut t = Timer::new();
    setup(&mut t, 0, 2, false, 0x1234);
    t.clock(0);
    t.write(CTRL, 0x00); // latch counter 0
    t.clock_n(0, 0x100);
    // a second latch before the read is ignored
    t.write(CTRL, 0x00);
    assert_eq!(read16(&mut t, 0), 0x1234);
    assert_eq!(read16(&mut t, 0), 0x1134);
    // LSB only (MSB is 0), and MSB only (LSB is 0)
    t.write(CTRL, 0x50); // counter 1, LSB, mode 0
    t.write(1, 0x20);
    t.clock(1);
    assert_eq!(t.read(1), 0x20);
    assert_eq!(t.read(1), 0x20);
    t.write(CTRL, 0x60); // counter 1, MSB, mode 0
    t.write(1, 0x02);
    t.clock(1);
    t.clock(1);
    assert_eq!(t.read(1), 0x01); // 0x01FF
    // the control register doesn't read
    assert_eq!(t.read(3), 0xFF);
}

#[test]
fn read_back() {
    let mut t = Timer::new();
    t.write(CTRL, 0xB2); // counter 2, LSB then MSB, mode 1, binary
    // status: OUT high, null count, the control bits
    t.write(CTRL, 0xE8); // read back status of counter 2
    assert_eq!(t.read(2), 0xC0 | 0x32);
    t.write(2, 10);
    t.write(2, 0);
    t.set_gate(2, false);
    t.set_gate(2, true);
    t.clock(2);
    t.clock(2);
    // count and status of counters 0 and 2: status comes first, then the
    // count, and a latched status isn't latched over
    t.write(CTRL, 0xCA);
    t.write(CTRL, 0xE8); // status of counter 2 again: ignored
    t.clock(2);
    assert_eq!(t.read(2), 0x32); // OUT low, count loaded
    assert_eq!(read16(&mut t, 2), 9);
    assert_eq!(read16(&mut t, 2), 8);
    // counter 0 was never programmed: mode 0, OUT low, null count
    assert_eq!(t.read(0), 0x40 | 0x30);
}

#[test]
fn control_word_sets_out() {
    let mut t = Timer::new();
    for mode in 0..8u8 {
        t.write(CTRL, 0x30 | (mode << 1));
        assert_eq!(t.out(0), mode != 0, "mode {mode}");
    }
}

/// SplitMix64.
struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
}

fn to_bcd(n: u64) -> u16 {
    let d = |p: u64| ((n / p) % 10) as u16;
    (d(1000) << 12) | (d(100) << 8) | (d(10) << 4) | d(1)
}

/// clock_n leaves the counter exactly as that many single pulses do, and
/// counts the same rising edges of OUT, in every mode, with gate changes
/// and new counts along the way.
#[test]
fn clock_n_matches_clock() {
    let mut rng = Rng(54);
    for round in 0..600 {
        let mode = rng.below(6) as u8;
        let bcd = rng.below(4) == 0;
        let count = |rng: &mut Rng| -> u16 {
            let n = match rng.below(10) {
                0 => 0,
                1 => 1,
                2..=7 => rng.below(40),
                _ => rng.below(400),
            };
            if bcd { to_bcd(n) } else { n as u16 }
        };
        let mut a = Timer::new();
        a.set_gate(0, rng.below(4) != 0);
        let c = count(&mut rng);
        setup(&mut a, 0, mode, bcd, c);
        let mut b = a.clone();
        for _ in 0..12 {
            let n = match rng.below(4) {
                0 => rng.below(4),
                1 | 2 => rng.below(200),
                _ => rng.below(25_000),
            };
            let rises = a.clock_n(0, n);
            let mut seen = 0;
            for _ in 0..n {
                let was = b.out(0);
                b.clock(0);
                seen += (!was && b.out(0)) as u64;
            }
            assert_eq!(rises, seen, "round {round} mode {mode} count {c:#x}");
            assert_eq!(a, b, "round {round} mode {mode} count {c:#x} n {n}");
            match rng.below(6) {
                0 => {
                    let g = rng.below(2) == 1;
                    a.set_gate(0, g);
                    b.set_gate(0, g);
                }
                1 => {
                    let c = count(&mut rng);
                    for t in [&mut a, &mut b] {
                        t.write(0, c as u8);
                        t.write(0, (c >> 8) as u8);
                    }
                }
                2 => {
                    // half a two-byte count
                    let v = rng.below(256) as u8;
                    a.write(0, v);
                    b.write(0, v);
                }
                _ => {}
            }
        }
    }
}

/// clock_n takes no longer for a year of pulses than for a few.
#[test]
fn clock_n_is_fast() {
    let mut t = Timer::new();
    setup(&mut t, 0, 2, false, 2);
    let n = 1u64 << 50;
    // loaded on the first pulse, then a rise every 2
    assert_eq!(t.clock_n(0, n), (n - 1) / 2);
    setup(&mut t, 1, 3, false, 7);
    assert_eq!(t.clock_n(1, 1 + 7 * n), n);
    assert!(t.out(1));
    setup(&mut t, 2, 0, false, 5);
    assert_eq!(t.clock_n(2, n), 1);
    assert!(t.out(2));
}
