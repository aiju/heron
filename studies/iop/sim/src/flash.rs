//! The image flash (RFC 0027, 5, device 13): two SST39SF040, 512K x 8
//! each, side by side as 512K x 16. Each chip has its own command state
//! machine, as on the board, so a command must be written to both halves
//! (0xAAAA, 0x5555, ...) to reach both.
//!
//! What a chip does, from its datasheet:
//! - **read** at any time it isn't busy;
//! - **byte program:** 5555h <- AAh, 2AAAh <- 55h, 5555h <- A0h, then the
//!   address <- the data. It only clears bits. 14-20 us;
//! - **sector erase:** 5555h <- AAh, 2AAAh <- 55h, 5555h <- 80h, 5555h <-
//!   AAh, 2AAAh <- 55h, then any address in the 4 KB sector <- 30h. 18-25
//!   ms; **chip erase:** the same with 5555h <- 10h. 70-100 ms;
//! - **software ID:** 5555h <- AAh, 2AAAh <- 55h, 5555h <- 90h; then reads
//!   give the maker (BFh at 0) and the device (B7h at 1) until F0h;
//! - **while busy,** a read gives DQ7 the complement of the data being
//!   programmed (0 during an erase: data# polling) and DQ6 toggling on every
//!   read; the rest is undefined (here 0).
//!
//! The command addresses are A14-A0, so the page register's bits matter
//! for them. Times here are the datasheet's maximums. A command sequence
//! broken by any other write goes back to reading.

const PROGRAM_NS: u64 = 20_000;
const SECTOR_ERASE_NS: u64 = 25_000_000;
const CHIP_ERASE_NS: u64 = 100_000_000;
const CHIP_BYTES: usize = 512 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum State {
    Read,
    /// The number of unlock cycles seen: 1 after AAh, 2 after 55h.
    Unlock(u8),
    Program,
    /// After 80h: the second unlock, 0-2 cycles of it.
    Erase(u8),
    Id,
}

#[derive(Clone, Debug)]
struct Chip {
    state: State,
    /// Busy until this time, and DQ7's value while busy.
    busy_until: u64,
    busy_dq7: u8,
    toggle: u8,
}

impl Chip {
    fn new() -> Chip {
        Chip {
            state: State::Read,
            busy_until: 0,
            busy_dq7: 0,
            toggle: 0,
        }
    }
}

/// The two chips, and their contents as halfwords (the even byte, D0-D7,
/// is the low chip).
#[derive(Clone, Debug)]
pub struct Flash {
    pub data: Vec<u16>,
    chips: [Chip; 2],
}

impl Flash {
    /// A flash holding `image` (bytes, little-endian halfwords) from 0, and
    /// erased (all ones) after it.
    pub fn new(image: &[u8]) -> Flash {
        let mut data = vec![0xFFFF; CHIP_BYTES];
        for (i, c) in image.chunks(2).take(CHIP_BYTES).enumerate() {
            data[i] = c[0] as u16 | (*c.get(1).unwrap_or(&0xFF) as u16) << 8;
        }
        Flash {
            data,
            chips: [Chip::new(), Chip::new()],
        }
    }

    /// The contents as bytes.
    pub fn bytes(&self) -> Vec<u8> {
        self.data.iter().flat_map(|h| h.to_le_bytes()).collect()
    }

    fn byte(&self, a: usize, lane: usize) -> u8 {
        (self.data[a] >> (8 * lane)) as u8
    }

    /// Read the halfword at address `a` (19 bits) at time `now_ns`.
    pub fn read(&mut self, a: u32, now_ns: u64) -> u16 {
        let a = a as usize & (CHIP_BYTES - 1);
        let mut out = 0u16;
        for lane in 0..2 {
            let byte = self.byte(a, lane);
            let c = &mut self.chips[lane];
            let v = if now_ns < c.busy_until {
                c.toggle ^= 0x40;
                c.busy_dq7 | c.toggle
            } else {
                match c.state {
                    State::Id => match a & 1 {
                        0 => 0xBF,
                        _ => 0xB7,
                    },
                    _ => byte,
                }
            };
            out |= (v as u16) << (8 * lane);
        }
        out
    }

