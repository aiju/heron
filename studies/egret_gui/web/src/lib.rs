//! The draft 1b or draft 2 machine in the browser, for studies/egret_gui:
//! app.js loads a snapshot of a machine (snapshot.py writes them; it says
//! which), runs it by the clock, shows its screen and feeds it the
//! keyboard and mouse.
//!
//! The functions are exported as they are, without wasm-bindgen: numbers
//! in and out, and pointers into the module's memory for the bytes (the
//! snapshot going in, the screen and the console coming out).

// `#[unsafe(no_mangle)]` is how a function is exported to JavaScript;
// nothing else here is unsafe.
#![allow(unsafe_code)]

use std::cell::RefCell;

use v1_isa::display::{Display, HEIGHT, WIDTH};

/// The machine: draft 1b's simulator or draft 2's, which have the same
/// fields and methods for all this uses.
pub enum Heron {
    V1(v1_isa::Machine),
    V2(v2_isa::Machine),
}

/// `on!(h, m => e)`: `e` with `m` the machine `h` holds, whichever it is.
macro_rules! on {
    ($h:expr, $m:ident => $e:expr) => {
        match $h {
            Heron::V1($m) => $e,
            Heron::V2($m) => $e,
        }
    };
}

pub mod snapshot;

impl Heron {
    fn display(&mut self) -> &mut Display {
        on!(self, m => &mut m.dev.display)
    }
    fn out(&self) -> &[u8] {
        on!(self, m => &m.dev.out)
    }
    fn cycles(&self) -> u64 {
        on!(self, m => m.cycles)
    }
    fn halted(&self) -> bool {
        on!(self, m => m.halted)
    }
    fn step(&mut self) -> Result<(), String> {
        on!(self, m => m.step())
    }
}

/// A step that skips more cycles than this was HALT waiting for the timer.
const IDLE_SKIP: u64 = 1000;

struct State {
    m: Option<Heron>,
    /// Where the JavaScript side puts a snapshot to load.
    input: Vec<u8>,
    /// The screen as RGBA.
    rgba: Vec<u8>,
    px: Vec<u32>,
    error: String,
    /// The machine waited for the timer during the last run.
    idled: bool,
    /// Cycles spent waiting for the timer, in all.
    idle_cycles: u64,
}

thread_local! {
    static STATE: RefCell<State> = const { RefCell::new(State {
        m: None,
        input: Vec::new(),
        rgba: Vec::new(),
        px: Vec::new(),
        error: String::new(),
        idled: false,
        idle_cycles: 0,
    }) };
}

fn with<R>(f: impl FnOnce(&mut State) -> R) -> R {
    STATE.with(|s| f(&mut s.borrow_mut()))
}

fn with_m<R: Default>(f: impl FnOnce(&mut Heron) -> R) -> R {
    with(|s| s.m.as_mut().map(f).unwrap_or_default())
}

/// Room for `n` bytes of snapshot; JavaScript writes them there, then
/// calls `load`.
#[unsafe(no_mangle)]
pub extern "C" fn input_buffer(n: u32) -> *mut u8 {
    with(|s| {
        s.input.clear();
        s.input.resize(n as usize, 0);
        s.input.as_mut_ptr()
    })
}

/// Load the snapshot in the input buffer: 1 if it worked, 0 if not (see
/// `error`).
#[unsafe(no_mangle)]
pub extern "C" fn load() -> u32 {
    with(|s| match snapshot::load(&s.input) {
        Ok(m) => {
            s.m = Some(m);
            s.idle_cycles = 0;
            s.input = Vec::new();
            1
        }
        Err(e) => {
            s.error = e;
            0
        }
    })
}

/// Run until `budget` more cycles have passed or `steps` instructions,
/// whichever comes first. Returns 0 if it can go on, 1 if the machine
/// halted, 2 on an error (see `error`).
#[unsafe(no_mangle)]
pub extern "C" fn run(budget: f64, steps: u32) -> u32 {
    with(|s| {
        let Some(m) = s.m.as_mut() else { return 2 };
        let until = m.cycles() + budget.max(0.0) as u64;
        for _ in 0..steps {
            if m.halted() {
                return 1;
            }
            if m.cycles() >= until {
                break;
            }
            let before = m.cycles();
            if let Err(e) = m.step() {
                s.error = e;
                return 2;
            }
            if m.cycles() - before > IDLE_SKIP {
                s.idled = true;
                s.idle_cycles += m.cycles() - before;
            }
        }
        u32::from(m.halted())
    })
}

