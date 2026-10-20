; Chibi Heron's board (RFC 0047, 6-10), for programs to include: the I/O
; space's devices, the interrupt vectors, the tasks' words in RAM and the
; frame buffers. Every device is a halfword at an even address; an 8-bit
; one is on its low byte. All are within reach of a 16-bit absolute
; address (0xFFFF8000-0xFFFFFFFF), sign-extended.

; ---- the devices
UART1   = 0xFFFF9000            ; TL16C550C, register n at +2n
UART0   = 0xFFFFE000            ; the console; the reset routine leaves it at
                                ; 115,200 baud, 8N1, its FIFOs on, DTR and RTS
U_RBR   = 0                     ; (and THR)
U_IER   = 2
U_IIR   = 4                     ; (and FCR)
U_LCR   = 6
U_MCR   = 8
U_LSR   = 10                    ; bit 0 a character in, bit 5 THR empty
U_MSR   = 12

IRQC    = 0xFFFFD000            ; the interrupt controller
IRQ_PENDING = 0xFFFFD000        ; R: the sources pending (bits as below);
                                ; W: clears the interrupt button's latch
IRQ_VECTOR  = 0xFFFFD002        ; R: 0x40 + 4k for the first source pending, 0x04 if none
IRQ_ODT     = 0xFFFFD004        ; R: 0x9000 while ODT is asked for; W: bit 0 TRACE
SCANLINE    = 0xFFFFD006        ; R: the scanline (9 bits);
                                ; W: the copper's target: bits 8-0 the line, bit 15 CEN

VIDEO   = 0xFFFFC000            ; W: the video's control (a halfword); any
                                ; write acknowledges the frame interrupt
VC_FB1  = 1                     ;   frame buffer 1 shown (else 0)
VC_DEN  = 2                     ;   the display on
VC_VIE  = 4                     ;   the frame interrupt on
PALBANK = 0xFFFFC002            ; W: bits 3-0, the palette's P7-P4

PS2     = 0xFFFFB000
PS2_KBD = 0xFFFFB000            ; R: bit 0 the data line, bit 1 a clock edge to take
PS2_MOUSE = 0xFFFFB002          ; (the device task's)
PS2_KCTL = 0xFFFFB004           ; W: bit 3 the keyboard's interrupt, bit 4 pull
PS2_MCTL = 0xFFFFB006           ;    the clock low, bit 5 the data; the mouse's

SLOW    = 0xFFFFA000            ; the slow devices
T_C0    = 0xFFFFA000            ; the 82C54: counter 0 (OUT0 the timer's interrupt),
T_C1    = 0xFFFFA002            ;   counter 1 (OUT1 the PCM's sample rate),
T_C2    = 0xFFFFA004            ;   counter 2 (OUT2 the speaker), all on 1.8432 MHz
T_CTL   = 0xFFFFA006            ;   and its control word
PAL_WADDR = 0xFFFFA010          ; the IMS G171: the write address,
PAL_DATA  = 0xFFFFA012          ;   a colour (red, green, blue: 6 bits each),
PAL_MASK  = 0xFFFFA014          ;   the pixel mask (undefined at power-on),
PAL_RADDR = 0xFFFFA016          ;   the read address
PCM_SAMPLE = 0xFFFFA020         ; the PCM's sample (the device task's)
CF_TIMING  = 0xFFFFA030         ; W: bit 0, the CF card at PIO mode 4
CF_CMD  = 0xFFFFA040            ; the CF card's command block, register n at +2n
CF_CTL  = 0xFFFFA060            ;   and its control block's

FLASH   = 0xFFE00000            ; the boot flash: byte n at +2n

; ---- the interrupt sources (bits of IRQ_PENDING) and their vectors
IRQ_TIMER = 1
IRQ_FRAME = 2
IRQ_UART0 = 4
IRQ_UART1 = 8
IRQ_KBD   = 16
IRQ_MOUSE = 32
IRQ_CF    = 64
IRQ_BUTTON = 128
V_RESET = 0x00
V_IRQ   = 0x04                  ; an interrupt with no source pending
V_ILLEGAL = 0x08
V_SWI   = 0x0C
V_DIV   = 0x10
V_ADDR  = 0x14
V_TAG   = 0x18
V_TIMER = 0x40                  ; then 0x40 + 4k, k by priority
V_FRAME = 0x44
V_UART0 = 0x48
V_UART1 = 0x4C
V_KBD   = 0x50
V_MOUSE = 0x54
V_CF    = 0x58
V_BUTTON = 0x5C

; ---- the tasks' words in RAM, 0x60-0x73: software leaves them to the tasks
COPPTR  = 0x60                  ; the copper's place in its list
PCMPTR  = 0x64                  ; the next sample's address (a byte each)
PCMEND  = 0x68                  ; the samples' end: then the task plays 0x80
KBDFRAME = 0x70                 ; the keyboard's last frame: the data in bits 13-6
MOUSEFRAME = 0x72

; ---- the frame buffers: 640 x 480 x 4, 512 bytes a line, pixel x of a
; line in byte x / 2, the low nibble for even x
FB0     = 0x180000
FB1     = 0x1C0000
LINE    = 512
