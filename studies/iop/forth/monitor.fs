\ The IOP's Forth: the console monitor, the image flash, booting the CPU,
\ tasks, and the cold start (RFC 0027, 6.6 and 8).

\ ---- hex with leading zeros

: h.4 ( u -- ) base @ >r hex 0 <# # # # # #> type r> base ! ;
: h.8 ( d -- ) base @ >r hex <# # # # # # # # # #> type r> base ! ;

\ ---- the monitor: any address on the system bus, as a double

: e ( d -- ) 2dup h.8 ." : " bus@ h.4 cr ;
: d ( x d -- ) bus! ;
: dump ( d n -- )
   0 ?do
      i 7 and 0= if cr 2dup h.8 ." :" then
      space 2dup bus@ h.4  2 0 d+
   loop 2drop cr ;

\ ---- the image flash, device 13: halfword addresses as doubles

: fl-split ( d -- reg page ) over $FF and -rot swab swap swab $FF and or ;
: fl@ ( d -- x ) fl-split flash@ ;
: fl! ( x d -- ) fl-split flash! ;
: image ( n -- d ) 2* FL_IMAGES + dup 0 flash@ swap 1+ 0 flash@ ;

\ Programming it, two SST39SF040 side by side: each command to both.
: unlock ( -- ) $AAAA $55 $55 flash!  $5555 $AA $2A flash! ;
: fl-wait ( -- ) begin 0 0 flash@ 0 0 flash@ xor $4040 and 0= until ;
: fl-program ( x d -- ) unlock $A0A0 $55 $55 flash! fl! fl-wait ;
: fl-erase ( d -- ) unlock $8080 $55 $55 flash! unlock $3030 -rot fl! fl-wait ;

\ The dictionary back into the flash, so that the next cold start has
\ what was compiled since: sectors of 4096 halfwords from 0, the header
\ kept but for the dictionary's length.
create flhdr 16 allot
: save ( -- )
   16 0 do i 0 flash@ flhdr i + ! loop
   here 255 + 8 rshift flhdr FL_PAGES + !
   here FL_DICT + 4095 + 12 rshift 0 do i 12 lshift 0 fl-erase loop
   16 0 do flhdr i + @ i 0 fl-program loop
   here 0 do i @ i FL_DICT + 0 fl-program loop ;

\ ---- the CPU card (RFC 0027, 8.1): its registers at 0x7000_0000

$70001000. 2constant cpu-ctl
$70002000. 2constant cpu-irq
: cpu! ( x -- ) cpu-ctl bus! ;
: cpu? ( -- x ) cpu-ctl bus@ ;
: cpu-halt ( -- ) 0 cpu! ;
: cpu-run ( -- ) 1 cpu! ;
: cpu-reset ( -- ) 3 cpu! ;
: cpu-step ( -- ) 4 cpu! ;
: cpu-int ( level -- ) 1 swap 1- lshift cpu-irq bus! ;
: cpu-wait ( -- ) begin pause cpu? 2 and until ;     \ until it halts

\ Records from the image flash onto the bus: {address (low, high), n,
\ n halfwords}, until n is 0. Slices of at most 16 halfwords that stay in
\ a page of the flash and 64 KB of the bus, with a pause between.
2variable fp
2variable dst
variable left
: fp+ ( n -- ) fp 2@ rot 0 d+ fp 2! ;
: dst+ ( n -- ) dst 2@ rot 0 d+ dst 2! ;
: fnext ( -- x ) fp 2@ fl@ 1 fp+ ;
: slice ( -- n )
   left @ 16 min  256 fp 2@ drop $FF and - min
   dst 2@ drop negate u2/ ?dup if min then ;
: copy-out ( -- )
   begin left @ while
      slice >r
      fp 2@ fl-split dst 2@ r@ (flash>bus)
      r@ fp+  r@ 2* dst+  r> negate left +!
      pause
   repeat ;
: play ( d -- )
   fp 2!
   begin fnext fnext fnext ?dup while
      left ! dst 2! copy-out
   repeat 2drop ;

\ The control store (image 0, if there is one), then the boot program
\ (image 1), then RESET and RUN (RFC 0027, 8.2).
: ?play ( d -- ) 2dup or if play else 2drop then ;
: boot-cpu ( -- ) cpu-halt  0 image ?play  1 image ?play  cpu-reset ;

\ ---- tasks: a bank each, in the ring through link

: reg ( bank r -- a ) swap 64 * + BANKS + ;
: me ( -- bank ) up@ 36 + @ ;
\ A task in a bank, running a colon definition's body for ever.
: spawn ( xt bank -- )
   >r
   1- r@ 0 reg !
   r@ 128 * STACKS + dup 64 + r@ 1 reg !  128 + r@ 2 reg !
   U.next r@ 33 reg !
   0 r@ 35 reg !
   r@ r@ 36 reg !
   r@ 0 reg r@ 37 reg !
   10 r@ 40 reg !
   me 34 reg @ r@ 34 reg !  r> me 34 reg ! ;

\ ---- the LEDs, device 15

$F00 constant ports
: leds ( x -- ) ports io! ;

\ ---- the cold start

: banner ( -- ) ." Heron IOP Forth, " here u. ." cells" cr ;
: cold ( -- )
   decimal  0 state !  0 evmask !  0 bells !
   uart-init  timer-init  7 leds
   banner  quit ;