/// Whether the machine waited for the timer since the last call.
#[unsafe(no_mangle)]
pub extern "C" fn idled() -> u32 {
    with(|s| u32::from(std::mem::take(&mut s.idled)))
}

/// Cycles spent waiting for the timer since the machine was loaded.
#[unsafe(no_mangle)]
pub extern "C" fn idle_cycles() -> f64 {
    with(|s| s.idle_cycles as f64)
}

#[unsafe(no_mangle)]
pub extern "C" fn cycles() -> f64 {
    with_m(|m| m.cycles() as f64)
}

#[unsafe(no_mangle)]
pub extern "C" fn instructions() -> f64 {
    with_m(|h| on!(h, m => m.instructions as f64))
}

/// Which draft the machine is: 1 (1b) or 2.
#[unsafe(no_mangle)]
pub extern "C" fn isa() -> u32 {
    with_m(|h| match h {
        Heron::V1(_) => 1,
        Heron::V2(_) => 2,
    })
}

/// The screen as RGBA, WIDTH x HEIGHT, if it changed since the last call
/// (else null).
#[unsafe(no_mangle)]
pub extern "C" fn screen() -> *const u8 {
    with(|s| {
        let Some(m) = s.m.as_mut() else {
            return std::ptr::null();
        };
        let d = m.display();
        if !d.dirty {
            return std::ptr::null();
        }
        d.dirty = false;
        d.rgb_into(&mut s.px);
        s.rgba.clear();
        for &p in &s.px {
            s.rgba
                .extend_from_slice(&[(p >> 16) as u8, (p >> 8) as u8, p as u8, 255]);
        }
        s.rgba.as_ptr()
    })
}

#[unsafe(no_mangle)]
pub extern "C" fn width() -> u32 {
    WIDTH
}

#[unsafe(no_mangle)]
pub extern "C" fn height() -> u32 {
    HEIGHT
}

#[unsafe(no_mangle)]
pub extern "C" fn push_event(e: u32) {
    with_m(|m| m.display().push_event(e));
}

#[unsafe(no_mangle)]
pub extern "C" fn set_mouse(x: u32, y: u32, buttons: u32) {
    with_m(|m| {
        let d = m.display();
        d.mouse_x = x;
        d.mouse_y = y;
        d.buttons = buttons;
    });
}

#[unsafe(no_mangle)]
pub extern "C" fn set_time_of_day(seconds: u32) {
    with_m(|m| m.display().time_of_day = seconds);
}

/// The timer's period in cycles. The page sets it from the clock it runs
/// the machine at, as a faster machine would be programmed, so the timer
/// ticks 60 times a second at any speed (the desktop works in ticks).
/// Until the machine has started its timer, this does nothing.
#[unsafe(no_mangle)]
pub extern "C" fn set_timer_period(cycles: f64) {
    with_m(|h| {
        on!(h, m => {
            let p = cycles as u64;
            if m.dev.timer_period != 0 && p != 0 && p != m.dev.timer_period {
                m.dev.timer_period = p;
                m.dev.timer_next = m.dev.timer_next.min(m.cycles + p);
            }
        })
    });
}

/// The pointer's shape (display.rs).
#[unsafe(no_mangle)]
pub extern "C" fn pointer() -> u32 {
    with_m(|m| m.display().pointer)
}

/// The console output so far: its length, and where it is.
#[unsafe(no_mangle)]
pub extern "C" fn output_len() -> u32 {
    with_m(|m| m.out().len() as u32)
}

#[unsafe(no_mangle)]
pub extern "C" fn output_ptr() -> *const u8 {
    with(|s| s.m.as_ref().map_or(std::ptr::null(), |m| m.out().as_ptr()))
}

/// The last error, as UTF-8.
#[unsafe(no_mangle)]
pub extern "C" fn error_len() -> u32 {
    with(|s| s.error.len() as u32)
}

#[unsafe(no_mangle)]
pub extern "C" fn error_ptr() -> *const u8 {
    with(|s| s.error.as_ptr())
}