    /// Write the halfword `v` at address `a` (19 bits) at time `now_ns`.
    pub fn write(&mut self, a: u32, v: u16, now_ns: u64) {
        let a = a as usize & (CHIP_BYTES - 1);
        for lane in 0..2 {
            let d = (v >> (8 * lane)) as u8;
            let cmd = a & 0x7FFF;
            let busy = now_ns < self.chips[lane].busy_until;
            if busy {
                // ignored while busy
                continue;
            }
            let state = self.chips[lane].state;
            let next = match (state, cmd, d) {
                (_, _, 0xF0) if !matches!(state, State::Program) => State::Read,
                (State::Read | State::Id, 0x5555, 0xAA) => State::Unlock(1),
                (State::Unlock(1), 0x2AAA, 0x55) => State::Unlock(2),
                (State::Unlock(2), 0x5555, 0xA0) => State::Program,
                (State::Unlock(2), 0x5555, 0x90) => State::Id,
                (State::Unlock(2), 0x5555, 0x80) => State::Erase(0),
                (State::Erase(0), 0x5555, 0xAA) => State::Erase(1),
                (State::Erase(1), 0x2AAA, 0x55) => State::Erase(2),
                (State::Erase(2), 0x5555, 0x10) => {
                    for h in self.data.iter_mut() {
                        *h |= 0xFF << (8 * lane);
                    }
                    self.busy(lane, now_ns + CHIP_ERASE_NS, 0);
                    State::Read
                }
                (State::Erase(2), _, 0x30) => {
                    let first = a & !0xFFF;
                    for h in &mut self.data[first..first + 0x1000] {
                        *h |= 0xFF << (8 * lane);
                    }
                    self.busy(lane, now_ns + SECTOR_ERASE_NS, 0);
                    State::Read
                }
                (State::Program, _, _) => {
                    let old = self.byte(a, lane);
                    let new = old & d;
                    self.data[a] =
                        (self.data[a] & !(0xFF << (8 * lane))) | (new as u16) << (8 * lane);
                    self.busy(lane, now_ns + PROGRAM_NS, !d & 0x80);
                    State::Read
                }
                _ => State::Read,
            };
            self.chips[lane].state = next;
        }
    }

    fn busy(&mut self, lane: usize, until: u64, dq7: u8) {
        let c = &mut self.chips[lane];
        c.busy_until = until;
        c.busy_dq7 = dq7;
        c.toggle = 0;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cmd(f: &mut Flash, seq: &[(u32, u16)], t: u64) {
        for &(a, v) in seq {
            f.write(a, v, t);
        }
    }

    #[test]
    fn program_and_erase() {
        let mut f = Flash::new(&[0x34, 0x12]);
        assert_eq!(f.read(0, 0), 0x1234);
        assert_eq!(f.read(1, 0), 0xFFFF);
        cmd(
            &mut f,
            &[
                (0x5555, 0xAAAA),
                (0x2AAA, 0x5555),
                (0x5555, 0xA0A0),
                (7, 0x0F0F),
            ],
            0,
        );
        // busy: DQ7 is the complement, DQ6 toggles
        let a = f.read(7, 1000);
        let b = f.read(7, 1001);
        assert_eq!(a & 0x8080, 0x8080);
        assert_eq!((a ^ b) & 0x4040, 0x4040);
        assert_eq!(f.read(7, 30_000), 0x0F0F);
        // programming only clears bits
        cmd(
            &mut f,
            &[
                (0x5555, 0xAAAA),
                (0x2AAA, 0x5555),
                (0x5555, 0xA0A0),
                (7, 0xF0F0),
            ],
            40_000,
        );
        assert_eq!(f.read(7, 80_000), 0);
        // one lane only
        cmd(
            &mut f,
            &[
                (0x5555, 0x00AA),
                (0x2AAA, 0x0055),
                (0x5555, 0x00A0),
                (1, 0x0000),
            ],
            100_000,
        );
        assert_eq!(f.read(1, 200_000), 0xFF00);
        // a sector erase
        let s = [(0x5555, 0xAAAA), (0x2AAA, 0x5555), (0x5555, 0x8080)];
        cmd(&mut f, &s, 300_000);
        cmd(
            &mut f,
            &[(0x5555, 0xAAAA), (0x2AAA, 0x5555), (0x10, 0x3030)],
            300_000,
        );
        assert_eq!(f.read(7, 300_001) & 0x8080, 0);
        assert_eq!(f.read(7, 30_000_000), 0xFFFF);
        assert_eq!(f.read(0, 30_000_000), 0xFFFF);
    }

    #[test]
    fn software_id() {
        let mut f = Flash::new(&[]);
        cmd(
            &mut f,
            &[(0x5555, 0xAAAA), (0x2AAA, 0x5555), (0x5555, 0x9090)],
            0,
        );
        assert_eq!(f.read(0, 1), 0xBFBF);
        assert_eq!(f.read(1, 1), 0xB7B7);
        f.write(0, 0xF0F0, 2);
        assert_eq!(f.read(0, 3), 0xFFFF);
    }
}
