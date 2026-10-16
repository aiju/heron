//! The simulator behind the website's page (studies/websim): one of the
//! studies' machines, put together from a description and run by a
//! frontend in slices of time.
//!
//! A description names a board, gives it parameters and says what to load
//! where ([`Setup`]); what each board takes is in its module. The frontend
//! runs the machine a slice at a time ([`Session::run`]), gives it what's
//! typed at the terminal, the keys and the mouse, and takes what it
//! printed and its screen. The machines are the studies' own crates, so a
//! machine here is the one their tests run.
//!
//! | Board | The machine | Module |
//! |---|---|---|
//! | `plain` | draft 1 (1a, 1b) or draft 2 without a supervisor: 1 MB of RAM and the I/O page's console and timer (RFC 0004, 26) | [`plain`] |
//! | `fen` | draft 2 in system mode on Fen's board (studies/fen/board): RAM, the timer, the video card, the I/O card's UART, CF card and PS/2 ports | [`fen`] |
//!
//! Time is the machine's cycle count, at the clock the board says: the
//! frontend asks for so many cycles a slice, and runs slices as fast as
//! the clock (or a multiple of it) wants, or as fast as it can.

pub mod fen;
pub mod plain;

use std::collections::VecDeque;

/// How a slice of running ended.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    /// It ran its slice; there's more to do.
    Ran,
    /// It waits for the terminal, and does nothing until something is
    /// typed.
    Waiting,
    /// It sleeps in HALT with nothing on the board to wake it: only input
    /// from outside will.
    Idle,
    /// It stopped for good: HALT with interrupts off.
    Halted,
}

impl Status {
    pub fn name(self) -> &'static str {
        match self {
            Status::Ran => "ran",
            Status::Waiting => "waiting",
            Status::Idle => "idle",
            Status::Halted => "halted",
        }
    }
}

/// A machine and its board, as a frontend sees it. The defaults are for a
/// board without the thing.
pub trait Board: Send + Sync {
    /// Run until the cycle count reaches `until`, or for `steps`
    /// instructions, or until the machine waits, sleeps or halts.
    fn run(&mut self, until: u64, steps: u64) -> Result<Status, String>;
    fn cycles(&self) -> u64;
    fn instructions(&self) -> u64;
    /// The machine's clock, cycles a second.
    fn clock_hz(&self) -> f64;
    /// Cycles spent asleep in HALT.
    fn idle_cycles(&self) -> u64 {
        0
    }
    /// Bytes typed at the terminal.
    fn send(&mut self, bytes: &[u8]);
    /// The end of the terminal's input, where the board has one.
    fn close(&mut self) {}
    /// What the machine printed on the terminal since the last call.
    fn take_output(&mut self) -> Vec<u8>;
    /// What it wrote to a log beside the terminal (Fen's kernel log).
    fn take_log(&mut self) -> Vec<u8> {
        Vec::new()
    }
    /// The screen's size, if there is one.
    fn screen_size(&self) -> Option<(u32, u32)> {
        None
    }
    /// The screen as 0xRRGGBB pixels, row by row, if it changed since the
    /// last call (or `always`).
    fn screen(&mut self, _out: &mut Vec<u32>, _always: bool) -> bool {
        false
    }
    /// A key down or up, by the name a browser gives it
    /// (KeyboardEvent.code: "KeyA", "Enter"); false if there's no such key
    /// or no keyboard.
    fn key(&mut self, _name: &str, _down: bool) -> bool {
        false
    }
    /// Whether there's a mouse.
    fn has_mouse(&self) -> bool {
        false
    }
    /// The mouse moved by (dx, dy), y down, with `buttons` held (bit 0 the
    /// left one, 1 the right, 2 the middle).
    fn mouse(&mut self, _dx: i32, _dy: i32, _buttons: u8) {}
    /// The registers, by name, for a debugger.
    fn registers(&self) -> Vec<(String, u32)>;
    /// Bytes of RAM (physical), as far as there is RAM.
    fn peek(&self, addr: u32, len: u32) -> Vec<u8>;
}

/// What to load: bytes for a target the board knows ("ram", "console",
/// "cf"), at an address in it.
pub struct Load {
    pub target: String,
    pub at: u32,
    pub bytes: Vec<u8>,
}

