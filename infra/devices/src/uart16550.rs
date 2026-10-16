//! A TL16C550C UART (a PC16550D with auto flow control), with a terminal
//! on the other end of its line.
//!
//! Time is counted in XIN cycles. A bit takes 16 × the divisor of them,
//! and a character 1 start bit, 5 to 8 data bits, an optional parity bit
//! and 1, 1½ or 2 stop bits, as LCR says. Characters move whole: one being
//! sent appears in `tx_out` when its last stop bit has gone, one being
//! received enters RBR or the receive FIFO one character time after the
//! terminal started sending it. A character keeps the length it had when
//! it started; with a divisor of 0 nothing moves at all.
//!
//! The terminal sends `rx_in` back to back, starting each character when
//! the line is idle and, with `host_flow`, only while RTS is asserted. It
//! always asserts CTS, DSR and DCD, never RI, and takes whatever is sent at
//! once. Parity, framing errors and breaks aren't modelled, so the only
//! line status error is overrun.

use std::collections::VecDeque;

const FIFO_SIZE: usize = 16;

// IER
const ERBI: u8 = 0x01;
const ETBEI: u8 = 0x02;
const ELSI: u8 = 0x04;
const EDSSI: u8 = 0x08;

// IIR interrupt identification, highest priority first
const IIR_LINE: u8 = 0x06;
const IIR_DATA: u8 = 0x04;
const IIR_TIMEOUT: u8 = 0x0C;
const IIR_THRE: u8 = 0x02;
const IIR_MODEM: u8 = 0x00;
const IIR_NONE: u8 = 0x01;
const IIR_FIFOS: u8 = 0xC0;

// LCR
const DLAB: u8 = 0x80;

// MCR
const DTR: u8 = 0x01;
const RTS: u8 = 0x02;
const OUT1: u8 = 0x04;
const OUT2: u8 = 0x08;
const LOOP: u8 = 0x10;
const AFE: u8 = 0x20;

// LSR
const DR: u8 = 0x01;
const OE: u8 = 0x02;
const THRE: u8 = 0x20;
const TEMT: u8 = 0x40;

// MSR inputs: CTS, DSR, RI, DCD
const RI: u8 = 0x40;
const TERMINAL_INPUTS: u8 = 0xB0;

/// A TL16C550C and the terminal on its line.
#[derive(Clone, Debug)]
pub struct Uart {
    /// What the terminal will send, in order.
    pub rx_in: VecDeque<u8>,
    /// What the terminal has received.
    pub tx_out: Vec<u8>,
    /// The terminal sends only while RTS is asserted (hardware flow
    /// control). True by default.
    pub host_flow: bool,
    dll: u8,
    dlm: u8,
    ier: u8,
    lcr: u8,
    mcr: u8,
    scr: u8,
    /// FCR bit 0: the FIFOs are on.
    fifo: bool,
    /// FCR bits 7:6: the receive trigger level.
    trigger_bits: u8,
    /// RBR and the receive FIFO (one entry without FIFOs).
    rx: VecDeque<u8>,
    /// THR and the transmit FIFO (one entry without FIFOs).
    tx: VecDeque<u8>,
    /// What RBR reads when there's nothing new.
    rbr: u8,
    /// The transmit shift register: a character and the XIN cycles until
    /// its last stop bit has gone.
    tsr: Option<(u8, u64)>,
    /// A character from the terminal on the line, and the cycles until it
    /// has arrived.
    line: Option<(u8, u64)>,
    /// LSR: overrun error.
    oe: bool,
    /// The THR empty interrupt is pending.
    thre_int: bool,
    /// The character timeout interrupt is pending.
    timeout: bool,
    /// XIN cycles since a character was received or RBR read.
    idle: u64,
    /// Auto-RTS has deasserted RTS.
    rts_hold: bool,
    /// MSR bits 3:0: DCTS, DDSR, TERI, DDCD.
    deltas: u8,
}

impl Default for Uart {
    fn default() -> Uart {
        Uart::new()
    }
}

