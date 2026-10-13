//! The 74181 model against the datasheet, alone and as four 181s with a
//! 182 for the carries.

use hwsim::models::alu181;
use hwsim::rng::Rng;

/// Logic-mode functions (M=1) from the 74181 datasheet, active-high data.
const LOGIC: [fn(u8, u8) -> u8; 16] = [
    |a, _| !a,       // 0000
    |a, b| !(a | b), // 0001
    |a, b| !a & b,   // 0010
    |_, _| 0,        // 0011
    |a, b| !(a & b), // 0100
    |_, b| !b,       // 0101
    |a, b| a ^ b,    // 0110
    |a, b| a & !b,   // 0111
    |a, b| !a | b,   // 1000
    |a, b| !(a ^ b), // 1001
    |_, b| b,        // 1010
    |a, b| a & b,    // 1011
    |_, _| 15,       // 1100
    |a, b| a | !b,   // 1101
    |a, b| a | b,    // 1110
    |a, _| a,        // 1111
];

#[test]
fn logic_mode() {
    for s in 0..16u8 {
        for a in 0..16u8 {
            for b in 0..16u8 {
                for cn in 0..2 {
                    let f = alu181(a, b, s, 1, cn).f;
                    assert_eq!(f, LOGIC[s as usize](a, b) & 15, "S={s:04b} a={a:X} b={b:X}");
                }
            }
        }
    }
}

#[test]
fn arithmetic_mode() {
    for a in 0..16u32 {
        for b in 0..16u32 {
            for carry in 0..2u32 {
                let cn = (carry ^ 1) as u8; // CN is an active-low carry
                let o = alu181(a as u8, b as u8, 0b1001, 0, cn);
                let sum = a + b + carry;
                assert_eq!(
                    (o.f as u32, (o.cn4 ^ 1) as u32),
                    (sum & 15, sum >> 4),
                    "{a:X}+{b:X}+{carry}"
                );
                let o = alu181(a as u8, b as u8, 0b0110, 0, cn);
                let diff = a + (!b & 15) + carry; // A minus B minus 1, plus carry
                assert_eq!(
                    (o.f as u32, (o.cn4 ^ 1) as u32),
                    (diff & 15, diff >> 4),
                    "{a:X}-{b:X} carry {carry}"
                );
            }
            // datasheet entries with no carry: F=A, F=A-1, F=A+A
            assert_eq!(alu181(a as u8, b as u8, 0b0000, 0, 1).f as u32, a);
            assert_eq!(
                alu181(a as u8, b as u8, 0b1111, 0, 1).f as u32,
                a.wrapping_sub(1) & 15
            );
            assert_eq!(
                alu181(a as u8, b as u8, 0b1100, 0, 1).f as u32,
                (2 * a) & 15
            );
        }
    }
}

/// A 16-bit ALU: four 181s with a 182 computing the carries between them,
/// as draft 0 wires them. Returns (F, carry out).
fn alu16(a: u16, b: u16, s: u8, m: u8, carry_in: u8) -> (u16, u8) {
    let nib = |x: u16, k: usize| ((x >> (4 * k)) & 15) as u8;
    let cn = carry_in ^ 1;
    let (mut p, mut g) = ([0u8; 4], [0u8; 4]);
    for k in 0..4 {
        let o = alu181(nib(a, k), nib(b, k), s, m, 1);
        (p[k], g[k]) = (o.p, o.g);
    }
    let mut c = [cn; 4];
    let mut c0 = cn ^ 1;
    for k in 0..3 {
        c0 = (g[k] ^ 1) | ((p[k] ^ 1) & c0);
        c[k + 1] = c0 ^ 1;
    }
    let (mut f, mut cout) = (0u16, 0);
    for (k, &ck) in c.iter().enumerate() {
        let o = alu181(nib(a, k), nib(b, k), s, m, ck);
        f |= (o.f as u16) << (4 * k);
        cout = o.cn4;
    }
    (f, cout ^ 1)
}

#[test]
fn sixteen_bits_with_lookahead() {
    let mut rng = Rng::new(7);
    for _ in 0..200_000 {
        let (a, b, ci) = (rng.next_u64() as u16, rng.next_u64() as u16, rng.bit());
        let sum = a as u32 + b as u32 + ci as u32;
        assert_eq!(
            alu16(a, b, 0b1001, 0, ci),
            (sum as u16, (sum >> 16) as u8),
            "{a:04X}+{b:04X}+{ci}"
        );
        let diff = a as u32 + (!b) as u32 + ci as u32;
        assert_eq!(
            alu16(a, b, 0b0110, 0, ci),
            (diff as u16, (diff >> 16) as u8),
            "{a:04X}-{b:04X} c{ci}"
        );
    }
}
