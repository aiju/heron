//! Piecewise-linear functions: the IBIS tables in voltage, and waveforms
//! in time.

/// A table of (x, y) points with x increasing. Beyond its ends it carries
/// on along the first and last segments, as ngspice's pwl() does.
#[derive(Debug, Clone)]
pub struct Pwl {
    x: Vec<f64>,
    y: Vec<f64>,
}

impl Pwl {
    pub fn new(points: &[(f64, f64)]) -> Result<Pwl, String> {
        if points.is_empty() {
            return Err("empty table".into());
        }
        let mut x = Vec::with_capacity(points.len());
        let mut y = Vec::with_capacity(points.len());
        for &(px, py) in points {
            if !px.is_finite() || !py.is_finite() {
                return Err(format!("table point ({px}, {py}) isn't finite"));
            }
            if let Some(&last) = x.last()
                && px <= last
            {
                return Err(format!("table x values must increase ({px} after {last})"));
            }
            x.push(px);
            y.push(py);
        }
        Ok(Pwl { x, y })
    }

    /// The segment that holds `v`: index i with x[i] ≤ v < x[i+1], clamped
    /// to the first and last segment.
    fn segment(&self, v: f64) -> usize {
        let n = self.x.len();
        if n < 2 {
            return 0;
        }
        // partition_point: the first index with x > v
        let p = self.x.partition_point(|&xi| xi <= v);
        p.saturating_sub(1).min(n - 2)
    }

    /// Value and slope at `v`, extended linearly beyond the ends.
    pub fn eval(&self, v: f64) -> (f64, f64) {
        if self.x.len() == 1 {
            return (self.y[0], 0.0);
        }
        let i = self.segment(v);
        let slope = (self.y[i + 1] - self.y[i]) / (self.x[i + 1] - self.x[i]);
        (self.y[i] + slope * (v - self.x[i]), slope)
    }

    /// Value at time `t`, held constant before the first and after the
    /// last point (a SPICE PWL source).
    pub fn at(&self, t: f64) -> f64 {
        let n = self.x.len();
        if t <= self.x[0] {
            return self.y[0];
        }
        if t >= self.x[n - 1] {
            return self.y[n - 1];
        }
        self.eval(t).0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extends_along_end_segments() {
        let p = Pwl::new(&[(0.0, 0.0), (1.0, 1.0), (2.0, 4.0)]).unwrap();
        assert_eq!(p.eval(-2.0), (-2.0, 1.0));
        assert_eq!(p.eval(0.5), (0.5, 1.0));
        assert_eq!(p.eval(1.5), (2.5, 3.0));
        assert_eq!(p.eval(4.0), (10.0, 3.0));
        assert_eq!(p.at(-1.0), 0.0);
        assert_eq!(p.at(9.0), 4.0);
    }

    #[test]
    fn rejects_unsorted() {
        assert!(Pwl::new(&[(0.0, 0.0), (0.0, 1.0)]).is_err());
    }
}