impl Uart {
    /// A UART after power-on and reset, with an idle terminal. The divisor
    /// latch and the scratch register power on undefined; here they're 0.
    pub fn new() -> Uart {
        let mut u = Uart {
            rx_in: VecDeque::new(),
            tx_out: Vec::new(),
            host_flow: true,
            dll: 0,
            dlm: 0,
            ier: 0,
            lcr: 0,
            mcr: 0,
            scr: 0,
            fifo: false,
            trigger_bits: 0,
            rx: VecDeque::new(),
            tx: VecDeque::new(),
            rbr: 0,
            tsr: None,
            line: None,
            oe: false,
            thre_int: false,
            timeout: false,
            idle: 0,
            rts_hold: false,
            deltas: 0,
        };
        u.reset();
        u
    }

    /// The MR pin: IER, FCR, LCR and MCR to 0, LSR to 0x60, IIR to 0x01,
    /// the FIFOs and shift registers emptied (a character on its way in or
    /// out is lost), the modem status deltas cleared. The divisor latch
    /// and the scratch register keep their values, as on the chip.
    pub fn reset(&mut self) {
        self.ier = 0;
        self.lcr = 0;
        self.mcr = 0;
        self.fifo = false;
        self.trigger_bits = 0;
        self.rx.clear();
        self.tx.clear();
        self.tsr = None;
        self.line = None;
        self.oe = false;
        self.thre_int = false;
        self.timeout = false;
        self.idle = 0;
        self.rts_hold = false;
        self.deltas = 0;
    }

    /// Read register `reg` (A2..A0), with DLAB selecting the divisor latch
    /// at 0 and 1. Reading RBR takes a character, LSR clears OE, MSR the
    /// deltas, and IIR clears a THR empty interrupt that it reports.
    pub fn read(&mut self, reg: u8) -> u8 {
        let dlab = self.lcr & DLAB != 0;
        let v = match reg & 7 {
            0 if dlab => self.dll,
            1 if dlab => self.dlm,
            0 => self.read_rbr(),
            1 => self.ier,
            2 => {
                let id = self.iir();
                if id == IIR_THRE {
                    self.thre_int = false;
                }
                if self.fifo { id | IIR_FIFOS } else { id }
            }
            3 => self.lcr,
            4 => self.mcr,
            5 => {
                let v = self.lsr();
                self.oe = false;
                v
            }
            6 => {
                let v = self.inputs() | self.deltas;
                self.deltas = 0;
                v
            }
            _ => self.scr,
        };
        self.settle();
        v
    }

    /// Write register `reg` (A2..A0), with DLAB selecting the divisor latch
    /// at 0 and 1; 2 is FCR. Writes to LSR and MSR are ignored.
    pub fn write(&mut self, reg: u8, v: u8) {
        let dlab = self.lcr & DLAB != 0;
        match reg & 7 {
            0 if dlab => self.dll = v,
            1 if dlab => self.dlm = v,
            0 => self.write_thr(v),
            1 => self.write_ier(v & 0x0F),
            2 => self.write_fcr(v),
            3 => self.lcr = v,
            4 => self.write_mcr(v & 0x3F),
            7 => self.scr = v,
            _ => {}
        }
        self.settle();
    }

    /// Let `n` XIN cycles pass.
    pub fn clock(&mut self, n: u64) {
        let mut left = n;
        loop {
            self.settle();
            if left == 0 || self.divisor() == 0 {
                return;
            }
            let step = self.next_change().map_or(left, |t| t.min(left));
            if let Some((_, t)) = &mut self.tsr {
                *t -= step;
            }
            if let Some((_, t)) = &mut self.line {
                *t -= step;
            }
            self.idle = self.idle.saturating_add(step);
            left -= step;
        }
    }

    /// The INTR output: an enabled interrupt is pending. (A board usually
    /// gates it with OUT2; this doesn't.)
    pub fn intr(&self) -> bool {
        self.iir() != IIR_NONE
    }

    /// RTS, true when asserted: MCR bit 1, unless auto-RTS has taken it
    /// back or the UART is in loopback.
    pub fn rts(&self) -> bool {
        self.output(RTS) && !(self.mcr & AFE != 0 && self.rts_hold)
    }

    /// DTR, true when asserted.
    pub fn dtr(&self) -> bool {
        self.output(DTR)
    }

