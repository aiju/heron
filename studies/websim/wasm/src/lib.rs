//! The simulator in the browser (studies/websim): the engine's [`Setup`]
//! and [`Session`] as plain exported functions, which web/sim.js calls.
//!
//! Numbers go in and out as arguments and results. Bytes and text go in
//! through the inbox: JavaScript asks for room (`inbox`), writes there,
//! then calls the function that takes them. They come out through the
//! outbox: a function puts them there and returns their length, and
//! JavaScript reads them at `outbox`. Both are reused from call to call,
//! and the module's memory can move when it grows, so JavaScript makes a
//! fresh view of it after every call.
//!
//! One machine at a time: `setup` starts a description, `param` and
//! `load` add to it, and `start` makes the machine from it, in place of
//! the one before.

// `#[unsafe(no_mangle)]` is how a function is exported to JavaScript;
// nothing here is unsafe otherwise.
#![allow(unsafe_code)]

use std::cell::RefCell;

use websim::{Session, Setup, Status};

#[derive(Default)]
struct State {
    setup: Option<Setup>,
    session: Option<Session>,
    inbox: Vec<u8>,
    outbox: Vec<u8>,
    error: String,
}

thread_local! {
    static STATE: RefCell<State> = RefCell::new(State::default());
}

fn with<R>(f: impl FnOnce(&mut State) -> R) -> R {
    STATE.with(|s| f(&mut s.borrow_mut()))
}

/// `f` with the session, or `none` without one.
fn with_session<R>(none: R, f: impl FnOnce(&mut Session) -> R) -> R {
    with(|s| s.session.as_mut().map_or(none, f))
}

/// Put bytes in the outbox; their length.
fn out(s: &mut State, bytes: &[u8]) -> u32 {
    s.outbox.clear();
    s.outbox.extend_from_slice(bytes);
    s.outbox.len() as u32
}

/// Room for `n` bytes going in; where to write them.
#[unsafe(no_mangle)]
pub extern "C" fn inbox(n: u32) -> *mut u8 {
    with(|s| {
        s.inbox.clear();
        s.inbox.resize(n as usize, 0);
        s.inbox.as_mut_ptr()
    })
}

/// Where the bytes coming out are.
#[unsafe(no_mangle)]
pub extern "C" fn outbox() -> *const u8 {
    with(|s| s.outbox.as_ptr())
}

/// The last error, into the outbox: its length.
#[unsafe(no_mangle)]
pub extern "C" fn error() -> u32 {
    with(|s| {
        let e = std::mem::take(&mut s.error);
        let n = out(s, e.as_bytes());
        s.error = e;
        n
    })
}

/// A new description, for the board named in the inbox.
#[unsafe(no_mangle)]
pub extern "C" fn setup() {
    with(|s| {
        let board = String::from_utf8_lossy(&s.inbox).into_owned();
        s.setup = Some(Setup::new(&board));
    })
}

/// A parameter of the description: `name=value` in the inbox.
#[unsafe(no_mangle)]
pub extern "C" fn param() -> u32 {
    with(|s| {
        let text = String::from_utf8_lossy(&s.inbox).into_owned();
        match (s.setup.as_mut(), text.split_once('=')) {
            (Some(setup), Some((n, v))) => {
                setup.param(n, v);
                1
            }
            _ => {
                s.error = format!("bad parameter {text:?}");
                0
            }
        }
    })
}

/// Something to load at `at`: the inbox has the target's name, a 0 byte,
/// then the bytes.
#[unsafe(no_mangle)]
pub extern "C" fn load(at: u32) -> u32 {
    with(|s| {
        let inbox = std::mem::take(&mut s.inbox);
        let Some(i) = inbox.iter().position(|&b| b == 0) else {
            s.error = "load: no target".into();
            return 0;
        };
        let Some(setup) = s.setup.as_mut() else {
            s.error = "load: no setup".into();
            return 0;
        };
        let target = String::from_utf8_lossy(&inbox[..i]).into_owned();
        setup.load(&target, at, inbox[i + 1..].to_vec());
        1
    })
}

/// Make the machine: 1, or 0 if the description is wrong (see `error`).
#[unsafe(no_mangle)]
pub extern "C" fn start() -> u32 {
    with(|s| {
        let made = match s.setup.as_ref() {
            Some(setup) => setup.start(),
            None => Err("start: no setup".into()),
        };
        match made {
            Ok(m) => {
                s.session = Some(m);
                s.setup = None;
                1
            }
            Err(e) => {
                s.error = e;
                0
            }
        }
    })
}

