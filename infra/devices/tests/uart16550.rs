//! The TL16C550C model: timing, FIFOs, interrupts, flow control and
//! loopback, against the datasheet.

use devices::uart16550::Uart;

const RBR: u8 = 0;
const IER: u8 = 1;
const IIR: u8 = 2;
const FCR: u8 = 2;
const LCR: u8 = 3;
const MCR: u8 = 4;
const LSR: u8 = 5;
const MSR: u8 = 6;
const SCR: u8 = 7;

/// XIN cycles per character at divisor 1, 8N1: 10 bits of 16.
const CHAR: u64 = 160;

/// A UART at divisor 1 with line control `lcr`.
fn uart(lcr: u8) -> Uart {
    let mut u = Uart::new();
    u.write(LCR, 0x80);
    u.write(0, 1);
    u.write(1, 0);
    u.write(LCR, lcr);
    u
}

#[test]
fn reset_values() {
    let mut u = Uart::new();
    u.write(SCR, 0x5A);
    u.write(LCR, 0x83);
    u.write(0, 12);
    u.write(IER, 0x0F);
    u.write(MCR, 0x1F);
    u.reset();
    assert_eq!(u.read(IER), 0);
    assert_eq!(u.read(IIR), 0x01);
    assert_eq!(u.read(LCR), 0);
    assert_eq!(u.read(MCR), 0);
    assert_eq!(u.read(LSR), 0x60);
    assert_eq!(u.read(MSR), 0xB0);
    assert!(!u.intr() && !u.rts() && !u.dtr() && !u.out1() && !u.out2());
    // the scratch register and divisor latch survive MR
    assert_eq!(u.read(SCR), 0x5A);
    u.write(LCR, 0x80);
    assert_eq!(u.read(0), 12);
}

#[test]
fn divisor_latch() {
    let mut u = Uart::new();
    u.write(LCR, 0x80);
    u.write(0, 0x34);
    u.write(1, 0x12);
    assert_eq!((u.read(0), u.read(1)), (0x34, 0x12));
    u.write(LCR, 0x03);
    // DLAB off: IER, not DLM
    assert_eq!(u.read(IER), 0);
    u.write(IER, 0xFF);
    assert_eq!(u.read(IER), 0x0F);
    u.write(LCR, 0x83);
    assert_eq!(u.read(1), 0x12);
    // at 8N1, a character is 10 bits of 16 x 0x1234 cycles
    u.write(LCR, 0x03);
    u.write(RBR, b'x');
    assert_eq!(u.next_change(), Some(160 * 0x1234));
    // a divisor of 0 stops the line
    u.write(LCR, 0x80);
    u.write(0, 0);
    u.write(1, 0);
    u.write(LCR, 0x03);
    assert_eq!(u.next_change(), None);
    u.clock(1 << 40);
    assert!(u.tx_out.is_empty());
}

#[test]
fn transmit_timing() {
    let mut u = uart(0x03);
    assert_eq!(u.read(LSR), 0x60);
    u.write(RBR, b'A');
    // straight into the shift register: THR empty, transmitter not
    assert_eq!(u.read(LSR), 0x20);
    assert_eq!(u.next_change(), Some(CHAR));
    u.clock(CHAR - 1);
    assert!(u.tx_out.is_empty());
    u.clock(1);
    assert_eq!(u.tx_out, b"A");
    assert_eq!(u.read(LSR), 0x60);
    // two characters: the second waits in THR
    u.write(RBR, b'B');
    u.write(RBR, b'C');
    assert_eq!(u.read(LSR), 0x00);
    u.clock(CHAR);
    assert_eq!(u.read(LSR), 0x20);
    u.clock(CHAR);
    assert_eq!(u.tx_out, b"ABC");
    assert_eq!(u.read(LSR), 0x60);
}

#[test]
fn character_lengths() {
    // 5 bits, 1.5 stop bits: 7.5 bits; data masked to 5 bits
    let mut u = uart(0x04);
    u.write(RBR, 0xFF);
    assert_eq!(u.next_change(), Some(120));
    u.clock(120);
    assert_eq!(u.tx_out, [0x1F]);
    // 7 bits, parity, 2 stop bits: 11 bits
    let mut u = uart(0x0E);
    u.write(RBR, 0xFF);
    assert_eq!(u.next_change(), Some(176));
    u.clock(176);
    assert_eq!(u.tx_out, [0x7F]);
    // 6 bits, 2 stop bits: 9 bits
    let mut u = uart(0x05);
    u.write(RBR, 0xFF);
    u.clock(143);
    assert!(u.tx_out.is_empty());
    u.clock(1);
    assert_eq!(u.tx_out, [0x3F]);
}

