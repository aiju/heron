//! The draft 2 simulator and timing model (studies/v2_isa/isa) for Python:
//! heron.native.v2. studies/v2_isa/sim.py wraps the machine in the
//! interface the studies use, as studies/v1_isa/sim32.py does draft 1's.

use pyo3::prelude::*;

#[pymodule]
pub mod v2 {
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;
    use pyo3::types::{PyBytes, PyDict, PyString, PyTuple};
    use v2_isa::Machine as Engine;
    use v2_isa::key::{Key, Param};
    use v2_isa::timing::{CONFIGS, Config, REFERENCE};

    /// The same exception as draft 1's, so the tools catch both alike.
    #[pymodule_export]
    use crate::py_v1::SimError;

    /// (instruction address or None, timing key, executions)
    type PcKey<'py> = (Option<u32>, Bound<'py, PyTuple>, u64);

    pub(crate) fn config(name: &str) -> PyResult<Config> {
        Config::named(name)
            .ok_or_else(|| PyValueError::new_err(format!("unknown configuration {name:?}")))
    }

    /// A key as the Python tuple (parcels, pc & 2, kind, *params).
    pub(crate) fn key_tuple<'py>(py: Python<'py>, k: &Key) -> PyResult<Bound<'py, PyTuple>> {
        let mut items = vec![
            k.n.into_pyobject(py)?.into_any(),
            k.p2.into_pyobject(py)?.into_any(),
            PyString::new(py, k.kind_name()).into_any(),
        ];
        for p in k.params() {
            items.push(match p {
                Param::Int(i) => i.into_pyobject(py)?.into_any(),
                Param::Str(s) => PyString::new(py, s).into_any(),
            });
        }
        PyTuple::new(py, items)
    }

    fn tuple_key(t: &Bound<'_, PyTuple>) -> PyResult<Key> {
        let bad = || PyValueError::new_err(format!("not a timing key: {t}"));
        if t.len() < 3 {
            return Err(bad());
        }
        let n: i64 = t.get_item(0)?.extract()?;
        let p2: i64 = t.get_item(1)?.extract()?;
        let kind: String = t.get_item(2)?.extract()?;
        let mut strings = Vec::new();
        let mut ints = Vec::new();
        for item in t.iter().skip(3) {
            match item.extract::<i64>() {
                Ok(i) => ints.push(Some(i)),
                Err(_) => {
                    strings.push(item.extract::<String>().map_err(|_| bad())?);
                    ints.push(None);
                }
            }
        }
        let mut s = strings.iter();
        let params: Vec<Param> = ints
            .iter()
            .map(|i| match i {
                Some(i) => Param::Int(*i),
                None => Param::Str(s.next().unwrap()),
            })
            .collect();
        Key::from_parts(n, p2, &kind, &params).ok_or_else(bad)
    }

    /// The cycles an instruction with timing key `key` takes in a
    /// configuration.
    #[pyfunction]
    fn cycles(key: &Bound<'_, PyTuple>, config: &str) -> PyResult<u32> {
        Ok(super::v2::config(config)?.cycles(tuple_key(key)?))
    }

    /// The configurations' names, in order.
    #[pyfunction]
    fn config_names() -> Vec<&'static str> {
        CONFIGS.iter().map(|(n, _)| *n).collect()
    }

    /// The configuration the simulator's own cycle count follows.
    #[pyfunction]
    fn reference() -> &'static str {
        REFERENCE
    }

    /// A draft 2 machine running a program: `image` RAM from address 0,
    /// `inp` the console input, `reference` the configuration its own cycle
    /// count follows.
    #[pyclass]
    struct Machine {
        m: Engine,
    }

    #[pymethods]
    impl Machine {
        #[new]
        #[pyo3(signature = (image, inp=b"".as_slice(), reference=REFERENCE))]
        fn new(image: &[u8], inp: &[u8], reference: &str) -> PyResult<Machine> {
            Ok(Machine {
                m: Engine::new(image, inp, config(reference)?),
            })
        }

        /// Execute one instruction (and take an interrupt if one is due).
        fn step(&mut self) -> PyResult<()> {
            self.m.step().map_err(SimError::new_err)
        }

        /// Run until HALT; more than max_cycles is an error. Ctrl-C stops it.
        #[pyo3(signature = (max_cycles=200_000_000))]
        fn run(&mut self, py: Python<'_>, max_cycles: u64) -> PyResult<()> {
            loop {
                let m = &mut self.m;
                match py.detach(|| m.run_for(max_cycles, 1 << 20)) {
                    Err(e) => return Err(SimError::new_err(e)),
                    Ok(true) => return Ok(()),
                    Ok(false) => py.check_signals()?,
                }
            }
        }

        /// Carry on after a HALT: `run` then continues with the next
        /// instruction.
        fn resume(&mut self) {
            self.m.halted = false;
        }

        /// The 16-bit parcel at an address.
        fn parcel(&self, addr: u32) -> PyResult<u32> {
            self.m.parcel(addr).map_err(|e| match e {
                v2_isa::insn::Stop::Error(e) => SimError::new_err(e),
                v2_isa::insn::Stop::Trap(t) => SimError::new_err(t.why),
                v2_isa::insn::Stop::Wait => SimError::new_err("a console wait"),
            })
        }

        #[getter]
        fn r(&self) -> [u32; 16] {
            self.m.r
        }
        /// Set the registers, the PC and the flags (for tests that start
        /// from a given state).
        #[setter]
        fn set_r(&mut self, r: [u32; 16]) {
            self.m.r = r;
        }
        #[setter]
        fn set_pc(&mut self, v: u32) {
            self.m.pc = v;
        }
        /// The flags as the word MFSR reads: V C Z N I from bit 0.
        #[getter]
        fn flags(&self) -> u32 {
            self.m.flags_word()
        }
        #[setter]
        fn set_flags(&mut self, v: u32) {
            self.m.set_flags_word(v);
        }
        #[getter]
        fn pc(&self) -> u32 {
            self.m.pc
        }
        #[getter]
        fn n(&self) -> u8 {
            self.m.n
        }
        #[getter]
        fn z(&self) -> u8 {
            self.m.z
        }
        #[getter]
        fn c(&self) -> u8 {
            self.m.c
        }
        #[getter]
        fn v(&self) -> u8 {
            self.m.v
        }
        #[getter]
        fn i(&self) -> u8 {
            self.m.i
        }
        #[getter]
        fn halted(&self) -> bool {
            self.m.halted
        }
        #[getter]
        fn cycles(&self) -> u64 {
            self.m.cycles
        }
        #[getter]
        fn instructions(&self) -> u64 {
            self.m.instructions
        }
        #[getter]
        fn irqs(&self) -> u64 {
            self.m.irqs
        }
        #[getter]
        fn min_sp(&self) -> u32 {
            self.m.min_sp
        }
        #[getter]
        fn data_bytes(&self) -> u64 {
            self.m.data_bytes
        }
        #[getter]
        fn in_trap(&self) -> bool {
            self.m.in_trap
        }
        /// Traps taken, all but SWI: [(pc, what)].
        #[getter]
        fn traps(&self) -> Vec<(u32, String)> {
            self.m.traps.clone()
        }
        /// All of RAM.
        #[getter]
        fn mem<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.m.mem)
        }
        /// What the program wrote to the console.
        #[getter]
        fn out<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.m.dev.out)
        }

        /// Executions per (instruction address, timing key): [(pc, key,
        /// count)], with pc None for interrupt entries.
        fn pc_keys<'py>(&self, py: Python<'py>) -> PyResult<Vec<PcKey<'py>>> {
            self.m
                .pc_keys()
                .iter()
                .map(|(pc, k, n)| Ok((*pc, key_tuple(py, k)?, *n)))
                .collect()
        }

        /// Cycles in a configuration; `shifted` costs the program as if all
        /// its code sat one parcel further on.
        #[pyo3(signature = (config, shifted=false))]
        fn cycles_for(&self, config: &str, shifted: bool) -> PyResult<u64> {
            Ok(self.m.cycles_for(super::v2::config(config)?, shifted))
        }

        /// {instruction address: cycles spent there} in a configuration,
        /// with None for interrupt entries.
        fn pc_cycles<'py>(&self, py: Python<'py>, config: &str) -> PyResult<Bound<'py, PyDict>> {
            let c = super::v2::config(config)?;
            let out = PyDict::new(py);
            for (pc, k, n) in self.m.pc_keys() {
                let prev: u64 = match out.get_item(pc)? {
                    Some(v) => v.extract()?,
                    None => 0,
                };
                out.set_item(pc, prev + n * c.cycles(k) as u64)?;
            }
            Ok(out)
        }
    }

    /// The board behind a `SysMachine`: RAM is the machine's own; beyond
    /// it, only a console at physical 0x7FFF_FF00 (0xFFFF_FF00 through the
    /// window): a byte written there goes out. No interrupts.
    struct ConsoleBus {
        out: Vec<u8>,
    }

    const CONSOLE_PA: u32 = 0x7FFF_FF00;

    impl v2_isa::sys::Bus for ConsoleBus {
        fn read(&mut self, pa: u32, _size: u32, _cycles: u64) -> Option<u32> {
            (pa & !3 == CONSOLE_PA).then_some(0xFFFF_FFFF)
        }

        fn write(&mut self, pa: u32, _size: u32, value: u32, _cycles: u64) -> bool {
            if pa & !3 != CONSOLE_PA {
                return false;
            }
            self.out.push(value as u8);
            true
        }

        fn irq(&mut self, _cycles: u64) -> (u8, u64) {
            (0, u64::MAX)
        }
    }

    /// Draft 2 in system mode (RFC 0029, `Machine::new_system`) on a plain
    /// board: `ram_size` bytes of RAM from physical 0 and a console, no
    /// interrupts. A reference for a CPU's system half: set its state, run
    /// it an instruction at a time, read its state back.
    #[pyclass]
    struct SysMachine {
        m: Engine,
    }

    #[pymethods]
    impl SysMachine {
        #[new]
        #[pyo3(signature = (ram_size=4 << 20))]
        fn new(ram_size: u32) -> PyResult<SysMachine> {
            let bus = Box::new(ConsoleBus { out: Vec::new() });
            Ok(SysMachine {
                m: Engine::new_system(ram_size, bus, config(REFERENCE)?),
            })
        }

        /// Write bytes into RAM at a physical address.
        fn load(&mut self, pa: u32, data: &[u8]) -> PyResult<()> {
            let a = pa as usize;
            if a + data.len() > self.m.mem.len() {
                return Err(PyValueError::new_err("outside RAM"));
            }
            self.m.mem[a..a + data.len()].copy_from_slice(data);
            Ok(())
        }

        /// RAM, physical from 0.
        fn mem<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.m.mem)
        }

        /// Run at most `steps` instructions: "steps" when they ran out,
        /// "halted" (HALT, I clear), "idle" (HALT waiting, nothing to wake
        /// it), or the simulation's error.
        fn run(&mut self, steps: u64) -> String {
            match self.m.run_system(u64::MAX, steps) {
                Ok(v2_isa::RunStatus::Halted) => "halted".into(),
                Ok(v2_isa::RunStatus::Idle) => "idle".into(),
                Ok(_) => "steps".into(),
                Err(e) => e,
            }
        }

        /// The registers in use (the current bank's).
        fn r(&self) -> [u32; 16] {
            self.m.r
        }

        fn set_r(&mut self, r: [u32; 16]) {
            self.m.r = r;
        }

        #[getter]
        fn pc(&self) -> u32 {
            self.m.pc
        }

        #[setter]
        fn set_pc(&mut self, v: u32) {
            self.m.pc = v;
        }

        /// sr, as MFSR reads it.
        fn sr(&self) -> u32 {
            self.m.sr()
        }

        /// Set sr whole, S too, and switch to the bank its mode runs in.
        fn set_sr(&mut self, x: u32) {
            use v2_isa::sys::{SR_I, SR_IPL_SHIFT, SR_S, SR_T};
            self.m.set_ccr(x);
            self.m.i = ((x & SR_I) != 0) as u8;
            let s = self.m.sys_mut();
            s.t = ((x & SR_T) != 0) as u8;
            s.ipl = ((x >> SR_IPL_SHIFT) & 15) as u8;
            s.supervisor = x & SR_S != 0;
            s.forget_pc_page();
            let to = if s.supervisor { 0 } else { s.bank as usize };
            self.m.switch_bank(to);
        }

        /// far, fsr, ctx, mapa and bank.
        fn sysregs<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
            let s = self.m.sys();
            let d = PyDict::new(py);
            for (k, v) in [
                ("far", s.far),
                ("fsr", s.fsr),
                ("ctx", s.ctx),
                ("mapa", s.mapa),
                ("bank", s.bank),
            ] {
                d.set_item(k, v)?;
            }
            Ok(d)
        }

        /// Set one of far, fsr, ctx, mapa and bank (bank: user mode's; the
        /// registers in use stay).
        fn set_sysreg(&mut self, name: &str, v: u32) -> PyResult<()> {
            let s = self.m.sys_mut();
            match name {
                "far" => s.far = v,
                "fsr" => s.fsr = v,
                "ctx" => s.ctx = v % v2_isa::sys::CONTEXTS as u32,
                "mapa" => s.mapa = v % v2_isa::sys::MAP_SIZE as u32,
                "bank" => s.bank = v % v2_isa::sys::BANKS as u32,
                _ => return Err(PyValueError::new_err(format!("no special register {name}"))),
            }
            s.forget_pc_page();
            Ok(())
        }

        /// The page map's entry at context x 4096 + page.
        fn map(&self, index: usize) -> u32 {
            self.m.sys().map[index % v2_isa::sys::MAP_SIZE]
        }

        fn set_map(&mut self, index: usize, entry: u32) {
            let s = self.m.sys_mut();
            s.map[index % v2_isa::sys::MAP_SIZE] = entry & v2_isa::sys::PTE_MASK;
            s.forget_pc_page();
        }

        /// Bank n's r0-r15 (the registers in use, if n is theirs).
        fn bank_regs(&self, n: usize) -> [u32; 16] {
            let s = self.m.sys();
            if s.cur_bank == n {
                self.m.r
            } else {
                s.banks[n % v2_isa::sys::BANKS]
            }
        }

        fn set_bank_regs(&mut self, n: usize, regs: [u32; 16]) {
            let cur = self.m.sys().cur_bank;
            if cur == n {
                self.m.r = regs;
            } else {
                self.m.sys_mut().banks[n % v2_isa::sys::BANKS] = regs;
            }
        }

        /// What went to the console.
        fn out<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
            let b = self
                .m
                .sys_mut()
                .bus_as::<ConsoleBus>()
                .map(|b| b.out.clone())
                .unwrap_or_default();
            PyBytes::new(py, &b)
        }

        /// Traps taken (but SWIs): (pc, what).
        fn traps(&self) -> Vec<(u32, String)> {
            self.m.traps.clone()
        }

        /// Exceptions taken, by vector offset / 4 (SWIs all at 0x40).
        fn exceptions(&self) -> Vec<u64> {
            self.m.sys().exceptions.to_vec()
        }

        #[getter]
        fn instructions(&self) -> u64 {
            self.m.instructions
        }

        #[getter]
        fn waiting(&self) -> bool {
            self.m.sys().waiting
        }
    }
}
