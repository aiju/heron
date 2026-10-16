//! The I/O processor and its system (studies/iop/sim) for Python:
//! heron.native.iop. studies/iop/run.py drives it.

use pyo3::prelude::*;

#[pymodule]
pub mod iop {
    use iop::cards::{self, Gpio, SERIAL_SLOT, Serial};
    use iop::iop::{Config, Iop, Status};
    use iop::micro;
    use iop::system::{CS_LANES, System as Engine};
    use pyo3::prelude::*;
    use pyo3::types::{PyBytes, PyDict};

    #[pymodule_export]
    use crate::py_v1::SimError;

    /// A microinstruction as text.
    #[pyfunction]
    fn disassemble(word: u64) -> String {
        micro::disassemble(word)
    }

    /// The 74F181 and 182: (F, carry out).
    #[pyfunction]
    fn alu(s: u8, m: bool, cin: bool, a: u16, b: u16) -> (u16, bool) {
        micro::alu(s, m, cin, a, b)
    }

    /// The system: the IOP's card, with `ucode` (six bytes a word,
    /// little-endian, from address 0) and `flash` in its image flash, and a
    /// draft 2 CPU card with `ram_size` bytes at `cpu_hz`, its RUN off.
    #[pyclass]
    struct System {
        s: Engine,
    }

    fn serial(i: &mut Iop) -> Option<&mut Serial> {
        i.io.slots[SERIAL_SLOT]
            .as_mut()
            .and_then(|c| c.as_any().downcast_mut::<Serial>())
    }

