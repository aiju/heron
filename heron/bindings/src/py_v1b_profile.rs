//! The instruction profiles (studies/v1b_profile/collect) for Python:
//! heron.native.v1b_profile. A profile attaches to a heron.native.v1
//! Machine as its observer, so it sees every instruction whoever runs the
//! machine executes; studies/v1b_profile/collect.py stores the results.

use pyo3::prelude::*;

#[pymodule]
pub mod v1b_profile {
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;
    use pyo3::types::{PyDict, PyList, PyTuple};

    use crate::py_v1::v1::{Machine, key_tuple};
    use crate::py_v1b_rtl::v1b_rtl::Rom;
    use v1b_profile::{HW_UNKNOWN, Profile};

    fn profile(m: &Machine) -> PyResult<&Profile> {
        let obs =
            m.m.observer
                .as_deref()
                .ok_or_else(|| PyValueError::new_err("no profile attached to this machine"))?;
        let any: &dyn std::any::Any = obs;
        any.downcast_ref::<Profile>()
            .ok_or_else(|| PyValueError::new_err("the machine's observer isn't a profile"))
    }

    /// Attach a profile to a machine. With `rom` (heron.native.v1b_rtl.Rom)
    /// the hardware shadow times every instruction, and with `check` also
    /// compares its results with the simulator's.
    #[pyfunction]
    #[pyo3(signature = (machine, rom=None, check=true))]
    fn start(
        mut machine: PyRefMut<'_, Machine>,
        rom: Option<PyRef<'_, Rom>>,
        check: bool,
    ) -> PyResult<()> {
        let p = Profile::new(machine.m.isa, rom.map(|r| r.rom.clone()), check)
            .map_err(PyValueError::new_err)?;
        machine.m.observer = Some(Box::new(p));
        Ok(())
    }

    /// Detach the profile (the machine runs at full speed again).
    #[pyfunction]
    fn stop(mut machine: PyRefMut<'_, Machine>) {
        machine.m.observer = None;
    }

    /// The profile's results as a dict of lists of tuples (see
    /// studies/v1b_profile/collect.py, which stores them).
    #[pyfunction]
    fn results<'py>(py: Python<'py>, machine: PyRef<'py, Machine>) -> PyResult<Bound<'py, PyDict>> {
        let p = profile(&machine)?;
        let d = PyDict::new(py);
        let opt = |v: u32, ok: bool| ok.then_some(v);
        let insns = PyList::empty(py);
        for (i, s) in p.insns.iter().enumerate() {
            let parcels: Vec<u16> = s.parcels[..s.n as usize].to_vec();
            let mem_range = s.mem_min <= s.mem_max;
            let row = (
                (i, s.pc, s.phys, s.version, parcels),
                (s.count, s.irqs, s.traps),
                (s.reg_defs, s.reg_defs_used),
                (s.flag_defs, s.flag_defs_used),
                (
                    s.mem,
                    s.mem_io,
                    s.mem_other,
                    opt(s.mem_min, mem_range),
                    opt(s.mem_max, mem_range),
                ),
                (s.first, s.mismatches, s.hw_illegal),
                (s.uses.reads, s.uses.writes, s.uses.freads, s.uses.fwrites),
            );
            insns.append(row.into_pyobject(py)?)?;
        }
        d.set_item("insns", insns)?;
        let keys = PyList::empty(py);
        for (i, s) in p.insns.iter().enumerate() {
            for k in &s.keys {
                let hw = (k.hw != HW_UNKNOWN).then_some(k.hw);
                let row = PyTuple::new(
                    py,
                    [
                        i.into_pyobject(py)?.into_any(),
                        key_tuple(py, &k.key)?.into_any(),
                        hw.into_pyobject(py)?.into_any(),
                        k.count.into_pyobject(py)?.into_any(),
                        k.model.into_pyobject(py)?.into_any(),
                    ],
                )?;
                keys.append(row)?;
            }
        }
        d.set_item("keys", keys)?;
        let edges: Vec<_> = p
            .edges
            .iter()
            .map(|(&(f, t, k), &n)| (f, t, k, n))
            .collect();
        d.set_item("edges", edges)?;
        let flags: Vec<_> = p
            .flag_pairs
            .iter()
            .map(|(&(w, r, m), &n)| (w, r, m, n))
            .collect();
        d.set_item("flag_pairs", flags)?;
        let regs: Vec<_> = p
            .reg_pairs
            .iter()
            .map(|(&(w, r, g), &(n, s))| (w, r, g, n, s))
            .collect();
        d.set_item("reg_pairs", regs)?;
        d.set_item("dist", p.dist.to_vec())?;
        let funcs: Vec<_> = p
            .functions()
            .into_iter()
            .map(|(t, f)| (t, f.calls, f.incl))
            .collect();
        d.set_item("funcs", funcs)?;
        d.set_item("steps", p.steps)?;
        d.set_item("totals", p.now)?;
        d.set_item("irqs", p.irqs)?;
        d.set_item("irq_hw", p.irq_hw)?;
        d.set_item("irq_model", p.irq_model)?;
        d.set_item("hw_unknown", p.hw_unknown)?;
        d.set_item("mismatches", p.mismatches)?;
        d.set_item("shadow_errors", p.shadow_errors)?;
        d.set_item("fetch_faults", p.fetch_faults)?;
        d.set_item("shadow", p.has_shadow())?;
        d.set_item("notes", p.notes.clone())?;
        Ok(d)
    }
}
