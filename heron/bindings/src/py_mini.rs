//! Heron Mini's register-transfer model with RFC 0042's video
//! (studies/mini/engine) for Python: heron.native.mini.
//! studies/mini/sim.py builds the control store and drives it.

use pyo3::prelude::*;

#[pymodule]
pub mod mini {
    use mini_engine::video::{Bandwidth, Layout};
    use mini_engine::{Board, Cpu, Rom, System};
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;
    use pyo3::types::PyBytes;

    #[pymodule_export]
    use crate::py_v1::SimError;

    #[pymodule_export]
    const FIELDS: [&str; mini_engine::FIELDS.len()] = mini_engine::FIELDS;

    /// The CPU and its board. `words`: the control store's distinct words,
    /// each as FIELDS's values, one after another; `index`: by
    /// microaddress, a word's number or -1.
    #[pyclass]
    struct Machine {
        cpu: Cpu,
        sys: System,
    }

    fn rgb565<'py>(
        py: Python<'py>,
        w: usize,
        h: usize,
        px: &[u16],
    ) -> (usize, usize, Bound<'py, PyBytes>) {
        let bytes: Vec<u8> = px.iter().flat_map(|p| p.to_le_bytes()).collect();
        (w, h, PyBytes::new(py, &bytes))
    }

    #[pymethods]
    impl Machine {
        #[new]
        #[allow(clippy::too_many_arguments)]
        #[pyo3(signature = (words, index, entry, refill, irq, fault, lengths, layout="L0", bandwidth="B0",
                            xga_pixel=1007, queue=2, check=true, jump_decodes=false, profile=false))]
        fn new(
            words: Vec<u32>,
            index: Vec<i32>,
            entry: u32,
            refill: u32,
            irq: u32,
            fault: [u32; 4],
            lengths: [u64; 4],
            layout: &str,
            bandwidth: &str,
            xga_pixel: u64,
            queue: usize,
            check: bool,
            jump_decodes: bool,
            profile: bool,
        ) -> PyResult<Machine> {
            let n = mini_engine::FIELDS.len();
            if !words.len().is_multiple_of(n) {
                return Err(PyValueError::new_err(
                    "words: not a whole number of microwords",
                ));
            }
            let words = words
                .chunks(n)
                .map(|c| c.try_into().expect("a microword"))
                .collect::<Vec<_>>();
            if index.iter().any(|&i| i >= words.len() as i32) {
                return Err(PyValueError::new_err("index: a word that isn't there"));
            }
            let layout = match layout {
                "L0" => Layout::L0,
                "L1" => Layout::L1,
                _ => return Err(PyValueError::new_err("layout: L0 or L1")),
            };
            let bandwidth = match bandwidth {
                "B0" => Bandwidth::B0,
                "B1" => Bandwidth::B1,
                "B2" => Bandwidth::B2,
                _ => return Err(PyValueError::new_err("bandwidth: B0, B1 or B2")),
            };
            let size = index.len();
            let rom = Rom {
                words,
                index,
                entry,
                refill,
                irq,
                fault,
                lengths,
            };
            let mut cpu = Cpu::new(rom, queue, check, jump_decodes).map_err(SimError::new_err)?;
            if profile {
                cpu.ucount = Some(vec![0; size]);
            }
            let board = Board {
                layout,
                bandwidth,
                xga_pixel,
            };
            Ok(Machine {
                cpu,
                sys: System::new(board),
            })
        }

        /// Put bytes in RAM at a physical address (it wraps at 4 MB).
        fn load(&mut self, pa: u32, data: &[u8]) {
            let mask = self.sys.ram.len() - 1;
            for (i, &b) in data.iter().enumerate() {
                self.sys.ram[(pa as usize + i) & mask] = b;
            }
        }

        /// The boot flash's contents.
        fn load_boot(&mut self, data: &[u8]) {
            let n = data.len().min(self.sys.boot.len());
            self.sys.boot[..n].copy_from_slice(&data[..n]);
        }

        /// RAM from a physical address.
        fn read<'py>(&self, py: Python<'py>, pa: u32, n: usize) -> Bound<'py, PyBytes> {
            let mask = self.sys.ram.len() - 1;
            let v: Vec<u8> = (0..n)
                .map(|i| self.sys.ram[(pa as usize + i) & mask])
                .collect();
            PyBytes::new(py, &v)
        }

        /// Input for the suite page's console, and for UART 0 (or 1).
        fn console_input(&mut self, data: &[u8]) {
            self.sys.page.inp.extend_from_slice(data);
        }
        #[pyo3(signature = (data, n=0))]
        fn uart_input(&mut self, data: &[u8], n: usize) {
            self.sys.uarts[n & 1].inp.extend_from_slice(data);
        }

        /// Run until the CPU halts ("halted"), `frames` more frames are
        /// complete ("frames", if frames > 0) or the cycle count reaches
        /// `until` ("limit"). Ctrl-C stops it.
        #[pyo3(signature = (until, frames=0))]
        fn run(&mut self, py: Python<'_>, until: u64, frames: u64) -> PyResult<&'static str> {
            let target = if frames > 0 {
                self.sys.video.frames + frames
            } else {
                u64::MAX
            };
            loop {
                let (cpu, sys) = (&mut self.cpu, &mut self.sys);
                let stop = cpu.cycles.saturating_add(1 << 22).min(until);
                let st = py.detach(|| -> Result<Option<&'static str>, String> {
                    while cpu.cycles < stop {
                        if cpu.halted {
                            return Ok(Some("halted"));
                        }
                        cpu.step(sys)?;
                        if sys.video.frames >= target {
                            return Ok(Some("frames"));
                        }
                    }
                    Ok(None)
                });
                match st.map_err(SimError::new_err)? {
                    Some(s) => return Ok(s),
                    None if self.cpu.halted => return Ok("halted"),
                    None if self.cpu.cycles >= until => return Ok("limit"),
                    None => py.check_signals()?,
                }
            }
        }

        /// The last complete frame: (width, height, RGB 5:6:5 little-endian),
        /// or None before the first.
        fn frame<'py>(&self, py: Python<'py>) -> Option<(usize, usize, Bound<'py, PyBytes>)> {
            let v = &self.sys.video;
            if v.frames == 0 {
                return None;
            }
            Some(rgb565(py, v.last_size.0, v.last_size.1, &v.last))
        }

        /// The picture the memory and the registers make now, as `frame`.
        fn snapshot<'py>(&self, py: Python<'py>) -> (usize, usize, Bound<'py, PyBytes>) {
            let (w, h, px) = self.sys.video.snapshot(&self.sys.ram);
            rgb565(py, w, h, &px)
        }

        /// What the suite page's console and the UARTs have sent.
        fn output<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.sys.page.out)
        }
        #[pyo3(signature = (n=0))]
        fn uart_output<'py>(&self, py: Python<'py>, n: usize) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.sys.uarts[n & 1].out)
        }

        /// Executions by microaddress, if profiling: [(address, count)].
        fn ucount(&self) -> Option<Vec<(u32, u64)>> {
            self.cpu.ucount.as_ref().map(|c| {
                c.iter()
                    .enumerate()
                    .filter(|&(_, &n)| n > 0)
                    .map(|(a, &n)| (a as u32, n))
                    .collect()
            })
        }

        #[getter]
        fn r(&self) -> [u32; 16] {
            self.cpu.rf[..16].try_into().expect("16 registers")
        }
        #[getter]
        fn pc(&self) -> u32 {
            self.cpu.pc
        }
        #[getter]
        fn flags(&self) -> u32 {
            self.cpu.flags_word()
        }
        #[getter]
        fn halted(&self) -> bool {
            self.cpu.halted
        }
        #[getter]
        fn cycles(&self) -> u64 {
            self.cpu.cycles
        }
        #[getter]
        fn ticks(&self) -> u64 {
            self.cpu.ticks
        }
        #[getter]
        fn hold_ticks(&self) -> u64 {
            self.cpu.hold_ticks
        }
        #[getter]
        fn steal_ticks(&self) -> u64 {
            self.cpu.steal_ticks
        }
        #[getter]
        fn instructions(&self) -> u64 {
            self.cpu.instructions
        }
        #[getter]
        fn refills(&self) -> u64 {
            self.cpu.refills
        }
        #[getter]
        fn fetch_words(&self) -> u64 {
            self.cpu.fetch_words
        }
        #[getter]
        fn fetch_wasted(&self) -> u64 {
            self.cpu.fetch_wasted
        }
        #[getter]
        fn demand(&self) -> u64 {
            self.cpu.demand
        }
        #[getter]
        fn io_ticks(&self) -> u64 {
            self.sys.io_ticks
        }
        #[getter]
        fn frames(&self) -> u64 {
            self.sys.video.frames
        }
        /// Shifter loads that found no word (B0, B2: the picture glitches).
        #[getter]
        fn underruns(&self) -> u64 {
            self.sys.video.underruns
        }
        /// Loads B1 stole a word for.
        #[getter]
        fn steals(&self) -> u64 {
            self.sys.video.steals
        }
        #[getter]
        fn line_irqs(&self) -> u64 {
            self.sys.video.line_irqs
        }
        /// The video's control register.
        #[getter]
        fn video_ctrl(&self) -> u32 {
            self.sys.video.ctrl
        }
    }
}