#[test]
fn thr_empty_interrupt() {
    let mut u = uart(0x03);
    assert!(!u.intr());
    // enabling it with THR empty raises it
    u.write(IER, 0x02);
    assert!(u.intr());
    assert_eq!(u.read(IIR), 0x02);
    // reading IIR cleared it
    assert!(!u.intr());
    assert_eq!(u.read(IIR), 0x01);
    // writing THR clears it; it comes back when THR empties
    u.write(RBR, 1);
    u.write(RBR, 2);
    assert!(!u.intr());
    u.clock(CHAR);
    assert!(u.intr());
    // writing THR clears it too
    u.write(RBR, 3);
    assert!(!u.intr());
    // rewriting IER with ETBEI already set doesn't raise it again, but
    // turning it off and on does
    u.clock(2 * CHAR);
    assert_eq!(u.read(IIR), 0x02);
    u.write(IER, 0x02);
    assert!(!u.intr());
    u.write(IER, 0x00);
    u.write(IER, 0x02);
    assert!(u.intr());
}

#[test]
fn transmit_fifo() {
    let mut u = uart(0x03);
    u.write(FCR, 0x01);
    for b in 0..20u8 {
        u.write(RBR, b);
    }
    // one in the shift register, 16 in the FIFO, the rest dropped
    assert_eq!(u.read(LSR) & 0x60, 0);
    u.clock(100 * CHAR);
    assert_eq!(u.tx_out, (0..17).collect::<Vec<u8>>());
    // FCR bit 2 empties the transmit FIFO but not the shift register
    for b in 0..5u8 {
        u.write(RBR, b);
    }
    u.write(FCR, 0x05);
    assert_eq!(u.read(LSR), 0x20);
    u.clock(10 * CHAR);
    assert_eq!(u.tx_out.len(), 18);
    assert_eq!(u.read(LSR), 0x60);
}

#[test]
fn receive_fifo_trigger_and_timeout() {
    let mut u = uart(0x03);
    u.write(FCR, 0x81); // FIFOs on, trigger level 8
    u.write(MCR, 0x02); // RTS, so the terminal sends
    u.write(IER, 0x01);
    u.rx_in.extend(b"0123456789");
    assert_eq!(u.read(IIR), 0xC1);
    assert_eq!(u.next_change(), Some(CHAR));
    u.clock(7 * CHAR);
    assert_eq!(u.read(LSR), 0x61);
    assert!(!u.intr());
    u.clock(CHAR);
    assert_eq!(u.read(IIR), 0xC4);
    // below the trigger level again: no interrupt
    assert_eq!(u.read(RBR), b'0');
    assert_eq!(u.read(IIR), 0xC1);
    u.clock(2 * CHAR);
    assert_eq!(u.read(IIR), 0xC4);
    for &b in b"12" {
        assert_eq!(u.read(RBR), b);
    }
    // 7 left, none coming: a timeout 4 character times after the last
    // character arrived (the reads above restart the timer too)
    assert_eq!(u.next_change(), Some(4 * CHAR));
    u.clock(4 * CHAR - 1);
    assert_eq!(u.read(IIR), 0xC1);
    u.clock(1);
    assert_eq!(u.read(IIR), 0xCC);
    // a read clears it and restarts the timer
    assert_eq!(u.read(RBR), b'3');
    assert_eq!(u.read(IIR), 0xC1);
    u.clock(4 * CHAR);
    assert_eq!(u.read(IIR), 0xCC);
    for &b in b"456789" {
        assert_eq!(u.read(RBR), b);
    }
    assert_eq!(u.read(IIR), 0xC1);
    assert_eq!(u.read(LSR), 0x60);
    assert_eq!(u.next_change(), None);
}

#[test]
fn trigger_levels() {
    for (fcr, level) in [(0x01, 1), (0x41, 4), (0x81, 8), (0xC1, 14)] {
        let mut u = uart(0x03);
        u.host_flow = false;
        u.write(FCR, fcr);
        u.write(IER, 0x01);
        u.rx_in.extend([0; 16]);
        u.clock((level - 1) * CHAR);
        assert!(!u.intr(), "level {level}");
        u.clock(CHAR);
        assert!(u.intr(), "level {level}");
    }
}

#[test]
fn auto_rts_stops_the_terminal() {
    let mut u = uart(0x03);
    u.write(FCR, 0x41); // trigger level 4
    u.write(MCR, 0x22); // AFE and RTS
    assert!(u.rts());
    u.rx_in.extend(0..20u8);
    u.clock(100 * CHAR);
    // RTS went when the 4th character arrived, so the 5th never started
    assert!(!u.rts());
    assert_eq!(u.rx_in.len(), 16);
    assert_eq!(u.read(LSR), 0x61);
    // it comes back when the FIFO is empty, not before
    for b in 0..3 {
        assert_eq!(u.read(RBR), b);
        assert!(!u.rts());
    }
    assert_eq!(u.read(RBR), 3);
    assert!(u.rts());
    u.clock(100 * CHAR);
    assert_eq!(u.rx_in.len(), 12);
    // without AFE, RTS is just MCR bit 1 and the FIFO overruns
    u.rx_in.extend(0..4u8);
    u.write(MCR, 0x02);
    assert!(u.rts());
    u.clock(100 * CHAR);
    assert!(u.rx_in.is_empty());
    assert_eq!(u.read(LSR), 0x63);
    // without RTS the terminal waits
    let mut u = uart(0x03);
    u.rx_in.push_back(1);
    assert_eq!(u.next_change(), None);
    u.clock(10 * CHAR);
    assert_eq!(u.read(LSR), 0x60);
}

