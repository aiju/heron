//! The draft 1 simulator and timing model (studies/v1_isa/isa) for Python:
//! heron.native.v1. studies/v1_isa/sim32.py wraps the machine in the
//! interface the studies use.

use pyo3::prelude::*;

pyo3::create_exception!(
    v1,
    SimError,
    pyo3::exceptions::PyException,
    "The simulation can't go on."
);

#[pymodule]
pub mod v1 {
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;
    use pyo3::types::{PyBytes, PyDict, PyString, PyTuple};
    use v1_isa::key::{Key, Param};
    use v1_isa::timing::{CONFIGS, Config, REFERENCE};
    use v1_isa::{Isa, Machine as Engine};

    #[pymodule_export]
    use super::SimError;

    /// (instruction address or None, timing key, executions)
    type PcKey<'py> = (Option<u32>, Bound<'py, PyTuple>, u64);

    fn config(name: &str) -> PyResult<Config> {
        Config::named(name)
            .ok_or_else(|| PyValueError::new_err(format!("unknown configuration {name:?}")))
    }

    /// A key as the Python tuple (parcels, pc & 2, kind, *params).
    fn key_tuple<'py>(py: Python<'py>, k: &Key) -> PyResult<Bound<'py, PyTuple>> {
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
    /// configuration (timing32.CONFIG_NAMES).
    #[pyfunction]
    fn cycles(key: &Bound<'_, PyTuple>, config: &str) -> PyResult<u32> {
        Ok(super::v1::config(config)?.cycles(tuple_key(key)?))
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

    /// A draft 1 machine running a program: `isa` is "v1a" or "v1b",
    /// `image` RAM from address 0, `inp` the console input, `reference`
    /// the configuration its own cycle count follows.
    #[pyclass]
    struct Machine {
        m: Engine,
    }

    #[pymethods]
    impl Machine {
        #[new]
        #[pyo3(signature = (isa, image, inp=b"".as_slice(), reference=REFERENCE))]
        fn new(isa: &str, image: &[u8], inp: &[u8], reference: &str) -> PyResult<Machine> {
            let isa = Isa::named(isa)
                .ok_or_else(|| PyValueError::new_err(format!("no draft 1 ISA {isa:?}")))?;
            Ok(Machine {
                m: Engine::new(isa, image, inp, config(reference)?),
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
        /// instruction. A program can use HALT to mark a point for the
        /// tools to look at its state, cycles so far included.
        fn resume(&mut self) {
            self.m.halted = false;
        }

        /// The 16-bit parcel at an address.
        fn parcel(&self, addr: u32) -> PyResult<u32> {
            self.m.parcel(addr).map_err(|e| match e {
                v1_isa::insn::Stop::Error(e) => SimError::new_err(e),
                v1_isa::insn::Stop::Trap(t) => SimError::new_err(t.why),
            })
        }

        #[getter]
        fn r(&self) -> [u32; 16] {
            self.m.r
        }
        /// Set the registers, the PC, HI and the flags (for tests that
        /// start from a given state).
        #[setter]
        fn set_r(&mut self, r: [u32; 16]) {
            self.m.r = r;
        }
        #[setter]
        fn set_pc(&mut self, v: u32) {
            self.m.pc = v;
        }
        #[setter]
        fn set_hi(&mut self, v: u32) {
            self.m.hi = v;
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
        fn hi(&self) -> u32 {
            self.m.hi
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
            Ok(self.m.cycles_for(super::v1::config(config)?, shifted))
        }

        /// {instruction address: cycles spent there} in a configuration,
        /// with None for interrupt entries.
        fn pc_cycles<'py>(&self, py: Python<'py>, config: &str) -> PyResult<Bound<'py, PyDict>> {
            let c = super::v1::config(config)?;
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

        /// v1bs's system state (studies/v1_isa/isa/src/sys.rs) as a dict,
        /// or None for the other ISAs.
        #[getter]
        fn sys<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyDict>>> {
            let Some(s) = self.m.sys.as_deref() else {
                return Ok(None);
            };
            let d = PyDict::new(py);
            d.set_item("s", s.s)?;
            d.set_item("xl", s.xl)?;
            d.set_item("xs", s.xs)?;
            d.set_item("other_sp", s.other_sp)?;
            d.set_item("sysctl", s.sysctl)?;
            d.set_item("bank", s.bank)?;
            d.set_item("ctx", s.ctx)?;
            d.set_item("far", s.far)?;
            d.set_item("fsr", s.fsr)?;
            d.set_item("page_faults", s.page_faults)?;
            d.set_item("map_writes", s.map_writes)?;
            d.set_item("mode_switches", s.mode_switches)?;
            Ok(Some(d))
        }

        /// A map entry of v1bs: context, virtual page number.
        fn map_entry(&self, ctx: usize, vpn: usize) -> PyResult<u32> {
            let s = self
                .m
                .sys
                .as_deref()
                .ok_or_else(|| PyValueError::new_err("not a v1bs machine"))?;
            Ok(s.map[ctx * v1_isa::sys::PAGES + vpn])
        }

        /// A v1bs register bank: r0-r15 and HI.
        fn bank(&self, n: usize) -> PyResult<Vec<u32>> {
            let s = self
                .m
                .sys
                .as_deref()
                .ok_or_else(|| PyValueError::new_err("not a v1bs machine"))?;
            Ok(s.banks[n].to_vec())
        }

        /// Start counting page references, with pages of 2^shift bytes
        /// (studies/v1_isa/isa/src/pages.rs).
        fn start_page_stats(&mut self, shift: u32) {
            self.m.start_page_stats(shift);
        }

        /// The page reference statistics, or None: for each of "fetch",
        /// "data" and "both", the references, first touches, pages and
        /// the LRU stack-distance histogram, and the misses of
        /// direct-mapped caches.
        fn page_stats<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyDict>>> {
            let Some(p) = self.m.pages.as_deref() else {
                return Ok(None);
            };
            let d = PyDict::new(py);
            d.set_item("shift", p.shift)?;
            d.set_item("stores", p.stores)?;
            d.set_item("fetch_page_changes", p.fetch_page_changes)?;
            d.set_item("direct_sizes", v1_isa::pages::DIRECT_SIZES.to_vec())?;
            for (name, l) in [("fetch", &p.fetch), ("data", &p.data), ("both", &p.both)] {
                let e = PyDict::new(py);
                e.set_item("refs", l.refs)?;
                e.set_item("cold", l.cold)?;
                e.set_item("pages", l.pages())?;
                e.set_item("hist", l.hist.clone())?;
                e.set_item("direct", l.direct_misses())?;
                d.set_item(name, e)?;
            }
            Ok(Some(d))
        }
    }
}