    /// OUT1, true when asserted.
    pub fn out1(&self) -> bool {
        self.output(OUT1)
    }

    /// OUT2, true when asserted.
    pub fn out2(&self) -> bool {
        self.output(OUT2)
    }

    /// XIN cycles until the next thing that happens on its own (a
    /// character finishing, or a character timeout), or None if nothing
    /// will. Clocking less than this changes nothing a program can see.
    pub fn next_change(&self) -> Option<u64> {
        if self.divisor() == 0 {
            return None;
        }
        let ct = self.char_time();
        let mut next: Option<u64> = None;
        let mut at = |t: u64| next = Some(next.map_or(t, |n| n.min(t)));
        if let Some((_, t)) = self.tsr {
            at(t);
        }
        if let Some((_, t)) = self.line {
            at(t);
        } else if self.terminal_sends() {
            // (the terminal starts on the next clock)
            at(ct);
        }
        if self.fifo && !self.rx.is_empty() && !self.timeout {
            at((4 * ct).saturating_sub(self.idle));
        }
        next
    }

    fn divisor(&self) -> u64 {
        u16::from_le_bytes([self.dll, self.dlm]) as u64
    }

    /// The XIN cycles of a character, as LCR says now.
    fn char_time(&self) -> u64 {
        let data = 5 + (self.lcr & 3) as u64;
        let parity = ((self.lcr >> 3) & 1) as u64;
        let stop_halves = match (self.lcr & 4 != 0, data) {
            (false, _) => 2,
            (true, 5) => 3,
            (true, _) => 4,
        };
        // in half bits, of 8 baud clocks each
        (2 * (1 + data + parity) + stop_halves) * 8 * self.divisor()
    }

    /// The data bits of a character.
    fn mask(&self) -> u8 {
        0xFF >> (3 - (self.lcr & 3))
    }

    fn capacity(&self) -> usize {
        if self.fifo { FIFO_SIZE } else { 1 }
    }

    fn trigger(&self) -> usize {
        if self.fifo {
            [1, 4, 8, 14][self.trigger_bits as usize]
        } else {
            1
        }
    }

    /// A modem control output: its MCR bit, outside loopback.
    fn output(&self, bit: u8) -> bool {
        self.mcr & (bit | LOOP) == bit
    }

    /// The modem inputs, as MSR bits 7:4 (DCD, RI, DSR, CTS): the
    /// terminal's, or in loopback OUT2, OUT1, DTR and RTS.
    fn inputs(&self) -> u8 {
        let m = self.mcr;
        if m & LOOP != 0 {
            ((m & (OUT1 | OUT2)) << 4) | ((m & DTR) << 5) | ((m & RTS) << 3)
        } else {
            TERMINAL_INPUTS
        }
    }

    fn lsr(&self) -> u8 {
        let mut v = 0;
        if !self.rx.is_empty() {
            v |= DR;
        }
        if self.oe {
            v |= OE;
        }
        if self.tx.is_empty() {
            v |= THRE;
            if self.tsr.is_none() {
                v |= TEMT;
            }
        }
        v
    }

    /// The highest-priority enabled interrupt, as IIR bits 3:0.
    fn iir(&self) -> u8 {
        let on = |bit| self.ier & bit != 0;
        if on(ELSI) && self.oe {
            IIR_LINE
        } else if on(ERBI) && self.rx.len() >= self.trigger() {
            IIR_DATA
        } else if on(ERBI) && self.timeout {
            IIR_TIMEOUT
        } else if on(ETBEI) && self.thre_int {
            IIR_THRE
        } else if on(EDSSI) && self.deltas != 0 {
            IIR_MODEM
        } else {
            IIR_NONE
        }
    }

    fn read_rbr(&mut self) -> u8 {
        if let Some(b) = self.rx.pop_front() {
            self.rbr = b;
        }
        self.idle = 0;
        self.timeout = false;
        self.update_hold();
        self.rbr
    }

    fn write_thr(&mut self, v: u8) {
        self.thre_int = false;
        if self.tx.len() < self.capacity() {
            self.tx.push_back(v);
        } else if !self.fifo {
            // without FIFOs, the unsent character in THR is overwritten;
            // a full FIFO drops the new one
            self.tx[0] = v;
        }
    }

