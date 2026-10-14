//! The random power-on state of flip-flops and memories: SplitMix64, so a
//! seed gives the same state on every machine.

pub struct Rng(u64);

impl Rng {
    pub fn new(seed: i64) -> Rng {
        Rng(seed as u64)
    }

    pub fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    pub fn bit(&mut self) -> u8 {
        (self.next_u64() >> 63) as u8
    }

    pub fn byte(&mut self) -> u8 {
        (self.next_u64() >> 56) as u8
    }
}
