//! The machine Fen runs on (studies/fen/board) for Python: heron.native.fen.
//! A Computer is draft 2 in system mode with its board; studies/fen/run.py
//! drives it.

use pyo3::prelude::*;

#[pymodule]
pub mod fen {
    use fen_board::{Computer as Engine, Config, ps2};
    use pyo3::prelude::*;
    use pyo3::types::{PyBytes, PyDict};
    use v2_isa::RunStatus;

    #[pymodule_export]
    use crate::py_v1::SimError;

    /// (instruction address or None, timing key, executions)
    type PcKey<'py> = (Option<u32>, Bound<'py, pyo3::types::PyTuple>, u64);

    /// The set 2 code of a key, by the name a browser gives it
    /// (KeyboardEvent.code: "KeyA", "Enter", "ShiftLeft", ...).
    #[pyfunction]
    fn scancode(name: &str) -> Option<u16> {
        ps2::scancode(name)
    }

    /// The machine and its board. `cf_image` is the CompactFlash card's
    /// contents.
    #[pyclass]
    struct Computer {
        c: Engine,
        screen: Vec<u32>,
    }

    #[pymethods]
    impl Computer {
        #[new]
        #[pyo3(signature = (cf_image=b"".as_slice(), ram_size=4 << 20, clock_hz=6e6, epoch=None, reference=None, boot_flags=0))]
        fn new(
            cf_image: &[u8],
            ram_size: u32,
            clock_hz: f64,
            epoch: Option<u64>,
            reference: Option<&str>,
            boot_flags: u32,
        ) -> PyResult<Computer> {
            let mut cfg = Config {
                ram_size,
                clock_hz,
                boot_flags,
                ..Config::default()
            };
            if let Some(e) = epoch {
                cfg.epoch = e;
            }
            if let Some(r) = reference {
                cfg.timing = crate::py_v2::v2::config(r)?;
            }
            Ok(Computer {
                c: Engine::new(cfg, cf_image.to_vec()),
                screen: Vec::new(),
            })
        }

        /// Put bytes in RAM at a physical address.
        fn load(&mut self, pa: u32, data: &[u8]) -> PyResult<()> {
            if pa as usize + data.len() > self.c.m.mem.len() {
                return Err(SimError::new_err("doesn't fit in RAM"));
            }
            self.c.load(pa, data);
            Ok(())
        }

        /// Run until the cycle count reaches `until`, or for `steps`
        /// instructions: "halted", "idle" (waiting in HALT for something
        /// from outside), "limit" or "steps". Ctrl-C stops it.
        #[pyo3(signature = (until, steps=u64::MAX))]
        fn run(&mut self, py: Python<'_>, until: u64, steps: u64) -> PyResult<&'static str> {
            let mut left = steps;
            loop {
                let chunk = left.min(1 << 20);
                let c = &mut self.c;
                let st = py
                    .detach(|| c.run(until, chunk))
                    .map_err(SimError::new_err)?;
                left -= chunk.min(left);
                match st {
                    RunStatus::Halted => return Ok("halted"),
                    RunStatus::Idle => return Ok("idle"),
                    RunStatus::Limit => return Ok("limit"),
                    RunStatus::Steps if left == 0 => return Ok("steps"),
                    RunStatus::Steps => py.check_signals()?,
                }
            }
        }

        /// The cycle count at a time in ns, at the board's clock.
        fn cycles_at(&self, ns: u64) -> u64 {
            self.c.cycles_at(ns)
        }

        #[getter]
        fn now_ns(&self) -> u64 {
            self.c.now_ns()
        }

        fn key(&mut self, code: u16, down: bool) {
            self.c.key(code, down);
        }

        fn mouse(&mut self, dx: i32, dy: i32, buttons: u8) {
            self.c.mouse(dx, dy, buttons);
        }

        fn uart_send(&mut self, data: &[u8]) {
            self.c.uart_send(data);
        }

        fn uart_take<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.c.uart_take())
        }

        fn debug_take<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.c.debug_take())
        }

        /// The screen as 640 x 480 RGB bytes, if it changed since the last
        /// call, else None (always: whether it changed or not).
        #[pyo3(signature = (always=false))]
        fn screen<'py>(&mut self, py: Python<'py>, always: bool) -> Option<Bound<'py, PyBytes>> {
            if !self.c.screen(&mut self.screen, always) {
                return None;
            }
            let mut rgb = Vec::with_capacity(self.screen.len() * 3);
            for &p in &self.screen {
                rgb.extend_from_slice(&[(p >> 16) as u8, (p >> 8) as u8, p as u8]);
            }
            Some(PyBytes::new(py, &rgb))
        }

        /// The CompactFlash card's contents, with what has been written.
        fn cf_image<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, self.c.board().cf.image())
        }

        /// Physical memory.
        fn read_phys<'py>(&self, py: Python<'py>, pa: u32, n: u32) -> Bound<'py, PyBytes> {
            let a = (pa as usize).min(self.c.m.mem.len());
            let b = (a + n as usize).min(self.c.m.mem.len());
            PyBytes::new(py, &self.c.m.mem[a..b])
        }

        /// The parcel at a virtual address, as the CPU would fetch it now,
        /// or None.
        fn parcel(&self, va: u32) -> Option<u32> {
            self.c.m.parcel(va).ok()
        }

        #[getter]
        fn pc(&self) -> u32 {
            self.c.m.pc
        }
        #[getter]
        fn r(&self) -> [u32; 16] {
            self.c.m.r
        }
        #[getter]
        fn sr(&self) -> u32 {
            self.c.m.sr()
        }
        #[getter]
        fn cycles(&self) -> u64 {
            self.c.m.cycles
        }
        #[getter]
        fn idle_cycles(&self) -> u64 {
            self.c.m.idle_cycles
        }
        #[getter]
        fn instructions(&self) -> u64 {
            self.c.m.instructions
        }
        #[getter]
        fn halted(&self) -> bool {
            self.c.m.halted
        }
        #[getter]
        fn ctx(&self) -> u32 {
            self.c.m.sys().ctx
        }
        #[getter]
        fn bank(&self) -> u32 {
            self.c.m.sys().bank
        }
        /// Exceptions and interrupts taken from user mode.
        #[getter]
        fn user_entries(&self) -> u64 {
            self.c.m.sys().user_entries
        }

        /// Start (or with `on` false, stop) the trace of threads run:
        /// each RTI into user mode in another bank than the last.
        #[pyo3(signature = (on=true))]
        fn trace_banks(&mut self, on: bool) {
            self.c.m.sys_mut().user_runs = if on { Some(Vec::new()) } else { None };
            self.c.board().trace = if on { Some(Vec::new()) } else { None };
        }

        /// The trace so far, [(cycle, bank)], with 0x100 | bank for a
        /// BCOPY into the bank, and empty it.
        fn bank_runs(&mut self) -> Vec<(u64, u16)> {
            match &mut self.c.m.sys_mut().user_runs {
                Some(v) => std::mem::take(v),
                None => Vec::new(),
            }
        }

        /// What the kernel wrote to the board's trace port so far,
        /// [(cycle, word)], and empty it.
        fn trace_port(&mut self) -> Vec<(u64, u32)> {
            match &mut self.c.board().trace {
                Some(v) => std::mem::take(v),
                None => Vec::new(),
            }
        }

        /// A context's valid page map entries: [(virtual page, entry)].
        fn page_map(&self, ctx: usize) -> Vec<(u32, u32)> {
            use v2_isa::sys::{CONTEXTS, PAGES, PTE_V};
            if ctx >= CONTEXTS {
                return Vec::new();
            }
            let map = &self.c.m.sys().map[ctx * PAGES..(ctx + 1) * PAGES];
            (0..PAGES)
                .filter(|&p| map[p] & PTE_V != 0)
                .map(|p| (p as u32, map[p]))
                .collect()
        }

        /// Registers of a bank (r0-r15).
        fn bank_regs(&self, n: usize) -> Vec<u32> {
            let s = self.c.m.sys();
            if n == s.cur_bank {
                self.c.m.r.to_vec()
            } else {
                s.banks[n % s.banks.len()].to_vec()
            }
        }
        /// Traps taken but SWIs, the first thousand: [(pc, what)].
        #[getter]
        fn traps(&self) -> Vec<(u32, String)> {
            self.c.m.traps.clone()
        }
        /// Exceptions taken, by vector offset / 4 (every SWI at 0x40).
        #[getter]
        fn exceptions(&self) -> Vec<u64> {
            self.c.m.sys().exceptions.to_vec()
        }
        /// Interrupts taken, by level.
        #[getter]
        fn interrupts(&self) -> Vec<u64> {
            self.c.m.sys().interrupts.to_vec()
        }

        /// Executions per (physical instruction address, timing key).
        fn pc_keys<'py>(&self, py: Python<'py>) -> PyResult<Vec<PcKey<'py>>> {
            self.c
                .m
                .pc_keys()
                .iter()
                .map(|(pc, k, n)| Ok((*pc, crate::py_v2::v2::key_tuple(py, k)?, *n)))
                .collect()
        }

        /// Cycles in a configuration, idle time left out.
        fn cycles_for(&self, config: &str) -> PyResult<u64> {
            Ok(self
                .c
                .m
                .cycles_for(crate::py_v2::v2::config(config)?, false))
        }

        /// {physical instruction address: cycles} in a configuration.
        fn pc_cycles<'py>(&self, py: Python<'py>, config: &str) -> PyResult<Bound<'py, PyDict>> {
            let c = crate::py_v2::v2::config(config)?;
            let out = PyDict::new(py);
            for (pc, k, n) in self.c.m.pc_keys() {
                let prev: u64 = match out.get_item(pc)? {
                    Some(v) => v.extract()?,
                    None => 0,
                };
                out.set_item(pc, prev + n * c.cycles(k) as u64)?;
            }
            Ok(out)
        }
    }
}