#[test]
fn overrun_without_flow_control() {
    // no FIFOs: the new character replaces the unread one
    let mut u = uart(0x03);
    u.host_flow = false;
    u.write(IER, 0x05);
    u.rx_in.extend([1, 2, 3]);
    u.clock(CHAR);
    assert_eq!(u.read(IIR), 0x04);
    u.clock(2 * CHAR);
    assert_eq!(u.read(IIR), 0x06);
    assert_eq!(u.read(LSR), 0x63);
    // reading LSR cleared OE
    assert_eq!(u.read(LSR), 0x61);
    assert_eq!(u.read(IIR), 0x04);
    assert_eq!(u.read(RBR), 3);
    assert_eq!(u.read(LSR), 0x60);
    // FIFOs: the 17th character and later are lost
    let mut u = uart(0x03);
    u.host_flow = false;
    u.write(FCR, 0xC1);
    u.write(IER, 0x05);
    u.rx_in.extend(0..20u8);
    u.clock(20 * CHAR);
    assert_eq!(u.read(IIR), 0xC6);
    assert_eq!(u.read(LSR), 0x63);
    let got: Vec<u8> = (0..16).map(|_| u.read(RBR)).collect();
    assert_eq!(got, (0..16).collect::<Vec<u8>>());
    assert_eq!(u.read(LSR), 0x60);
}

#[test]
fn received_data_is_masked() {
    let mut u = uart(0x02); // 7 bits
    u.host_flow = false;
    u.rx_in.push_back(0xC1);
    u.clock(9 * 16);
    assert_eq!(u.read(RBR), 0x41);
}

#[test]
fn loopback() {
    let mut u = uart(0x03);
    u.write(IER, 0x09);
    u.rx_in.push_back(b'T');
    u.host_flow = false;
    // all modem outputs off in loopback: CTS, DSR and DCD go
    u.write(MCR, 0x10);
    assert!(!u.rts() && !u.dtr() && !u.out1() && !u.out2());
    assert_eq!(u.read(IIR), 0x00);
    assert_eq!(u.read(MSR), 0x0B);
    assert!(!u.intr());
    // the outputs loop back: RTS->CTS, DTR->DSR, OUT1->RI, OUT2->DCD
    u.write(MCR, 0x1F);
    assert!(!u.rts() && !u.dtr() && !u.out1() && !u.out2());
    assert_eq!(u.read(MSR), 0xFB);
    assert_eq!(u.read(MSR), 0xF0);
    // RI going off is TERI; RI coming on isn't
    u.write(MCR, 0x1B);
    assert_eq!(u.read(MSR), 0xB4);
    // the transmitter goes to the receiver, not the terminal, which waits
    u.write(RBR, b'L');
    u.clock(CHAR);
    assert!(u.tx_out.is_empty());
    assert_eq!(u.read(LSR), 0x61);
    assert_eq!(u.read(RBR), b'L');
    assert_eq!(u.rx_in.len(), 1);
    // out of loopback the terminal sends again, and the modem inputs are
    // the terminal's
    u.write(MCR, 0x0B);
    assert!(u.rts() && u.dtr() && !u.out1() && u.out2());
    assert_eq!(u.read(MSR), 0xB0);
    u.clock(CHAR);
    assert_eq!(u.read(RBR), b'T');
}

#[test]
fn next_change_lets_a_caller_skip() {
    // clocking to each change in turn ends where clocking straight does
    let mut a = uart(0x03);
    a.write(FCR, 0x81);
    a.write(MCR, 0x22);
    a.write(IER, 0x0F);
    a.rx_in.extend(0..30u8);
    for b in 0..5 {
        a.write(RBR, b);
    }
    let mut b = a.clone();
    let mut t = 0;
    while let Some(dt) = a.next_change() {
        assert!(dt > 0);
        a.clock(dt);
        t += dt;
        if a.intr() && matches!(a.read(IIR) & 0x0F, 0x04 | 0x0C) {
            while a.read(LSR) & 1 != 0 {
                a.read(RBR);
            }
        }
    }
    assert!(a.rx_in.is_empty());
    assert_eq!(a.tx_out, [0, 1, 2, 3, 4]);
    b.clock(5 * CHAR);
    assert_eq!(b.tx_out, a.tx_out);
    assert!(t > 30 * CHAR);
}
