//! A display, a keyboard and a mouse for the draft 1 machine: a hack for
//! studies/egret_gui, not a proposal (RFC 0016 is the video proposal).
//!
//! The frame buffer is VRAM_SIZE bytes at VRAM_BASE, outside the 1 MB of
//! RAM, as on a card: 640 x 480 pixels, `pitch` bytes a row, at 1, 2, 4 or
//! 8 bits per pixel, the first pixel of a byte in its low bits (as
//! studies/graphics draws them). Whoever shows it (the frontend) reads
//! VRAM, the mode and the palette.
//!
//! I/O page, after the console and the timer (32-bit registers):
//!   +20  R: the next input event, or -1 (reading takes it)
//!   +24  R: the mouse: x | y << 16
//!   +28  R: the mouse buttons (bit 0 left, 1 right, 2 middle) | modifiers << 8
//!   +2C  R/W: the mode: log2 of the bits per pixel (0-3)
//!   +30  R/W: the palette index (writing +34 moves it on)
//!   +34  R/W: the palette entry at the index, 0xRRGGBB
//!   +38  R: the time of day in seconds, as the frontend last set it
//!   +3C  R/W: the mouse pointer's shape: 0 arrow, 1 text, 2 crosshair,
//!        3 busy, 4 move, 5 hand, 6 none (the frontend draws it)
//!
//! An input event is a word, its kind in bits 31-28:
//!   key down 1, key up 2:  kind << 28 | modifiers << 16 | code
//!   button down 3, up 4:   kind << 28 | button << 24 | y << 12 | x
//!   wheel 5:               kind << 28 | (delta & 0xFFFF), +1 = down a notch
//! Codes are ASCII, with 8 backspace, 9 tab, 13 return, 27 escape, 127
//! delete, and 0x100 on: left, right, up, down, home, end, page up, page
//! down. Modifiers: 1 shift, 2 control, 4 alt, 8 meta.

use std::collections::VecDeque;

pub const VRAM_BASE: u32 = 0x0100_0000;
pub const VRAM_SIZE: u32 = 0x10_0000;
pub const WIDTH: u32 = 640;
pub const HEIGHT: u32 = 480;
const MAX_EVENTS: usize = 256;

pub struct Display {
    pub vram: Vec<u8>,
    pub depth: u32,
    pub palette: [u32; 256],
    pub pal_index: u32,
    pub events: VecDeque<u32>,
    pub mouse_x: u32,
    pub mouse_y: u32,
    pub buttons: u32,
    pub time_of_day: u32,
    pub pointer: u32,
    /// VRAM was written since the frontend last looked.
    pub dirty: bool,
}

impl Default for Display {
    fn default() -> Display {
        Display {
            vram: vec![0; VRAM_SIZE as usize],
            depth: 3,
            palette: [0; 256],
            pal_index: 0,
            events: VecDeque::new(),
            mouse_x: 0,
            mouse_y: 0,
            buttons: 0,
            time_of_day: 0,
            pointer: 0,
            dirty: true,
        }
    }
}

impl Display {
    /// Bytes per row in the current mode.
    pub fn pitch(&self) -> u32 {
        (WIDTH << self.depth) / 8
    }

    /// Queue an input event; when the queue is full the event is lost.
    pub fn push_event(&mut self, e: u32) {
        if self.events.len() < MAX_EVENTS {
            self.events.push_back(e);
        }
    }

    pub fn read(&mut self, reg: u32) -> u32 {
        match reg {
            0x20 => self.events.pop_front().unwrap_or(0xFFFF_FFFF),
            0x24 => self.mouse_x | self.mouse_y << 16,
            0x28 => self.buttons,
            0x2C => self.depth,
            0x30 => self.pal_index,
            0x34 => self.palette[self.pal_index as usize],
            0x38 => self.time_of_day,
            0x3C => self.pointer,
            _ => 0,
        }
    }

    pub fn write(&mut self, reg: u32, value: u32) {
        match reg {
            0x2C => {
                self.depth = value & 3;
                self.dirty = true;
            }
            0x30 => self.pal_index = value & 0xFF,
            0x34 => {
                self.palette[self.pal_index as usize] = value & 0xFF_FFFF;
                self.pal_index = (self.pal_index + 1) & 0xFF;
                self.dirty = true;
            }
            0x3C => self.pointer = value,
            _ => {}
        }
    }

    /// The screen as 0xRRGGBB pixels, row by row.
    pub fn rgb(&self) -> Vec<u32> {
        let mut out = Vec::with_capacity((WIDTH * HEIGHT) as usize);
        self.rgb_into(&mut out);
        out
    }

    pub fn rgb_into(&self, out: &mut Vec<u32>) {
        out.clear();
        let bpp = 1u32 << self.depth;
        let mask = (1u32 << bpp) - 1;
        let pitch = self.pitch() as usize;
        for y in 0..HEIGHT as usize {
            let row = &self.vram[y * pitch..(y + 1) * pitch];
            for x in 0..WIDTH {
                let bit = x * bpp;
                let v = (row[(bit / 8) as usize] as u32 >> (bit % 8)) & mask;
                out.push(self.palette[v as usize]);
            }
        }
    }
}
