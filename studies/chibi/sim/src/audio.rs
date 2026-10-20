//! The sound jack: the DAC0832's output (the PCM's samples, as the DAC
//! latch holds them) and the timer's OUT2 (the speaker) mixed, as the
//! levels change, and resampled for the host on request.
//!
//! The analog side is a sketch on the board (RFC 0047, 7); here the DAC
//! gives ±12288 around its middle (0x80), OUT2 ±4096, and a one-pole
//! high-pass at about 20 Hz stands for the jack's coupling capacitor.

use std::collections::VecDeque;

#[derive(Clone, Debug)]
pub struct Audio {
    /// Recording: off, nothing is kept.
    pub on: bool,
    /// The level changes not yet resampled: (tick, level).
    log: VecDeque<(u64, i32)>,
    dac: u8,
    spk: bool,
    /// The level before the log's first change.
    level: i32,
    /// Resampled up to here (ticks).
    pos: u64,
    /// The high-pass's state.
    hp_in: f64,
    hp_out: f64,
}

impl Default for Audio {
    fn default() -> Audio {
        Audio::new()
    }
}

impl Audio {
    pub fn new() -> Audio {
        Audio {
            on: false,
            log: VecDeque::new(),
            dac: 0x80,
            spk: false,
            level: Audio::mix(0x80, false),
            pos: 0,
            hp_in: 0.0,
            hp_out: 0.0,
        }
    }

    fn mix(dac: u8, spk: bool) -> i32 {
        (dac as i32 - 0x80) * 96 + if spk { 4096 } else { -4096 }
    }

    pub fn dac(&self) -> u8 {
        self.dac
    }

    /// The DAC latch's output changed at `t`.
    pub fn set_dac(&mut self, t: u64, v: u8) {
        if v != self.dac {
            self.dac = v;
            self.push(t);
        }
    }

    /// OUT2 changed at `t`.
    pub fn set_speaker(&mut self, t: u64, v: bool) {
        if v != self.spk {
            self.spk = v;
            self.push(t);
        }
    }

    fn push(&mut self, t: u64) {
        let l = Audio::mix(self.dac, self.spk);
        if !self.on {
            self.level = l;
            return;
        }
        self.log.push_back((t, l));
    }

    /// Start or stop recording at `now`.
    pub fn record(&mut self, on: bool, now: u64) {
        if on && !self.on {
            self.log.clear();
            self.level = Audio::mix(self.dac, self.spk);
            self.pos = now;
        }
        self.on = on;
    }

    /// The samples from the last call (or the recording's start) to
    /// `now`, at `rate` Hz with ticks of `tick_s` seconds: each the mean
    /// level over its interval, high-passed.
    pub fn take(&mut self, now: u64, rate: f64, tick_s: f64) -> Vec<i16> {
        let mut out = Vec::new();
        if !self.on || now <= self.pos {
            return out;
        }
        let step = 1.0 / (rate * tick_s);
        let n = ((now - self.pos) as f64 / step) as u64;
        let alpha = 1.0 / (1.0 + 2.0 * std::f64::consts::PI * 20.0 / rate);
        let mut t = self.pos as f64;
        for _ in 0..n {
            let end = t + step;
            // the mean of the piecewise-constant level over [t, end)
            let mut acc = 0.0;
            let mut at = t;
            while let Some(&(ct, l)) = self.log.front() {
                if ct as f64 >= end {
                    break;
                }
                let c = (ct as f64).max(at);
                acc += self.level as f64 * (c - at);
                at = c;
                self.level = l;
                self.log.pop_front();
            }
            acc += self.level as f64 * (end - at);
            let x = acc / step;
            self.hp_out = alpha * (self.hp_out + x - self.hp_in);
            self.hp_in = x;
            out.push(self.hp_out.clamp(-32768.0, 32767.0) as i16);
            t = end;
        }
        self.pos = t as u64;
        out
    }
}
