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

\ ---- blocks on the bus (RFC 0027, 11): the primitives move any number of
\ halfwords natively, slicing them for the bus; here they're cut where an
\ address would leave its 64 KB on the bus, or its page in the shared RAM.

: seg ( d -- n ) drop negate u2/ ?dup 0= if $8000 then ;      \ halfwords left in d's 64 KB
: srseg ( d -- n ) drop negate ?dup 0= if $FFFF then ;         \ in its page of the shared RAM
: d+n ( d n -- d' ) 0 d+ ;
2variable from
2variable to
variable left
: step ( k -- ) dup negate left +!  2* to 2@ rot d+n to 2! ;
: bus-move ( src dst n -- )      \ n halfwords, between bus addresses
   left ! to 2! from 2!
   begin left @ while
      left @ from 2@ seg umin to 2@ seg umin >r
      from 2@ to 2@ r@ (move)
      r@ 2* from 2@ rot d+n from 2!  r> step  pause
   repeat ;
: bus-fill ( x d n -- )          \ n halfwords of x, (fill) by pairs
   left ! to 2!
   begin left @ while
      left @ to 2@ seg umin u2/ ?dup if
         >r dup to 2@ r@ (fill) r> 2* step
      else dup to 2@ bus! 1 step then
      pause
   repeat drop ;
: sr>bus ( sr d n -- )           \ from the shared RAM (halfword index lo, page) to the bus
   left ! to 2! from 2!
   begin left @ while
      left @ from 2@ srseg umin to 2@ seg umin >r
      from 2@ to 2@ r@ (sr>bus)
      from 2@ r@ d+n from 2!  r> step  pause
   repeat ;
: bus>sr ( d sr n -- )           \ from the bus to the shared RAM
   left ! from 2! to 2!
   begin left @ while
      left @ from 2@ srseg umin to 2@ seg umin >r
      to 2@ from 2@ r@ (bus>sr)
      from 2@ r@ d+n from 2!  r> step  pause
   repeat ;

\ Records from the image flash onto the bus: {address (low, high), n,
\ n halfwords}, until n is 0. The flash's position is kept as (reg page).
: copy-out ( reg page -- reg' page' )
   begin left @ while
      left @ to 2@ seg umin >r
      to 2@ r@ (flash>bus)  r> step  pause
   repeat ;
: play ( d -- )
   fl-split
   begin (fl@+) >r (fl@+) >r (fl@+) ?dup while
      left !  r> r> swap to 2!  copy-out
   repeat rdrop rdrop 2drop ;

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
