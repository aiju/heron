# The gallery

Every picture on `main` (at `198d40a`) drawn in the [figure
languages](README.md), with the ASCII it would replace, and a few new
figures where the documents have tables or prose. Each figure's source is
shown in a fenced block here; in a document it would be in a comment, and
only the picture would show.

`heron figures write studies/figures/gallery.md` draws them again.

## Timing diagrams

### [RFC 0037, 16: an access](../../reports/0037-rfc-system-and-io-bus.md#16-the-access)

The intervals are measured between named times: `[on]` names the time SEL rises, and `<-> a on` draws the interval under the row above it.

<details><summary>The ASCII it replaces</summary>

```
BCLK edge   0     1     2     3     4     5     6     7
A0-A7,      X=====================================X     address, WRITE (and write data)
WRITE         |<-1+setup->|                 |<-1+hold->|
SEL         ______________/‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾\__________
                          |<---- strobe ---->|
read data                        card drives ^ taken at the end of the strobe
```

</details>

```timing
# RFC 0037, 16: an access with SETUP = 1, STROBE = 3, HOLD = 1
.grid 1 'BCLK edge'
.range 0 8
BCLK            8{:1 +.5:0 +.5}
'A0–A7, WRITE'  :x .1[a]:'address, WRITE, write data' 7.1[b]:x
  <-> a on   '1 + SETUP'
  <-> off b  '1 + HOLD'
SEL             :0 2.1[on]:1 5.1[off]:0
  <-> on off 'STROBE'
'D, a read'     :z 3.6:'read data' off+.15:z
  ^ off 'taken at the end of the strobe'
```

![An access with SETUP = 1, STROBE = 3 and HOLD = 1](gallery/access.svg)

### [RFC 0037, 18: a read the card stretches with WAIT](../../reports/0037-rfc-system-and-io-bus.md#18-wait)

New, not a conversion: an illustration of section 18's rules, not a timing the RFC gives. WAIT falls at `on+25ns`, so moving SEL moves it too; `->` draws an arrow between named edges.

```timing
# RFC 0037, 18: a read the card stretches with WAIT
ns = 1/60          # the grid is in clocks of 60 ns
.grid 1 'BCLK edge'
.range 0 11
BCLK   11{:1 +.5:0 +.5}
SEL    :0 1.1[on]:1 9.1[off]|:0
WAIT   :1 on+25ns[w]:0 5.4[r]:1
  <-> on w '≤ 30 ns'
D      :z 5.2[d]:'read data' off+.15:z
  ^ off 'taken'
  <-> on off 'the strobe: STROBE clocks, more while WAIT'
on -> w
d -> r 'then released'
r -> off '2 clocks after it''s seen'
```

![A read stretched with WAIT](gallery/wait.svg)

## Bit fields

### [RFC 0028, 2: the instruction format](../../reports/0028-rfc-draft-2-isa.md#2-instruction-format)

`beside` puts a word to the right of the one before.

<details><summary>The ASCII it replaces</summary>

```
in memory:  byte 0     byte 1
            opcode     register byte
                       7      4 3      0
                       d        s
```

</details>

```bits
# RFC 0028, 2: the first parcel, an opcode byte and a register byte
word 8 "byte 0"
  7-0  opcode
word 8 "byte 1" beside
  7-4  d
  3-0  s
```

![The first parcel: the opcode byte, then the register byte](gallery/format.svg)

### [RFC 0028, 3: the index parcel](../../reports/0028-rfc-draft-2-isa.md#the-index-parcel)

<details><summary>The ASCII it replaces</summary>

```
15    12 11  10 9    8 7         0
   x        s      z       d8
```

</details>

```bits
# RFC 0028, 3: the index parcel
word 16
  15-12 x
  11-10 s
  9-8   z
  7-0   d8
```

![The index parcel](gallery/index.svg)

