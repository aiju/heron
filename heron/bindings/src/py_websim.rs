//! The website's simulator (studies/websim/engine) for Python:
//! heron.native.websim. A Session is a machine made from a description, as
//! the browser makes it; the study's tests and command line drive it.

use pyo3::prelude::*;

#[pymodule]
pub mod websim {
    use pyo3::prelude::*;
    use pyo3::types::PyBytes;
    use websim::Setup;

    #[pymodule_export]
    use crate::py_v1::SimError;

    /// A machine: `board` with `params` ({name: text}) and `loads`
    /// ([(target, address, bytes)]), at power-on.
    #[pyclass]
    struct Session {
        s: websim::Session,
    }

    #[pymethods]
    impl Session {
        #[new]
        #[pyo3(signature = (board, params=Vec::new(), loads=Vec::new()))]
        fn new(
            board: &str,
            params: Vec<(String, String)>,
            loads: Vec<(String, u32, Vec<u8>)>,
        ) -> PyResult<Session> {
            let mut setup = Setup::new(board);
            for (n, v) in &params {
                setup.param(n, v);
            }
            for (t, at, bytes) in loads {
                setup.load(&t, at, bytes);
            }
            Ok(Session {
                s: setup.start().map_err(SimError::new_err)?,
            })
        }

        /// Run for `cycles` more cycles or `steps` instructions: "ran",
        /// "waiting" (for the terminal), "idle" (asleep with nothing to
        /// wake it) or "halted". Ctrl-C stops it.
        #[pyo3(signature = (cycles, steps=u64::MAX))]
        fn run(&mut self, py: Python<'_>, cycles: u64, steps: u64) -> PyResult<&'static str> {
            let until = self.s.board_ref().cycles().saturating_add(cycles);
            let mut left = steps;
            loop {
                let chunk = left.min(1 << 20);
                let s = &mut self.s;
                let more = until.saturating_sub(s.board_ref().cycles());
                let before = s.board_ref().instructions();
                let st = py
                    .detach(|| s.run(more, chunk))
                    .map_err(SimError::new_err)?;
                left = left.saturating_sub(self.s.board_ref().instructions() - before);
                if st != websim::Status::Ran || self.s.board_ref().cycles() >= until || left == 0 {
                    return Ok(st.name());
                }
                py.check_signals()?;
            }
        }

        #[getter]
        fn cycles(&self) -> u64 {
            self.s.board_ref().cycles()
        }

        #[getter]
        fn instructions(&self) -> u64 {
            self.s.board_ref().instructions()
        }

        #[getter]
        fn idle_cycles(&self) -> u64 {
            self.s.board_ref().idle_cycles()
        }

        #[getter]
        fn clock_hz(&self) -> f64 {
            self.s.board_ref().clock_hz()
        }

        /// Type at the terminal.
        fn send(&mut self, data: &[u8]) {
            self.s.board().send(data);
        }

        /// The end of the terminal's input.
        fn close(&mut self) {
            self.s.board().close();
        }

        /// What it printed since the last call.
        fn output<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.s.board().take_output())
        }

        /// What it wrote to its log since the last call.
        fn log<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.s.board().take_log())
        }

        /// (width, height), or None without a screen.
        #[getter]
        fn screen_size(&self) -> Option<(u32, u32)> {
            self.s.board_ref().screen_size()
        }

        /// The screen as RGBA bytes if it changed since the last call (or
        /// `always`), else None.
        #[pyo3(signature = (always=false))]
        fn screen<'py>(&mut self, py: Python<'py>, always: bool) -> Option<Bound<'py, PyBytes>> {
            self.s.screen_rgba(always).map(|p| PyBytes::new(py, p))
        }

        /// A key down or up, by its browser name ("KeyA"): whether the
        /// machine has it.
        fn key(&mut self, name: &str, down: bool) -> bool {
            self.s.board().key(name, down)
        }

        /// The mouse to (x, y) with `buttons` held.
        #[pyo3(signature = (x, y, buttons=0))]
        fn mouse(&mut self, x: i32, y: i32, buttons: u8) {
            self.s.mouse_to(x, y, buttons);
        }

        /// Whether the mouse has somewhere to go still.
        #[getter]
        fn mouse_busy(&self) -> bool {
            self.s.mouse_busy()
        }

        /// [(name, value)]
        fn registers(&self) -> Vec<(String, u32)> {
            self.s.board_ref().registers()
        }

        fn peek<'py>(&self, py: Python<'py>, addr: u32, n: u32) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.s.board_ref().peek(addr, n))
        }
    }
}
