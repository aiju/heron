//! Chibi Heron's whole-machine simulator (RFC 0047): the two-halves
//! machine's microcode run a microinstruction at a time, exactly as the
//! register-transfer model (studies/chibi/rtl2.py) runs it, on a board
//! with every device the netlist (board2.py) has: the RAM, the boot flash,
//! both UARTs, the interrupt controller and its buttons, the video with its
//! palette, scanline and frame interrupt, the PS/2 ports at the lines, the
//! 82C54 and the PCM's DAC, the CompactFlash card, and the suite's test
//! fixture.
//!
//! The microcode is the study's own: Python builds the control store
//! (routines2.py, flat.py) and hands it over as an image ([`store`]), so
//! the copper, the device task, ODT, reset and the boot run as the board
//! runs them, and a change to the microcode needs nothing here. Time is
//! the master clock's ticks, as the clock generator gives them.
//!
//! Speed: tens of millions of microinstructions a second, several times
//! the board's own 7-8 million; a machine waiting in HALT, or stopped,
//! skips ahead to the next thing a device does.

pub mod audio;
pub mod board;
pub mod cpu;
pub mod fixture;
pub mod flash;
pub mod ps2;
pub mod store;
pub mod video;

use std::collections::{HashMap, HashSet};

pub use board::{Board, Config};
pub use cpu::{Cpu, Owner};
pub use store::Store;

/// Why [`Machine::run`] returned.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    /// The tick or cycle limit.
    Limit,
    /// The machine stopped (HALT with interrupts off), with `stop_on_halt`.
    Halted,
    /// An instruction at a breakpoint is about to run.
    Breakpoint,
}

/// Where the time went: ticks and runs of each control store word, and
/// ticks and executions by instruction address and by task.
#[derive(Clone, Debug, Default)]
pub struct Profile {
    pub word_cycles: Vec<u64>,
    pub word_ticks: Vec<u64>,
    /// instruction address -> (executions, ticks)
    pub insns: HashMap<u32, (u64, u64)>,
    pub device_task: (u64, u64),
    pub copper: (u64, u64),
}

pub struct Machine {
    pub cpu: Cpu,
    pub board: Board,
    pub store: Store,
    /// Stop when the machine stops (rtl2.py's runs do).
    pub stop_on_halt: bool,
    /// Skip a word's repeats while it only waits (HALT's wait, the stopped
    /// machine) and nothing is due.
    pub skip_idle: bool,
    pub breakpoints: HashSet<u32>,
    pub profile: Option<Profile>,
    /// Every decode: (its cycle, the tick it ends at, the instruction's
    /// address, its first parcel), up to the limit.
    pub decodes: Option<Vec<(u64, u64, u32, u16)>>,
    pub decode_limit: usize,
    /// Cycles skipped in idle waits.
    pub skipped: u64,
    last_addr: usize,
}

impl Machine {
    /// A machine at power-on: the CPU at µPC 0 (the reset routine), the
    /// RAM clear, the boot flash blank.
    pub fn new(store: Store, cfg: Config) -> Machine {
        Machine {
            cpu: Cpu::new(),
            board: Board::new(cfg),
            store,
            stop_on_halt: true,
            skip_idle: true,
            breakpoints: HashSet::new(),
            profile: None,
            decodes: None,
            decode_limit: 1 << 20,
            skipped: 0,
            last_addr: usize::MAX,
        }
    }

    /// The reset button: the sequencer, the flags and the devices' reset
    /// (RAM, the register file and the boot flash keep their contents).
    pub fn reset(&mut self) {
        self.cpu.reset();
        self.board.reset(self.cpu.ticks);
        self.last_addr = usize::MAX;
    }

    /// Whether the machine is stopped: at the word of HALT with interrupts
    /// off.
    pub fn stopped(&self) -> bool {
        !self.cpu.task && self.store.words[self.cpu.address(&self.store)].halt
    }

    /// Put bytes in RAM (the address wraps at 2 MB).
    pub fn load(&mut self, addr: u32, bytes: &[u8]) {
        for (i, &b) in bytes.iter().enumerate() {
            self.board.ram[(addr as usize + i) % board::RAM_SIZE] = b;
        }
    }

    /// Run until the tick count reaches `until`, the cycle count
    /// `max_cycles`, the machine stops (with `stop_on_halt`), or a
    /// breakpoint.
    pub fn run(&mut self, until: u64, max_cycles: u64) -> Result<Status, String> {
        loop {
            if self.cpu.ticks >= until || self.cpu.cycles >= max_cycles {
                return Ok(Status::Limit);
            }
            let a = self.cpu.address(&self.store);
            let (idle, halt) = (self.store.words[a].idle, self.store.words[a].halt);
            if idle && self.skip_idle && a == self.last_addr {
                self.skip(a, until, max_cycles);
                if self.cpu.ticks >= until || self.cpu.cycles >= max_cycles {
                    return Ok(Status::Limit);
                }
            }
            let halt = halt && !self.cpu.task;
            let t = self.cpu.ticks;
            let (task, owner_pc) = (self.cpu.task, self.cpu.insn_pc);
            let insns = self.cpu.instructions;
            self.cpu.cycle(&self.store, &mut self.board)?;
            self.board.end_cycle(self.cpu.ticks);
            self.last_addr = a;
            if self.profile.is_some() || self.decodes.is_some() || !self.breakpoints.is_empty() {
                let new_insn = self.cpu.instructions != insns;
                self.note(a, t, task, owner_pc, new_insn);
                // (decoded: it runs from the next cycle on)
                if new_insn && self.breakpoints.contains(&self.cpu.insn_pc) {
                    return Ok(Status::Breakpoint);
                }
            }
            if halt && self.stop_on_halt {
                return Ok(Status::Halted);
            }
        }
    }