/// Run for `cycles` more cycles or `steps` instructions: 0 ran, 1 waits for
/// the terminal, 2 asleep with nothing to wake it, 3 halted, -1 stopped
/// with an error (see `error`).
#[unsafe(no_mangle)]
pub extern "C" fn run(cycles: f64, steps: f64) -> i32 {
    with(|s| {
        let Some(m) = s.session.as_mut() else {
            s.error = "no machine".into();
            return -1;
        };
        match m.run(cycles.max(0.0) as u64, steps.max(1.0) as u64) {
            Ok(Status::Ran) => 0,
            Ok(Status::Waiting) => 1,
            Ok(Status::Idle) => 2,
            Ok(Status::Halted) => 3,
            Err(e) => {
                s.error = e;
                -1
            }
        }
    })
}

#[unsafe(no_mangle)]
pub extern "C" fn cycles() -> f64 {
    with_session(0.0, |m| m.board_ref().cycles() as f64)
}

#[unsafe(no_mangle)]
pub extern "C" fn instructions() -> f64 {
    with_session(0.0, |m| m.board_ref().instructions() as f64)
}

/// Cycles spent asleep in HALT.
#[unsafe(no_mangle)]
pub extern "C" fn idle_cycles() -> f64 {
    with_session(0.0, |m| m.board_ref().idle_cycles() as f64)
}

#[unsafe(no_mangle)]
pub extern "C" fn clock_hz() -> f64 {
    with_session(0.0, |m| m.board_ref().clock_hz())
}

/// The inbox's bytes, typed at the terminal.
#[unsafe(no_mangle)]
pub extern "C" fn send() {
    with(|s| {
        let bytes = std::mem::take(&mut s.inbox);
        if let Some(m) = s.session.as_mut() {
            m.board().send(&bytes);
        }
    })
}

/// The end of the terminal's input.
#[unsafe(no_mangle)]
pub extern "C" fn close() {
    with_session((), |m| m.board().close())
}

/// What the machine printed since the last call, into the outbox.
#[unsafe(no_mangle)]
pub extern "C" fn output() -> u32 {
    with(|s| {
        let bytes = s
            .session
            .as_mut()
            .map(|m| m.board().take_output())
            .unwrap_or_default();
        out(s, &bytes)
    })
}

/// What it wrote to its log since the last call, into the outbox.
#[unsafe(no_mangle)]
pub extern "C" fn log() -> u32 {
    with(|s| {
        let bytes = s
            .session
            .as_mut()
            .map(|m| m.board().take_log())
            .unwrap_or_default();
        out(s, &bytes)
    })
}

/// The screen's width and height, 0 without one.
#[unsafe(no_mangle)]
pub extern "C" fn screen_width() -> u32 {
    with_session(0, |m| m.board_ref().screen_size().map_or(0, |s| s.0))
}

#[unsafe(no_mangle)]
pub extern "C" fn screen_height() -> u32 {
    with_session(0, |m| m.board_ref().screen_size().map_or(0, |s| s.1))
}

/// The screen as RGBA, if it changed since the last call (or `always`):
/// where it is, or null.
#[unsafe(no_mangle)]
pub extern "C" fn screen(always: u32) -> *const u8 {
    with_session(std::ptr::null(), |m| {
        m.screen_rgba(always != 0)
            .map_or(std::ptr::null(), |p| p.as_ptr())
    })
}

/// A key down (1) or up (0), named in the inbox as a browser names it:
/// 1 if the machine has the key.
#[unsafe(no_mangle)]
pub extern "C" fn key(down: u32) -> u32 {
    with(|s| {
        let name = String::from_utf8_lossy(&s.inbox).into_owned();
        s.session
            .as_mut()
            .map_or(0, |m| m.board().key(&name, down != 0) as u32)
    })
}

/// Whether there's a mouse.
#[unsafe(no_mangle)]
pub extern "C" fn has_mouse() -> u32 {
    with_session(0, |m| m.board_ref().has_mouse() as u32)
}

/// The mouse to (x, y) on the screen, with `buttons` held.
#[unsafe(no_mangle)]
pub extern "C" fn mouse(x: i32, y: i32, buttons: u32) {
    with_session((), |m| m.mouse_to(x, y, buttons as u8))
}

/// The registers into the outbox, a line `name value` each.
#[unsafe(no_mangle)]
pub extern "C" fn registers() -> u32 {
    with(|s| {
        let text: String = s
            .session
            .as_ref()
            .map(|m| {
                m.board_ref()
                    .registers()
                    .iter()
                    .map(|(n, v)| format!("{n} {v}\n"))
                    .collect()
            })
            .unwrap_or_default();
        out(s, text.as_bytes())
    })
}

/// `len` bytes of RAM at `addr` into the outbox (fewer past its end).
#[unsafe(no_mangle)]
pub extern "C" fn peek(addr: u32, len: u32) -> u32 {
    with(|s| {
        let bytes = s
            .session
            .as_ref()
            .map(|m| m.board_ref().peek(addr, len))
            .unwrap_or_default();
        out(s, &bytes)
    })
}