    /// The THR empty interrupt comes up when IER.1 is set while THR is
    /// empty (a rising edge; rewriting IER.1 = 1 doesn't), and goes away
    /// when IER.1 is cleared.
    fn write_ier(&mut self, v: u8) {
        if v & !self.ier & ETBEI != 0 && self.tx.is_empty() {
            self.thre_int = true;
        }
        if self.ier & !v & ETBEI != 0 {
            self.thre_int = false;
        }
        self.ier = v;
    }

    /// FCR: turning the FIFOs on or off empties them; the other bits only
    /// count with bit 0 set. DMA mode (bit 3) does nothing here.
    fn write_fcr(&mut self, v: u8) {
        let had_tx = !self.tx.is_empty();
        let on = v & 1 != 0;
        if on != self.fifo {
            self.rx.clear();
            self.tx.clear();
        }
        self.fifo = on;
        if on {
            if v & 2 != 0 {
                self.rx.clear();
            }
            if v & 4 != 0 {
                self.tx.clear();
            }
            self.trigger_bits = v >> 6;
        }
        if self.rx.is_empty() {
            self.timeout = false;
        }
        if had_tx && self.tx.is_empty() {
            self.thre_int = true;
        }
        self.update_hold();
    }

    /// MCR, and the MSR deltas that follow from it in loopback: DCTS, DDSR
    /// and DDCD on any change of their input, TERI when RI goes off.
    fn write_mcr(&mut self, v: u8) {
        let before = self.inputs();
        self.mcr = v;
        let after = self.inputs();
        self.deltas |= ((before ^ after) >> 4) & 0b1011;
        if before & !after & RI != 0 {
            self.deltas |= 0b0100;
        }
    }

    /// Auto-RTS, kept simple: RTS goes when the receive FIFO (or RBR) holds
    /// the trigger level, and comes back when it's empty. The terminal
    /// looks at RTS before each character, so at most the one already on
    /// the line arrives after that.
    fn update_hold(&mut self) {
        if self.rx.is_empty() {
            self.rts_hold = false;
        } else if self.rx.len() >= self.trigger() {
            self.rts_hold = true;
        }
    }

    /// A character has arrived. A full receive FIFO loses the new one, but
    /// without FIFOs it replaces the unread one in RBR; either way it's an
    /// overrun.
    fn receive(&mut self, b: u8) {
        if self.rx.len() < self.capacity() {
            self.rx.push_back(b);
        } else {
            self.oe = true;
            if !self.fifo {
                self.rx[0] = b;
            }
        }
        // after a timeout, only a read restarts the timer
        if !self.timeout {
            self.idle = 0;
        }
        self.update_hold();
    }

    /// The terminal has a character to send and may send it.
    fn terminal_sends(&self) -> bool {
        self.line.is_none()
            && !self.rx_in.is_empty()
            && self.mcr & LOOP == 0
            && (!self.host_flow || self.rts())
    }

    /// Finish what has run out of time, and start what can start: the
    /// next character from THR, and the terminal's next character. In
    /// loopback the terminal waits.
    fn settle(&mut self) {
        if let Some((b, 0)) = self.tsr {
            self.tsr = None;
            if self.mcr & LOOP != 0 {
                self.receive(b);
            } else {
                self.tx_out.push(b);
            }
        }
        if let Some((b, 0)) = self.line {
            self.line = None;
            self.receive(b);
        }
        if self.divisor() == 0 {
            return;
        }
        if self.tsr.is_none()
            && let Some(b) = self.tx.pop_front()
        {
            self.tsr = Some((b & self.mask(), self.char_time()));
            if self.tx.is_empty() {
                self.thre_int = true;
            }
        }
        if self.terminal_sends()
            && let Some(b) = self.rx_in.pop_front()
        {
            self.line = Some((b & self.mask(), self.char_time()));
        }
        if self.fifo && !self.rx.is_empty() && !self.timeout && self.idle >= 4 * self.char_time() {
            self.timeout = true;
        }
    }
}