/// A machine's description: its board, the board's parameters (as text:
/// numbers in decimal or with an exponent, names), and what to load.
pub struct Setup {
    pub board: String,
    pub params: Vec<(String, String)>,
    pub loads: Vec<Load>,
}

impl Setup {
    pub fn new(board: &str) -> Setup {
        Setup {
            board: board.into(),
            params: Vec::new(),
            loads: Vec::new(),
        }
    }

    pub fn param(&mut self, name: &str, value: &str) {
        self.params.retain(|(n, _)| n != name);
        self.params.push((name.into(), value.into()));
    }

    pub fn load(&mut self, target: &str, at: u32, bytes: Vec<u8>) {
        self.loads.push(Load {
            target: target.into(),
            at,
            bytes,
        });
    }

    /// The machine, at power-on.
    pub fn start(&self) -> Result<Session, String> {
        let mut p = Params::new(&self.params);
        let board: Box<dyn Board> = match self.board.as_str() {
            "plain" => Box::new(plain::Plain::new(&mut p, &self.loads)?),
            "fen" => Box::new(fen::Fen::new(&mut p, &self.loads)?),
            b => return Err(format!("no board {b:?}")),
        };
        p.finish(&self.board)?;
        Ok(Session::new(board))
    }
}

/// A board's parameters, each taken once; any left over is a mistake in
/// the description.
pub struct Params<'a> {
    list: &'a [(String, String)],
    used: Vec<bool>,
}

impl<'a> Params<'a> {
    fn new(list: &'a [(String, String)]) -> Params<'a> {
        Params {
            list,
            used: vec![false; list.len()],
        }
    }

    /// A parameter's text, if it's given.
    pub fn text(&mut self, name: &str) -> Option<&'a str> {
        let i = self.list.iter().position(|(n, _)| n == name)?;
        self.used[i] = true;
        Some(self.list[i].1.as_str())
    }

    /// A number: an integer, or anything f64 reads ("6e6").
    pub fn number(&mut self, name: &str) -> Result<Option<f64>, String> {
        let Some(t) = self.text(name) else {
            return Ok(None);
        };
        let t = t.trim();
        let v = match t.strip_prefix("0x") {
            Some(h) => u64::from_str_radix(h, 16).map(|v| v as f64).ok(),
            None => t.parse::<f64>().ok(),
        };
        match v {
            Some(v) if v.is_finite() => Ok(Some(v)),
            _ => Err(format!("{name}: not a number: {t:?}")),
        }
    }

    /// A whole number that fits in 32 bits.
    pub fn u32(&mut self, name: &str) -> Result<Option<u32>, String> {
        match self.number(name)? {
            Some(v) if v >= 0.0 && v <= u32::MAX as f64 && v.fract() == 0.0 => Ok(Some(v as u32)),
            Some(v) => Err(format!("{name}: not a 32-bit whole number: {v}")),
            None => Ok(None),
        }
    }

    fn finish(self, board: &str) -> Result<(), String> {
        let left: Vec<&str> = self
            .list
            .iter()
            .zip(&self.used)
            .filter(|(_, u)| !**u)
            .map(|((n, _), _)| n.as_str())
            .collect();
        if left.is_empty() {
            Ok(())
        } else {
            Err(format!("the {board} board takes no {}", left.join(", ")))
        }
    }
}

/// The most the mouse moves between two of its samples: a PS/2 mouse
/// reports at most 255 counts each way and drops the rest.
const MOUSE_STEP: i32 = 200;
/// Fen's window system asks for 40 samples a second.
const MOUSE_SLICE_NS: f64 = 25e6;

/// A running machine.
pub struct Session {
    board: Box<dyn Board>,
    /// Why it stopped, if it stopped with an error; it doesn't run again.
    error: Option<String>,
    /// Where the machine has the mouse (it starts it in the middle of the
    /// screen and keeps it on it) and the buttons it last had.
    mouse_at: (i32, i32),
    buttons: u8,
    /// Where the mouse is to go next, with which buttons, in order. Motion
    /// goes a sample's worth at a time, and a change of buttons gets a
    /// sample of its own, so a click quicker than a sample isn't lost.
    mouse_to: VecDeque<(i32, i32, u8)>,
    /// When the mouse may next be given motion: a sample's time after it
    /// last was.
    mouse_next: u64,
    pixels: Vec<u32>,
    rgba: Vec<u8>,
}

