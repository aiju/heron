//! Chibi Heron's whole-machine simulator (studies/chibi/sim) for Python:
//! heron.native.chibi. studies/chibi/sim.py builds the control store's
//! image and drives it.

use pyo3::prelude::*;

#[pymodule]
pub mod chibi {
    use chibi_sim::{Config, Machine as Engine, Status, Store, board, ps2, video};
    use pyo3::prelude::*;
    use pyo3::types::{PyBytes, PyDict};

    #[pymodule_export]
    use crate::py_v1::SimError;

    /// The set 2 code of a key, by the name a browser gives it
    /// (KeyboardEvent.code: "KeyA", "Enter", ...).
    #[pyfunction]
    fn scancode(name: &str) -> Option<u16> {
        ps2::scancode(name)
    }

    /// The ticks of `s` seconds.
    #[pyfunction]
    fn ticks_of(s: f64) -> u64 {
        Engine::ticks_of(s)
    }

    /// The machine at power-on, its control store from `store` (sim.py's
    /// store_image).
    #[pyclass(unsendable)]
    struct Machine {
        m: Engine,
        rgb: Vec<u8>,
    }

    #[pymethods]
    impl Machine {
        #[new]
        #[pyo3(signature = (store, fixture=true, stretch=true, mouse_reporting=false, console_input=b"".as_slice()))]
        fn new(
            store: &[u8],
            fixture: bool,
            stretch: bool,
            mouse_reporting: bool,
            console_input: &[u8],
        ) -> PyResult<Machine> {
            let store = Store::from_image(store).map_err(SimError::new_err)?;
            let cfg = Config {
                fixture,
                stretch,
                mouse_reporting,
                ..Config::default()
            };
            let mut m = Engine::new(store, cfg);
            m.board.fixture.inp = console_input.to_vec();
            Ok(Machine { m, rgb: Vec::new() })
        }

        /// Run until the tick count reaches `until`, `max_cycles`
        /// microinstructions, the machine stops (`stop_on_halt`) or a
        /// breakpoint: "limit", "halted" or "breakpoint". Ctrl-C stops it.
        #[pyo3(signature = (until=u64::MAX, max_cycles=u64::MAX))]
        fn run(&mut self, py: Python<'_>, until: u64, max_cycles: u64) -> PyResult<&'static str> {
            loop {
                let chunk = self.m.cpu.ticks.saturating_add(1 << 26).min(until);
                let m = &mut self.m;
                let st = py
                    .detach(|| m.run(chunk, max_cycles))
                    .map_err(SimError::new_err)?;
                match st {
                    Status::Halted => return Ok("halted"),
                    Status::Breakpoint => return Ok("breakpoint"),
                    Status::Limit
                        if self.m.cpu.ticks >= until || self.m.cpu.cycles >= max_cycles =>
                    {
                        return Ok("limit");
                    }
                    Status::Limit => py.check_signals()?,
                }
            }
        }

        /// Run for `s` seconds of the machine's time.
        fn run_for(&mut self, py: Python<'_>, s: f64) -> PyResult<&'static str> {
            let until = self.m.cpu.ticks + Engine::ticks_of(s);
            self.run(py, until, u64::MAX)
        }

        #[setter]
        fn set_stop_on_halt(&mut self, v: bool) {
            self.m.stop_on_halt = v;
        }

        #[setter]
        fn set_skip_idle(&mut self, v: bool) {
            self.m.skip_idle = v;
        }

        #[getter]
        fn stopped(&self) -> bool {
            self.m.stopped()
        }

        #[getter]
        fn ticks(&self) -> u64 {
            self.m.cpu.ticks
        }

        #[getter]
        fn cycles(&self) -> u64 {
            self.m.cpu.cycles
        }

        #[getter]
        fn instructions(&self) -> u64 {
            self.m.cpu.instructions
        }

        #[getter]
        fn seconds(&self) -> f64 {
            self.m.seconds()
        }

        #[getter]
        fn pc(&self) -> u32 {
            self.m.cpu.pc
        }

        /// The address of the instruction running (the last decode's).
        #[getter]
        fn insn_pc(&self) -> u32 {
            self.m.cpu.insn_pc
        }

        #[getter]
        fn upc(&self) -> usize {
            self.m.cpu.address(&self.m.store)
        }

        #[getter]
        fn task(&self) -> bool {
            self.m.cpu.task
        }

        /// A program register, in bank 0 or 1.
        #[pyo3(signature = (n, bank=false))]
        fn reg(&self, n: usize, bank: bool) -> u32 {
            self.m.cpu.reg(n, bank)
        }

        #[pyo3(signature = (n, v, bank=false))]
        fn set_reg(&mut self, n: usize, v: u32, bank: bool) {
            self.m.cpu.set_reg(n, bank, v);
        }

        /// The register file: 256 halfwords, [half << 7 | task << 6 |
        /// bank << 5 | n].
        fn register_file(&self) -> Vec<u16> {
            self.m.cpu.rf.to_vec()
        }

        /// The flags, by name (N Z C V I IC ST B BI INIT IRQP).
        fn flags<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
            let f = self.m.cpu.f;
            let d = PyDict::new(py);
            for (k, v) in [
                ("N", f.n),
                ("Z", f.z),
                ("C", f.c),
                ("V", f.v),
                ("I", f.i),
                ("IC", f.ic),
                ("ST", f.st),
                ("B", f.b),
                ("BI", f.bi),
                ("INIT", f.init),
                ("IRQP", f.irqp),
            ] {
                d.set_item(k, v as u8)?;
            }
            Ok(d)
        }

        // ---- memory

        /// Put bytes in RAM (the address wraps at 2 MB).
        fn load(&mut self, addr: u32, data: &[u8]) {
            self.m.load(addr, data);
        }

        /// RAM, `n` bytes from `addr`.
        fn ram<'py>(&self, py: Python<'py>, addr: u32, n: usize) -> Bound<'py, PyBytes> {
            let r = &self.m.board.ram;
            let out: Vec<u8> = (0..n)
                .map(|i| r[(addr as usize + i) % board::RAM_SIZE])
                .collect();
            PyBytes::new(py, &out)
        }