### [RFC 0028, 3.1: the special mode's two parcels](../../reports/0028-rfc-draft-2-isa.md#31-the-special-mode)

<details><summary>The ASCII it replaces</summary>

```
  parcel 1   15    12 11  10 9    8 7         0
                x        s      z     a23–16
  parcel 2   15                             0
                           a15–0
```

</details>

```bits
# RFC 0028, 3.1: the special mode's D and E take two parcels
word 16 "parcel 1"
  15-12 x
  11-10 s
  9-8   z
  7-0   a23–16
word 16 "parcel 2"
  15-0  a15–0
```

![The parcels of the special mode's D and E](gallery/special.svg)

### [RFC 0028, 5.1: MOV rd, #u7](../../reports/0028-rfc-draft-2-isa.md#51-moves)

New, from the prose: "holds the constant's bits 6–3 in the register byte's low nibble and its bits 2–0 in the opcode's". `= 01110` gives constant bits; `over` a bracket.

```bits
# RFC 0028, 5.1: MOV rd, #u7, as a little-endian parcel
word 16 "MOV rd, #u7"
  15-12 rd
  11-8  "u7 6–3"
  7-3   = 01110
  2-0   "u7 2–0"
  over 15-8 "register byte"
  over 7-0  "opcode byte"
```

![MOV rd, #u7: the constant split between the two bytes](gallery/mvi.svg)

### [RFC 0037, 15 and 17: registers from tables](../../reports/0037-rfc-system-and-io-bus.md#17-the-timing-table)

New, from the RFC's tables of bits. A name too long for its field goes under it; a field called reserved is hatched.

```bits
# RFC 0037, 17: an entry of the timing table
word 16
  15-14 reserved
  13    WINDOW
  12    WAIT
  11-8  HOLD
  7-2   STROBE
  1-0   SETUP
```

![An entry of the timing table](gallery/entry.svg)

```bits
# RFC 0037, 15: the X register addresses a device register
word 16 X
  15-12 reserved
  11-8  S
  7-0   "A0–A7"
  under 11-8 "the device"
  under 7-0  "its register"
```

![The X register: a device and its register](gallery/x.svg)

### [RFC 0001, 3: draft 0's encoding](../../reports/0001-rfc-draft-0.md#3-encoding)

<details><summary>The ASCII it replaces</summary>

```
 15  12 11   8 7    4 3    0
+------+------+------+------+
|  op  |  a   |  b   |  c   |
+------+------+------+------+
  a = rd (destination) or cc (condition)
  b = rs (source or base register)
  c = fn (function) or o (4-bit offset)
  ii = bits 7..0, a signed 8-bit immediate
```

</details>

```bits
# RFC 0001: draft 0's instruction
word 16
  15-12 op
  11-8  a
  7-4   b
  3-0   c
```

![Draft 0's instruction](gallery/draft0.svg)

## Address maps

### [RFC 0037, 5.1: Heron's map](../../reports/0037-rfc-system-and-io-bus.md#51-addresses)

New, from the RFC's table. Regions are as high as their text, not as big as they are.

```map
# RFC 0037, 5.1: Heron's map of physical addresses
0x0000_0000  "regions 0–3" "CPU or memory cards; the main CPU card in region 0"
0x4000_0000  "region 4" "the I/O processor's shared RAM"
0x5000_0000  "region 5" "a second video card, or another fast card"
0x6000_0000  "region 6" "video"
0x7000_0000  registers "the card in region N's at 0x7N00_0000"
0x7700_0000  free
0x7F00_0000  "the I/O bus's window" "device S's register RRRR at 0x7F0S_RRRR"
0x8000_0000  unused "outside the supervisor window"
0x1_0000_0000
group 0x0000_0000 0x7000_0000 "memory: 256 MB a region"
group 0x7000_0000 0x8000_0000 "16 MB a card"
group 0x0000_0000 0x8000_0000 "the kernel's, at 0x8000_0000 + p"
```

![Heron's map of physical addresses](gallery/physical.svg)

## Charts of tables

### [RFC 0028, 4: the opcode map](../../reports/0028-rfc-draft-2-isa.md#4-the-opcode-map)

New, from the RFC's table, copied as it is: the rows are written as Markdown's. `↳` continues the cell to its left, so `MVI #u7 ×8` spans eight cells; an empty cell is free, and hatched.

```grid
# RFC 0028, 4: the opcode map
| | _0 | _1 | _2 | _3 | _4 | _5 | _6 | _7 | _8 | _9 | _A | _B | _C | _D | _E | _F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0_ | ILLEGAL | LDM rb,ra-rc +1 | STM rb,ra-rc +1 | LEA [R+d16] +1 | LEA [sp+4R] | LEA [R+X·s] +1 | MFSR rd,n | MTSR n,rs | ADD.B4 | TMOV | TTST | TADD | TSUB | TCMP | LEA [r14+4R] | LEA spec +1–2 |
| 1_ | MOV rs | MOV #q | MOV [R] | MOV [R+d16] +1 | MOV [sp+4R] | MOV [R+X·s] +1 | MOV [R]+ | MOV -[R] | MOV b[R] | MOV b[R+d16] +1 | MOV b[R]+ | MOV h[R] | MOV h[R+d16] +1 | MOV #−q | MOV [r14+4R] | MOV spec +1–2 |
| 2_ | CLR ea +0–2 | INC ea +0–2 | ST [R] | ST [R+d16] +1 | ST [sp+4R] | ST [R+X·s] +1 | ST [R]+ | ST -[R] | ST b[R] | ST b[R+d16] +1 | ST b[R]+ | ST h[R] | ST h[R+d16] +1 | DEC ea +0–2 | ST [r14+4R] | ST spec +1–2 |
| 3_ | MOVS rs | MFUR rd,rs | MOVS [R] | MOVS [R+d16] +1 | MOVS [sp+4R] | MOVS [R+X·s] +1 | MOVS [R]+ | MOVS -[R] | MOVS b[R] | MOVS b[R+d16] +1 | MOVS b[R]+ | MOVS h[R] | MOVS h[R+d16] +1 | MTUR rd,rs | MOVS [r14+4R] | MOVS spec +1–2 |
| 4_ | ADD rs | ADD #q | ADD [R] | ADD [R+d16] +1 | ADD [sp+4R] | ADD [R+X·s] +1 | ADD [R]+ | ADD -[R] | ADD b[R] | ADD b[R+d16] +1 | ADD b[R]+ | ADD h[R] | ADD h[R+d16] +1 | ADD #−q | ADD [r14+4R] | ADD spec +1–2 |
| 5_ | SUB rs | SUB #q | SUB [R] | SUB [R+d16] +1 | SUB [sp+4R] | SUB [R+X·s] +1 | SUB [R]+ | SUB -[R] | SUB b[R] | SUB b[R+d16] +1 | SUB b[R]+ | SUB h[R] | SUB h[R+d16] +1 | SUB #−q | SUB [r14+4R] | SUB spec +1–2 |
| 6_ | CMP rs | CMP #q | CMP [R] | CMP [R+d16] +1 | CMP [sp+4R] | CMP [R+X·s] +1 | CMP [R]+ | CMP -[R] | CMP b[R] | CMP b[R+d16] +1 | CMP b[R]+ | CMP h[R] | CMP h[R+d16] +1 | CMP #−q | CMP [r14+4R] | CMP spec +1–2 |
| 7_ | MVI #u7 ×8 | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | CMPI #u7 ×8 | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ |
| 8_ | AND rs | AND #q | AND [R] | AND [R+d16] +1 | AND [sp+4R] | AND [R+X·s] +1 | AND [R]+ | AND -[R] | AND b[R] | AND b[R+d16] +1 | AND b[R]+ | AND h[R] | AND h[R+d16] +1 | AND #−q | AND [r14+4R] | AND spec +1–2 |
| 9_ | OR rs | OR #q | OR [R] | OR [R+d16] +1 | OR [sp+4R] | OR [R+X·s] +1 | OR [R]+ | OR -[R] | OR b[R] | OR b[R+d16] +1 | OR b[R]+ | OR h[R] | OR h[R+d16] +1 | OR #−q | OR [r14+4R] | OR spec +1–2 |
| A_ | XOR rs | XOR #q | XOR [R] | XOR [R+d16] +1 | XOR [sp+4R] | XOR [R+X·s] +1 | XOR [R]+ | XOR -[R] | XOR b[R] | XOR b[R+d16] +1 | XOR b[R]+ | XOR h[R] | XOR h[R+d16] +1 | XOR #−q | XOR [r14+4R] | XOR spec +1–2 |
| B_ | Bcc s8 ×16 | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ |
| C_ | LSL #n ×2 | ↳ | LSL rs |  | LSR #n ×2 | ↳ | LSR rs |  | ASR #n ×2 | ↳ | ASR rs |  | ROR #n ×2 | ↳ | ROR rs |  |
| D_ | NOT | NEG | INC | DEC | RLC | RRC | SWAP | SXB | SXH | ZXB | ZXH | CLZ | FFS | POPC | REV | SETcc |
| E_ | ADC rs | SBC rs | BIC rs | TST rs | MULU rs | MULS rs | MULA | DIVU rs | DIVS rs | DIVUL rs | BIC spec +1–2 | TST spec +1–2 | MULU spec +1–2 | MULS spec +1–2 | MERGE |  |
| F_ | JMP ea +0–2 | CALL ea +0–2 | Jcc rel16 +1 | Jcc abs32 +2 | SAVE ra-rb | RESTORE ra-rb | DBNZ r,back4 | CAS | FPU ea +1–3 |  |  |  | SWI #n | ext: misc | ext: system | ILLEGAL |
```

![Draft 2's opcode map](gallery/opmap.svg)

## Block diagrams

### [RFC 0016, 4: the video card](../../reports/0016-rfc-video.md#4-video-memory)

Boxes are placed `right of`, `below` and so on another box, or `at` a point of the grid; a box is as big as its text. A wire between two boxes picks the sides that face each other, and goes straight where they overlap.

<details><summary>The ASCII it replaces</summary>

```
            system bus (P1 + P2)
                    |
           +-----------------+
           |  bus interface  |  posted writes; WAIT on reads
           +-----------------+
                    |  CPU slots
+----------+  +-------------------------+  +------------+  +---------+
|  timing  |->|  VRAM: 4 x 512K x 8     |->| pixel path |->| palette |-> DACs -> VGA / PVM
|  ROMs    |  |  32 bits, 79 ns slots   |  +------------+  +---------+
+----------+  +-------------------------+        ^
  syncs, slot     ^          ^       ^           |
  owners          |          |       |      sprite line
               blitter    copper  sprites,  buffers (optional)
                                  tiles
```

</details>

```blocks
# RFC 0016, 4: the video card
text sys "system bus (P1 + P2)" at 30,0
box bif "bus interface" below sys gap 2
text "posted writes; WAIT on reads" right of bif gap 1.5
box tim "timing ROMs" at 0,11
text "syncs, slot owners" below tim gap 0.5
box vram "VRAM" "4 × 512K × 8, 32 bits" "79 ns slots" right of tim gap 4 width=27
box pix "pixel path" right of vram gap 4
box pal "palette" right of pix gap 3
box dac "DACs" right of pal gap 3
text vga "VGA / PVM" right of dac gap 3
box cop "copper" below vram gap 4
box blit "blitter" left of cop gap 1.5
box spr "sprites, tiles" right of cop gap 1.5
box buf "sprite line" "buffers (optional)" below pix gap 4 dashed

sys -> bif
bif -> vram "CPU slots"
tim -> vram -> pix -> pal -> dac -> vga
blit -> vram
cop -> vram
spr -> vram
buf -> pix
```

![The video card](gallery/video.svg)

### [Report 0012, 3: draft 1b's datapath](../../reports/0012-report-draft-1b-hardware.md#3-block-diagram)

RES is a `bus`: a wire to a bus goes straight across to it, with a dot where it meets it. The ASCII's last three lines would stay prose.

<details><summary>The ASCII it replaces</summary>

```
          +-- decode ROM (2 x flash) <-- data bus (the opcode being fetched)
          |
          v
   next address Y (153 x 6) <-- NEXT, condition, dispatch, reset/fault
          |
          v
   microcode ROMs (15 x flash) --> uIR (15 x 377) --> 120 control lines

  +-----------+  A bus  +--------------+   F   +------------------+  RES
  | RF copy A |-------->|              |------>| result mux       |----+--> R (377 x 4) --> A, A x 2, B
  | 4 x SRAM  | PC ---->| 8 x 74LS181  |       | F, F >> 1, ror 8,|    +--> MAR (377 x 3, via 157s)
  +-----------+ R, 2R ->| 3 x 74S182   |       | ror 16, per-byte |    +--> PC (161 x 8, load)
                B->A -->|              |       | clear (153 x 16) |    +--> LC (161 x 2)
  +-----------+  B bus  |              |       +------------------+    +--> data bus (541 x 5)
  | RF copy B |-------->|              |
  | 4 x SRAM  |         +--------------+
  +-----------+  B bus also from: R, T (by byte lane, x 2), immediate unit, MQ (299 x 4), flags

  address mux (PC or MAR, 157 x 5) --> RAM (2 x 512K x 8); I/O page when MAR bit 31 is set
  data bus <--> RAM, I/O; data bus --> IR (377 x 2), T (377 x 4), decode ROM, SX
  B bus --> flags (zero detect: 688 x 4), and through the bridge (541 x 4) onto the A bus
```

</details>

```blocks
# Report 0012, 3: draft 1b's datapath and its control

# the control
box dec "decode ROM" "2 × flash" at 0,0
text op "data bus (the opcode being fetched)" right of dec gap 4
box next "next address Y" "153 × 6" below dec gap 3
text cond "NEXT, condition, dispatch, reset/fault" right of next gap 4
box rom "microcode ROMs" "15 × flash" below next gap 3
box uir "µIR" "15 × 377" right of rom gap 4
text ctl "120 control lines" right of uir gap 4
op -> dec
cond -> next
dec -> next -> rom -> uir -> ctl

# the datapath
box rfa "RF copy A" "4 × SRAM" at 0,25
box rfb "RF copy B" "4 × SRAM" below rfa gap 4
box alu "ALU" "8 × 74LS181" "3 × 74S182" right of rfa gap 9 align=top height=14
box mux "result mux" "F, F >> 1, ror 8, ror 16," "per-byte clear" "153 × 16" right of alu gap 5 align=top
bus res "RES" from 54,27 to 54,39
text r "R (377 × 4) → A, A × 2, B" at 56,27
text mar "MAR (377 × 3, via 157s)" at 56,30
text pc "PC (161 × 8, load)" at 56,33
text lc "LC (161 × 2)" at 56,36
text db "data bus (541 × 5)" at 56,39
rfa -> alu "A bus"
rfb -> alu "B bus"
text a1 "PC" left of alu gap 2 dy=-1.5
text a2 "R, 2R" left of alu gap 2
text a3 "B → A" left of alu gap 2 dy=1.5
a1 -> alu
a2 -> alu
a3 -> alu
alu -> mux "F"
mux -> res
res -> r
res -> mar
res -> pc
res -> lc
res -> db
text "B bus also from: R, T (by byte lane, × 2), immediate unit, MQ (299 × 4), flags" below rfb gap 1 align=left
```

![Draft 1b's control and datapath](gallery/datapath.svg)

### [RFC 0027, 2: the I/O processor's card](../../reports/0027-rfc-io-coprocessor.md#2-the-card)

Four buses and the boxes on them. `alu.bottom -> f.bottom` goes around as a U, since both ends face down.

<details><summary>The ASCII it replaces</summary>

```
                                 system bus
   A1–A31, BE, START, WRITE        D0–D15                 REQ, GNT, WAIT, ATN0–3
  ======|=============================|==========================|===============
        |                             |                          |
  master: AL, AHOUT, AH0, AH1    16652: BA takes reads,     bus state; slave side:
  (16823 x 4)                    AB drives writes; also     three ranges, address
        |                        the slave's data path      register, WAIT
        |                             |
        |    +------------------------+--- T bus ---+-------------+-----------+
        |    |              |                       |             |           |
        | bridge         shared RAM            I/O bus side     swap      event ports,
        | (16245)        2 MB, 4 x 512K x 8    (RFC 0037, 22)   register  doorbells
        |    |                                      |
        |    |                  I/O bus ============+==== D0–D15, A0–A7, SEL and INT x 16
  ------+----+-------------------- R bus -----+-----------------+---------------
     |              |              |                |                  |
  SRAM 64K x 16  K <-> R        ALU: A from R,    F (16823): the     loaded from R:
  registers      (16245)        B from AC         result, onto R     AC, X, BANK,
  and memory        |           4 x 181 + 182     in the 2nd half    AH0, AH1, LC,
     |              |                 |                ^             control
  address:       K field              +----------------+
  BANK:REG or X     |
                    +--> uPC (4 x 161) --> microcode, 6 x flash --> uIR (3 x 16823)
```

</details>

```blocks
# RFC 0027, 2: the I/O processor's card
bus sys "system bus" from 0,3 to 90,3
text "A1–A31, BE, START, WRITE" at 12,1.5
text "D0–D15" at 33,1.5
text "REQ, GNT, WAIT, ATN0–3" at 62,1.5

box master "master" "AL, AHOUT, AH0, AH1" "16823 × 4" at 1,6
box ab "16652" "BA takes reads, AB drives writes," "and the slave's data path" at 27,6
box slave "bus state, slave side" "three ranges, address register," "WAIT" at 62,6

bus t "T bus" from 16,17 to 90,17
box bridge "bridge" "16245" at 16,20
box ram "shared RAM" "2 MB, 4 × 512K × 8" at 26,20
box iob "I/O bus side" "RFC 0037, 22" at 44,20
box swap "swap" "register" at 60,20
box ev "event ports," "doorbells" at 72,20 plain

bus io "I/O bus" from 40,28 to 66,28
text "D0–D15, A0–A7, SEL and INT × 16" at 67,28

bus r "R bus" from 0,32 to 90,32
box sram "SRAM" "64K × 16," "registers and memory" at 0,35
text "address: BANK:REG or X" below sram gap 0.5
box k "K ↔ R" "16245" at 20,35
box alu "ALU" "A from R, B from AC" "4 × 181 + 182" at 32,35
box f "F" "16823: the result," "onto R in the 2nd half" at 52,35
box ld "loaded from R" "AC, X, BANK, AH0, AH1," "LC, control" at 72,35

box upc "µPC" "4 × 161" below k gap 6 dx=8
box rom "microcode" "6 × flash" right of upc gap 4
box uir "µIR" "3 × 16823" right of rom gap 4

sys - master
sys - ab
sys - slave
master - r
ab - t
t - bridge
t - ram
t - iob
t - swap
t - ev
bridge - r
iob - io
r - sram.top-3
r - k
r - alu
r - f
r - ld
alu.bottom -> f.bottom
k -> upc "K field"
upc -> rom -> uir
```

![The I/O processor's card](gallery/iop.svg)
