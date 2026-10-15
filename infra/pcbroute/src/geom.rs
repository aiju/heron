//! Shapes of copper, in millimetres: rotated rectangles and capsules (a
//! segment swept by a radius: a round pad, a track, a via).

use serde::Deserialize;

/// A piece of copper on some routing layers: a pad, or fixed copper (a
/// track or a via that is already there). KiCad's conventions: y points
/// down, angles turn counter-clockwise on screen.
#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct Shape {
    /// "rect" or "capsule"
    pub kind: String,
    pub cx: f64,
    pub cy: f64,
    /// half width and half height of a rectangle
    pub hw: f64,
    pub hh: f64,
    /// a rectangle's rotation, degrees
    pub angle: f64,
    /// a rectangle's corner radius (KiCad's rounded rectangles)
    pub rr: f64,
    pub x1: f64,
    pub y1: f64,
    pub x2: f64,
    pub y2: f64,
    /// a capsule's radius
    pub r: f64,
    /// the routing layers it is on; empty for all (plated through)
    pub layers: Vec<usize>,
    /// its net (an index into the problem's nets), or -1 for none
    pub net: i64,
    /// a pad: its net's routes may end on it
    pub pad: bool,
}

impl Shape {
    pub fn on(&self, layer: usize) -> bool {
        self.layers.is_empty() || self.layers.contains(&layer)
    }

    /// The bounding box: (x0, y0, x1, y1).
    pub fn bbox(&self) -> (f64, f64, f64, f64) {
        if self.kind == "capsule" {
            (
                self.x1.min(self.x2) - self.r,
                self.y1.min(self.y2) - self.r,
                self.x1.max(self.x2) + self.r,
                self.y1.max(self.y2) + self.r,
            )
        } else {
            let (s, c) = self.angle.to_radians().sin_cos();
            let ex = (self.hw * c).abs() + (self.hh * s).abs();
            let ey = (self.hw * s).abs() + (self.hh * c).abs();
            (self.cx - ex, self.cy - ey, self.cx + ex, self.cy + ey)
        }
    }

    /// The distance from a point to the shape; 0 inside it.
    pub fn dist(&self, x: f64, y: f64) -> f64 {
        if self.kind == "capsule" {
            (seg_dist(x, y, self.x1, self.y1, self.x2, self.y2) - self.r).max(0.0)
        } else {
            // into the rectangle's own axes (the inverse of KiCad's rotation)
            let (s, c) = self.angle.to_radians().sin_cos();
            let (dx, dy) = (x - self.cx, y - self.cy);
            let u = c * dx - s * dy;
            let v = s * dx + c * dy;
            // a rounded rectangle is its inner rectangle swept by the radius
            let rr = self.rr.min(self.hw).min(self.hh).max(0.0);
            let du = (u.abs() - (self.hw - rr)).max(0.0);
            let dv = (v.abs() - (self.hh - rr)).max(0.0);
            (du.hypot(dv) - rr).max(0.0)
        }
    }
}

/// The distance from (px, py) to the segment (x1, y1)-(x2, y2).
pub fn seg_dist(px: f64, py: f64, x1: f64, y1: f64, x2: f64, y2: f64) -> f64 {
    let (vx, vy) = (x2 - x1, y2 - y1);
    let len2 = vx * vx + vy * vy;
    let t = if len2 == 0.0 {
        0.0
    } else {
        (((px - x1) * vx + (py - y1) * vy) / len2).clamp(0.0, 1.0)
    };
    (px - x1 - t * vx).hypot(py - y1 - t * vy)
}