    /// The bookkeeping of a cycle at word `a` that started at tick `t`.
    fn note(&mut self, a: usize, t: u64, task: bool, owner_pc: u32, new_insn: bool) {
        let dt = self.cpu.ticks - t;
        if let Some(p) = &mut self.profile {
            if p.word_cycles.is_empty() {
                p.word_cycles = vec![0; store::WORDS];
                p.word_ticks = vec![0; store::WORDS];
            }
            p.word_cycles[a] += 1;
            p.word_ticks[a] += dt;
            let e = if task {
                match self.cpu.task_owner {
                    Owner::Copper => &mut p.copper,
                    _ => &mut p.device_task,
                }
            } else {
                p.insns.entry(owner_pc).or_insert((0, 0))
            };
            e.1 += dt;
            if new_insn {
                p.insns.entry(self.cpu.insn_pc).or_insert((0, 0)).0 += 1;
            }
        }
        if new_insn
            && let Some(d) = &mut self.decodes
            && d.len() < self.decode_limit
        {
            let pc = self.cpu.insn_pc;
            let i = pc as usize & (board::RAM_SIZE - 2);
            let parcel = u16::from_le_bytes([self.board.ram[i], self.board.ram[i + 1]]);
            d.push((self.cpu.cycles - 1, self.cpu.ticks, pc, parcel));
        }
    }

    /// Repeats of the waiting word at `a` that would change nothing but
    /// the time, up to the next thing due: skipped.
    fn skip(&mut self, a: usize, until: u64, max_cycles: u64) {
        if self.board.cfg.stretch && self.board.video_active() {
            return;
        }
        // it waits on, and IRQP is as the lines have it (else it changes
        // at this cycle's end)
        let irqp = (self.board.irq() && self.cpu.f.i) || self.board.odt_req();
        if self.cpu.f.irqp != irqp
            || !self
                .cpu
                .jumps_to_itself(&self.store.words[a], a, &self.board)
        {
            return;
        }
        let w = &self.store.words[a];
        let period = 3 + w.len as u64 + w.hlen as u64;
        let horizon = self.board.next_event.min(until);
        if horizon <= self.cpu.ticks + period {
            return;
        }
        let mut k = (horizon - self.cpu.ticks) / period - 1;
        k = k.min(max_cycles.saturating_sub(self.cpu.cycles + 1));
        if self.board.cfg.fixture
            && let Some(c) = self.board.fixture.cycles_to_flag()
        {
            k = k.min(c.saturating_sub(1));
        }
        if k == 0 {
            return;
        }
        self.cpu.cycles += k;
        self.cpu.ticks += k * period;
        self.skipped += k;
        if self.board.cfg.fixture {
            self.board.fixture.ticks(k);
        }
        if let Some(p) = &mut self.profile
            && !p.word_cycles.is_empty()
        {
            p.word_cycles[a] += k;
            p.word_ticks[a] += k * period;
            p.insns.entry(self.cpu.insn_pc).or_insert((0, 0)).1 += k * period;
        }
    }

    // ---- from outside

    /// A key down or up on the keyboard, by its set 2 code.
    pub fn key(&mut self, code: u16, down: bool) {
        let t = self.cpu.ticks;
        self.board.sync(t);
        self.board.ps2[0].key(code, down, t);
        self.board.poke(t);
    }

    /// Bytes the keyboard (0) or the mouse (1) sends, as they are.
    pub fn ps2_send(&mut self, port: usize, bytes: &[u8]) {
        let t = self.cpu.ticks;
        self.board.sync(t);
        self.board.ps2[port].push(bytes, t);
        self.board.poke(t);
    }

    /// The mouse moved by (dx, dy), y up, with `buttons` held.
    pub fn mouse(&mut self, dx: i32, dy: i32, buttons: u8) {
        let t = self.cpu.ticks;
        self.board.sync(t);
        self.board.ps2[1].mouse(dx, dy, buttons, t);
        self.board.poke(t);
    }

    /// Bytes typed at UART `port`'s terminal.
    pub fn uart_send(&mut self, port: usize, bytes: &[u8]) {
        let t = self.cpu.ticks;
        self.board.sync(t);
        self.board.uart[port].rx_in.extend(bytes.iter().copied());
        self.board.poke(t);
    }

    /// What UART `port` has sent since the last call.
    pub fn uart_take(&mut self, port: usize) -> Vec<u8> {
        std::mem::take(&mut self.board.uart[port].tx_out)
    }

    pub fn press_halt(&mut self) {
        self.board.press_halt();
    }

    pub fn press_interrupt(&mut self) {
        self.board.press_interrupt();
    }

    /// Record the sound from now on (or stop).
    pub fn record_audio(&mut self, on: bool) {
        let t = self.cpu.ticks;
        self.board.sync(t);
        self.board.audio.record(on, t);
        self.board.poke(t);
    }

    /// The sound since the last call, at `rate` Hz.
    pub fn audio_take(&mut self, rate: f64) -> Vec<i16> {
        let t = self.cpu.ticks;
        self.board.poke(t);
        self.board
            .audio
            .take(t, rate, board::TICK_PS as f64 * 1e-12)
    }

    /// The machine's time in seconds.
    pub fn seconds(&self) -> f64 {
        self.cpu.ticks as f64 * board::TICK_PS as f64 * 1e-12
    }

    /// The ticks of `s` seconds.
    pub fn ticks_of(s: f64) -> u64 {
        (s / (board::TICK_PS as f64 * 1e-12)).round() as u64
    }
}