    fn status(st: Status) -> &'static str {
        match st {
            Status::Limit => "limit",
            Status::Stopped => "stopped",
            Status::Break => "break",
        }
    }

    impl System {
        fn with_iop<T>(&self, f: impl FnOnce(&Iop) -> T) -> T {
            f(&self.s.iop.lock().unwrap())
        }

        fn with_iop_mut<T>(&mut self, f: impl FnOnce(&mut Iop) -> T) -> T {
            f(&mut self.s.iop.lock().unwrap())
        }
    }

    #[pymethods]
    impl System {
        /// `disk`: a CF card's image, in slot 0; `serial`: the serial card,
        /// two lines, in slot 1; `gpio`: general-purpose I/O cards, in
        /// these slots; `tick`: the CPU card's tick jumper, the timer's
        /// bit (RFC 0040, 3.3: 16), or none.
        #[new]
        #[pyo3(signature = (ucode, flash, ram_size=4 << 20, cpu_hz=6e6, watchdog=false, shared_bytes=2 << 20, reference=None, disk=None, serial=false, gpio=Vec::new(), tick=None))]
        #[allow(clippy::too_many_arguments)]
        fn new(
            ucode: &[u8],
            flash: &[u8],
            ram_size: u32,
            cpu_hz: f64,
            watchdog: bool,
            shared_bytes: usize,
            reference: Option<&str>,
            disk: Option<Vec<u8>>,
            serial: bool,
            gpio: Vec<usize>,
            tick: Option<u32>,
        ) -> PyResult<System> {
            let cfg = Config {
                watchdog,
                shared_bytes,
                ..Config::default()
            };
            let timing = match reference {
                Some(r) => crate::py_v2::v2::config(r)?,
                None => v2_isa::timing::Config::named(v2_isa::timing::REFERENCE).unwrap(),
            };
            let mut iop = Iop::from_rom(cfg, ucode, flash);
            cards::fit(&mut iop, disk, serial, &gpio);
            let mut s = Engine::new(iop, ram_size, cpu_hz, timing);
            s.card().tick_bit = tick;
            Ok(System { s })
        }

        /// Run until the IOP's clock reaches `until` bus clocks: "limit",
        /// "stopped" (the microcode jumped to itself) or "break". Ctrl-C
        /// stops it.
        fn run(&mut self, py: Python<'_>, until: u64) -> PyResult<&'static str> {
            loop {
                let now = self.with_iop(|i| i.clock);
                let chunk = until.min(now + (1 << 20));
                let s = &mut self.s;
                let st = py.detach(|| s.run(chunk)).map_err(SimError::new_err)?;
                if st != Status::Limit || chunk >= until {
                    return Ok(status(st));
                }
                py.check_signals()?;
            }
        }

        /// Bus clocks since power-up.
        #[getter]
        fn clock(&self) -> u64 {
            self.with_iop(|i| i.clock)
        }

        #[getter]
        fn bclk_ns(&self) -> u64 {
            self.with_iop(|i| i.cfg.bclk_ns)
        }

        /// COLD: the IOP and its devices reset.
        fn cold(&mut self) {
            self.with_iop_mut(|i| i.cold())
        }

        /// Bytes a terminal sends on serial line n.
        fn serial_send(&mut self, n: usize, data: &[u8]) {
            self.with_iop_mut(|i| {
                if let Some(c) = serial(i) {
                    c.lines[n & 1].rx_in.extend(data.iter().copied());
                }
            })
        }

        /// What serial line n's terminal has received since the last call.
        fn serial_take<'py>(&mut self, py: Python<'py>, n: usize) -> Bound<'py, PyBytes> {
            let v = self.with_iop_mut(|i| match serial(i) {
                Some(c) => std::mem::take(&mut c.lines[n & 1].tx_out),
                None => Vec::new(),
            });
            PyBytes::new(py, &v)
        }

        /// A GPIO card's inputs, as the world drives them.
        fn gpio_set(&mut self, slot: usize, v: u16) {
            self.with_iop_mut(|i| {
                if let Some(g) =
                    i.io.slots
                        .get_mut(slot)
                        .and_then(|c| c.as_mut())
                        .and_then(|c| c.as_any().downcast_mut::<Gpio>())
                {
                    g.inputs = v;
                }
            })
        }

        /// The CF card's image.
        fn disk<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
            let v = self.with_iop_mut(|i| cards::disk_image(i).unwrap_or_default());
            PyBytes::new(py, &v)
        }

        fn uart_send(&mut self, data: &[u8]) {
            self.with_iop_mut(|i| i.io.uart.rx_in.extend(data.iter().copied()))
        }

        /// Characters the console's terminal has received since the last
        /// call.
        fn uart_take<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
            let v = self.with_iop_mut(|i| std::mem::take(&mut i.io.uart.tx_out));
            PyBytes::new(py, &v)
        }

        /// Characters still waiting to be sent to the IOP.
        #[getter]
        fn uart_pending(&self) -> usize {
            self.with_iop(|i| i.io.uart.rx_in.len())
        }

        /// What the CPU wrote to its card's debug port since the last call.
        fn debug_take<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
            let v = std::mem::take(&mut self.s.card().debug);
            PyBytes::new(py, &v)
        }

        /// SRAM cells.
        fn sram(&self, addr: usize, n: usize) -> Vec<u16> {
            self.with_iop(|i| i.sram[addr.min(0x10000)..(addr + n).min(0x10000)].to_vec())
        }

        fn sram_write(&mut self, addr: usize, data: Vec<u16>) {
            self.with_iop_mut(|i| {
                for (k, v) in data.into_iter().enumerate() {
                    i.sram[(addr + k) & 0xFFFF] = v;
                }
            })
        }

        /// Shared RAM halfwords.
        fn shared(&self, index: usize, n: usize) -> Vec<u16> {
            self.with_iop(|i| {
                let l = i.shared.len();
                i.shared[index.min(l)..(index + n).min(l)].to_vec()
            })
        }

        fn shared_write(&mut self, index: usize, data: Vec<u16>) {
            self.with_iop_mut(|i| {
                let l = i.shared.len();
                for (k, v) in data.into_iter().enumerate() {
                    i.shared[(index + k) % l] = v;
                }
            })
        }

        /// The image flash's contents.
        fn flash<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
            let v = self.with_iop(|i| i.io.flash.bytes());
            PyBytes::new(py, &v)
        }

        /// The core's registers and state.
        fn regs<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
            let d = PyDict::new(py);
            let i = self.s.iop.lock().unwrap();
            d.set_item("upc", i.upc)?;
            d.set_item("cur", i.cur)?;
            d.set_item("f", i.f)?;
            d.set_item("carry", i.carry)?;
            d.set_item("ac", i.ac)?;
            d.set_item("x", i.x)?;
            d.set_item("bank", i.bank)?;
            d.set_item("ah0", i.ah[0])?;
            d.set_item("ah1", i.ah[1])?;
            d.set_item("lc", i.lc)?;
            d.set_item("ctrl", i.ctrl)?;
            d.set_item("ab", i.ab)?;
            d.set_item("ba", i.ba)?;
            d.set_item("tick", i.tick)?;
            d.set_item("doorbells", i.doorbells)?;
            d.set_item("leds", i.io.leds)?;
            d.set_item("stopped", i.stopped)?;
            d.set_item("watchdog_resets", i.watchdog_resets)?;
            Ok(d)
        }

        /// What the IOP did: microinstructions, transfers, stalls.
        fn stats<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
            let d = PyDict::new(py);
            let i = self.s.iop.lock().unwrap();
            d.set_item("clock", i.clock)?;
            d.set_item("micro", i.stats.micro)?;
            d.set_item("transfers", i.stats.transfers)?;
            d.set_item("stall_bus", i.stats.stall_bus)?;
            d.set_item("stall_ba", i.stats.stall_ba)?;
            d.set_item("stall_io", i.stats.stall_io)?;
            d.set_item("io_accesses", i.io.accesses)?;
            Ok(d)
        }

        /// Executions by microaddress: [(address, count)], those run.
        fn counts(&self) -> Vec<(u16, u64)> {
            self.with_iop(|i| {
                i.counts
                    .iter()
                    .enumerate()
                    .filter(|(_, c)| **c > 0)
                    .map(|(a, c)| (a as u16, *c))
                    .collect()
            })
        }

        fn clear_counts(&mut self) {
            self.with_iop_mut(|i| i.counts.iter_mut().for_each(|c| *c = 0))
        }

        /// The last microinstructions run: [(clock, address)].
        fn trace(&self) -> Vec<(u64, u16)> {
            self.with_iop(|i| i.trace.iter().copied().collect())
        }

        #[getter]
        fn breakpoints(&self) -> Vec<u16> {
            self.with_iop(|i| i.breakpoints.clone())
        }

        #[setter]
        fn set_breakpoints(&mut self, b: Vec<u16>) {
            self.with_iop_mut(|i| i.breakpoints = b)
        }

        /// A doorbell rung, as a CPU's write would.
        fn ring(&mut self, n: u32) {
            self.with_iop_mut(|i| {
                i.slave_write(0x7400_0000 + 4 * (n & 15), 4, 0, 0);
            })
        }

        /// LED values written, with their times in ns.
        fn led_log(&self) -> Vec<(u64, u8)> {
            self.with_iop(|i| i.io.led_log.clone())
        }

        // ---- the CPU card

        /// The CPU's state.
        fn cpu<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
            let d = PyDict::new(py);
            let m = &self.s.cpu;
            d.set_item("pc", m.pc)?;
            d.set_item("r", m.r)?;
            d.set_item("cycles", m.cycles)?;
            d.set_item("idle_cycles", m.idle_cycles)?;
            d.set_item("instructions", m.instructions)?;
            let c = self.s.card_ref();
            d.set_item("run", c.run)?;
            d.set_item("halted", c.halted)?;
            d.set_item("irq", c.irq)?;
            d.set_item("msg", format!("{:?}", c.msg).to_lowercase())?;
            d.set_item("msg_value", c.msg_value)?;
            d.set_item("lane_errors", c.lane_errors)?;
            Ok(d)
        }

        /// Levels lowered in the CPU card's interrupt request register, as
        /// a handler's write to its clear address would.
        fn irq_clear(&mut self, bits: u8) {
            self.s.card().irq &= !bits;
        }

        /// The CPU card's message register freed, as the message level's
        /// entry does once it has the message.
        fn msg_release(&mut self) {
            self.s.card().msg = iop::system::Msg::Free;
        }

        /// The CPU card's RAM.
        fn cpu_mem<'py>(&self, py: Python<'py>, pa: u32, n: u32) -> Bound<'py, PyBytes> {
            let mem = &self.s.cpu.mem;
            let a = (pa as usize).min(mem.len());
            let b = (a + n as usize).min(mem.len());
            PyBytes::new(py, &mem[a..b])
        }

        fn cpu_mem_write(&mut self, pa: u32, data: Vec<u8>) {
            let mem = &mut self.s.cpu.mem;
            for (k, v) in data.into_iter().enumerate() {
                if let Some(b) = mem.get_mut(pa as usize + k) {
                    *b = v;
                }
            }
            self.s.cpu.forget_code();
        }

        /// A lane of the CPU card's control store, k = 0-9.
        fn lane(&mut self, k: usize) -> Vec<u16> {
            if k >= CS_LANES {
                return Vec::new();
            }
            self.s.card().lanes[k].clone()
        }

        /// Traps the CPU took: [(pc, what)].
        fn cpu_traps(&self) -> Vec<(u32, String)> {
            self.s.cpu.traps.clone()
        }
    }
}