        /// The boot flash's 128 KB.
        fn flash<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.m.board.flash.data)
        }

        /// Program the boot flash (as a programmer would, off the board),
        /// from byte 0; the rest stays as it was.
        fn set_flash(&mut self, data: &[u8]) -> PyResult<()> {
            let f = &mut self.m.board.flash.data;
            if data.len() > f.len() {
                return Err(SimError::new_err("more than the flash's 128 KB"));
            }
            f[..data.len()].copy_from_slice(data);
            Ok(())
        }

        /// The CompactFlash card, its contents as they are now.
        fn cf_image<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, self.m.board.cf.image())
        }

        /// Put a card with these contents in the slot.
        fn set_cf(&mut self, image: &[u8]) {
            let t = self.m.cpu.ticks;
            self.m.board.set_cf(image.to_vec(), t);
        }

        // ---- the outside

        /// What the suite's console has printed.
        fn console_out<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.m.board.fixture.out)
        }

        /// More input on the suite's console.
        fn console_in(&mut self, data: &[u8]) {
            self.m.board.fixture.inp.extend_from_slice(data);
        }

        /// Bytes typed at UART `port`'s terminal.
        fn uart_send(&mut self, port: usize, data: &[u8]) {
            self.m.uart_send(port & 1, data);
        }

        /// What UART `port` has sent since the last call.
        fn uart_take<'py>(&mut self, py: Python<'py>, port: usize) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.m.uart_take(port & 1))
        }

        /// Whether UART `port`'s terminal sends only while RTS is asserted
        /// (it does by default).
        fn uart_flow(&mut self, port: usize, on: bool) {
            self.m.board.uart[port & 1].host_flow = on;
        }

        /// What UART `port`'s terminal still has to send.
        fn uart_pending(&self, port: usize) -> usize {
            self.m.board.uart[port & 1].rx_in.len()
        }

        fn key(&mut self, code: u16, down: bool) {
            self.m.key(code, down);
        }

        /// Bytes the keyboard (0) or the mouse (1) sends, as they are.
        fn ps2_send(&mut self, port: usize, data: &[u8]) {
            self.m.ps2_send(port & 1, data);
        }

        /// What the host has sent the keyboard (0) or the mouse (1).
        fn ps2_received<'py>(&self, py: Python<'py>, port: usize) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.m.board.ps2[port & 1].received)
        }

        /// The mouse moved by (dx, dy), y up, with `buttons` held.
        fn mouse(&mut self, dx: i32, dy: i32, buttons: u8) {
            self.m.mouse(dx, dy, buttons);
        }

        fn press_halt(&mut self) {
            self.m.press_halt();
        }

        fn press_interrupt(&mut self) {
            self.m.press_interrupt();
        }

        fn reset(&mut self) {
            self.m.reset();
        }

        // ---- the picture and the sound

        /// Draw the picture from now on (or stop).
        fn render(&mut self, on: bool) {
            self.m.board.video.render = on;
        }

        /// Frames drawn since power-on.
        #[getter]
        fn frames(&self) -> u64 {
            self.m.board.video.frames
        }

        /// The last frame drawn, 640 x 480 RGB bytes.
        fn screen<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
            self.rgb.clear();
            for &p in &self.m.board.video.shown {
                self.rgb
                    .extend_from_slice(&[(p >> 16) as u8, (p >> 8) as u8, p as u8]);
            }
            PyBytes::new(py, &self.rgb)
        }

        /// The palette: 256 (r, g, b), 6 bits each.
        fn palette(&self) -> Vec<(u8, u8, u8)> {
            self.m
                .board
                .video
                .palette
                .rgb
                .iter()
                .map(|c| (c[0], c[1], c[2]))
                .collect()
        }

        /// Record the sound from now on (or stop).
        fn record_audio(&mut self, on: bool) {
            self.m.record_audio(on);
        }

        /// The sound since the last call: 16-bit samples at `rate` Hz,
        /// little-endian.
        #[pyo3(signature = (rate=44100.0))]
        fn audio_take<'py>(&mut self, py: Python<'py>, rate: f64) -> Bound<'py, PyBytes> {
            let s = self.m.audio_take(rate);
            let b: Vec<u8> = s.iter().flat_map(|x| x.to_le_bytes()).collect();
            PyBytes::new(py, &b)
        }

        /// The samples written to the PCM's latch (the first 4096).
        fn pcm_log<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.m.board.pcm_log)
        }

        // ---- debugging

        fn add_breakpoint(&mut self, pc: u32) {
            self.m.breakpoints.insert(pc);
        }

        fn clear_breakpoints(&mut self) {
            self.m.breakpoints.clear();
        }

        /// Keep every decode from now on: (cycle, tick, address, parcel).
        #[pyo3(signature = (limit=1 << 20))]
        fn keep_decodes(&mut self, limit: usize) {
            self.m.decodes = Some(Vec::new());
            self.m.decode_limit = limit;
        }

        fn decodes(&mut self) -> Vec<(u64, u64, u32, u16)> {
            self.m.decodes.take().unwrap_or_default()
        }

        /// Profile from now on.
        fn keep_profile(&mut self) {
            self.m.profile = Some(Default::default());
        }

        /// The profile: {"words": [(cycles, ticks)] by control store
        /// address, "insns": {address: (executions, ticks)}, "device_task":
        /// (cycles, ticks), "copper": ...}.
        fn profile<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyDict>>> {
            let Some(p) = &self.m.profile else {
                return Ok(None);
            };
            let d = PyDict::new(py);
            let words: Vec<(u64, u64)> = p
                .word_cycles
                .iter()
                .zip(&p.word_ticks)
                .map(|(&c, &t)| (c, t))
                .collect();
            d.set_item("words", words)?;
            d.set_item("insns", p.insns.clone())?;
            d.set_item("device_task", p.device_task)?;
            d.set_item("copper", p.copper)?;
            Ok(Some(d))
        }

        /// The board's counters: the video's underflows and stretched phase
        /// Fs, frames, cycles skipped while waiting, the scanline, the
        /// interrupt sources pending.
        fn stats<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
            let b = &self.m.board;
            let d = PyDict::new(py);
            d.set_item("underflows", b.video.underflows)?;
            d.set_item("stretches", b.video.stretches)?;
            d.set_item("frame_count", b.video.frame_count)?;
            d.set_item("skipped", self.m.skipped)?;
            d.set_item("scanline", b.video.scanline())?;
            d.set_item("sources", b.sources())?;
            d.set_item("dac", b.audio.dac())?;
            d.set_item("sreq", b.sreq)?;
            d.set_item("width", video::WIDTH)?;
            d.set_item("height", video::HEIGHT)?;
            Ok(d)
        }
    }
}