impl Session {
    /// A session on a board: one of this crate's, from [`Setup::start`],
    /// or any other.
    pub fn new(board: Box<dyn Board>) -> Session {
        let (w, h) = board.screen_size().unwrap_or((0, 0));
        Session {
            board,
            error: None,
            mouse_at: (w as i32 / 2, h as i32 / 2),
            buttons: 0,
            mouse_to: VecDeque::new(),
            mouse_next: 0,
            pixels: Vec::new(),
            rgba: Vec::new(),
        }
    }

    pub fn board(&mut self) -> &mut dyn Board {
        self.board.as_mut()
    }

    pub fn board_ref(&self) -> &dyn Board {
        self.board.as_ref()
    }

    pub fn error(&self) -> Option<&str> {
        self.error.as_deref()
    }

    /// Run for `cycles` more cycles or `steps` instructions, whichever
    /// comes first. While the mouse has somewhere to go, the slice is cut
    /// into the mouse's samples, each with its share of the motion.
    pub fn run(&mut self, cycles: u64, steps: u64) -> Result<Status, String> {
        if let Some(e) = &self.error {
            return Err(e.clone());
        }
        let until = self.board.cycles().saturating_add(cycles);
        let sample = (MOUSE_SLICE_NS * self.board.clock_hz() / 1e9).max(1.0) as u64;
        let mut left = steps;
        loop {
            let at = self.board.cycles();
            let mut to = until;
            if !self.mouse_to.is_empty() {
                if at >= self.mouse_next {
                    self.feed_mouse();
                    self.mouse_next = at.saturating_add(sample);
                }
                to = to.min(self.mouse_next);
            }
            let before = self.board.instructions();
            let status = self.board.run(to, left).inspect_err(|e| {
                self.error = Some(e.clone());
            })?;
            left = left.saturating_sub(self.board.instructions() - before);
            if status != Status::Ran || self.board.cycles() >= until || left == 0 {
                return Ok(status);
            }
        }
    }

    /// A sample's worth of the way to the next place the mouse is to go.
    fn feed_mouse(&mut self) {
        let Some(&(x, y, b)) = self.mouse_to.front() else {
            return;
        };
        let step = |v: i32| v.clamp(-MOUSE_STEP, MOUSE_STEP);
        let (dx, dy) = (step(x - self.mouse_at.0), step(y - self.mouse_at.1));
        self.mouse_at = (self.mouse_at.0 + dx, self.mouse_at.1 + dy);
        if self.mouse_at == (x, y) {
            self.buttons = b;
            self.mouse_to.pop_front();
        }
        self.board.mouse(dx, dy, self.buttons);
    }

    /// The mouse to (x, y) on the screen, with `buttons` held when it gets
    /// there. It goes as the machine runs.
    pub fn mouse_to(&mut self, x: i32, y: i32, buttons: u8) {
        let Some((w, h)) = self.board.screen_size().filter(|_| self.board.has_mouse()) else {
            return;
        };
        let to = (x.clamp(0, w as i32 - 1), y.clamp(0, h as i32 - 1), buttons);
        // the last place to go is only motion if it doesn't change the
        // buttons, and then this one can take its place
        let n = self.mouse_to.len();
        let before = if n >= 2 {
            self.mouse_to[n - 2].2
        } else {
            self.buttons
        };
        match self.mouse_to.back_mut() {
            Some(t) if t.2 == before && t.2 == buttons => *t = to,
            _ if n >= 64 => {}
            _ => self.mouse_to.push_back(to),
        }
    }

    /// Whether the mouse has somewhere to go still.
    pub fn mouse_busy(&self) -> bool {
        !self.mouse_to.is_empty()
    }

    /// The screen as RGBA bytes, if it changed since the last call (or
    /// `always`).
    pub fn screen_rgba(&mut self, always: bool) -> Option<&[u8]> {
        if !self.board.screen(&mut self.pixels, always) {
            return None;
        }
        self.rgba.clear();
        self.rgba.reserve(self.pixels.len() * 4);
        for &p in &self.pixels {
            self.rgba
                .extend_from_slice(&[(p >> 16) as u8, (p >> 8) as u8, p as u8, 255]);
        }
        Some(&self.rgba)
    }
}
