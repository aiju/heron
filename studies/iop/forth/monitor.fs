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

$70000000. 2constant cpu-ctl
$70002000. 2constant cpu-irq
: cpu! ( x -- ) cpu-ctl bus! ;
: cpu? ( -- x ) cpu-ctl bus@ ;
: cpu-halt ( -- ) 0 cpu! ;
: cpu-run ( -- ) 1 cpu! ;
: cpu-reset ( -- ) 3 cpu! ;
: cpu-step ( -- ) 4 cpu! ;
: cpu-int ( level -- ) 1 swap 1- lshift cpu-irq bus! ;
: cpu-wait ( -- ) begin pause cpu? 2 and until ;     \ until it halts

\ ---- blocks (RFC 0027, 11): each a native job (`(job)`, ucode/jobs.uc),
\ which slices it for the bus while this task waits. Addresses are
\ physical, as doubles; region 4 is the shared RAM. Lengths in halfwords.

: >sr ( offset. -- phys. ) $4000 + ;
: bus-move ( src. dst. n -- ) 2* >r 2swap r> U.js_copy (job) ;
: bus-fill ( x dst. n -- ) 2* >r rot 0 r> U.js_fill (job) ;
: sr>bus ( sr. dst. n -- ) >r 2swap >sr 2swap r> bus-move ;     \ sr: an offset in the shared RAM
: bus>sr ( src. sr. n -- ) >r >sr r> bus-move ;
: io>bus ( reg dst. n -- ) 2* >r rot 0 r> U.js_fromio (job) ;   \ a device's register, n a multiple of 2
: bus>io ( src. reg n -- ) 2* >r 0 2swap r> U.js_toio (job) ;

\ Records from the image flash onto the bus: {address (low, high), n,
\ n halfwords}, until n is 0. The flash's position is kept as (reg page).
: fl+ ( reg page n -- reg' page' ) rot + dup swab $FF and rot + swap $FF and swap ;
2variable to
variable left
: play ( d -- )
   fl-split
   begin (fl@+) >r (fl@+) >r (fl@+) ?dup while
      left !  r> r> swap to 2!
      to 2@ 2over left @ 2* U.js_flash (job)
      left @ fl+
   repeat rdrop rdrop 2drop ;

\ The control store (image 0, if there is one), then the boot program
\ (image 1), then RESET and RUN (RFC 0027, 8.2).
: ?play ( d -- ) 2dup or if play else 2drop then ;
: boot-cpu ( -- ) cpu-halt  0 image ?play  1 image ?play  cpu-reset ;

\ ---- tasks: a bank each, in the ring through link

: reg ( bank r -- a ) swap 64 * + BANKS + ;
: me ( -- bank ) up@ R.me + @ ;
\ A task in a bank, running a colon definition's body for ever.
: spawn ( xt bank -- )
   >r
   1- r@ R.ip reg !
   r@ 128 * STACKS + dup 64 + r@ R.sp reg !  128 + r@ R.rp reg !
   U.next r@ R.resume reg !
   0 r@ R.wait reg !
   -1 r@ R.m1 reg !
   r@ r@ R.me reg !
   r@ 0 reg r@ R.up reg !
   10 r@ USER_FIRST reg !               \ base
   0 r@ USER_FIRST 5 + reg !            \ handler
   me R.link reg @ r@ R.link reg !  r> me R.link reg ! ;

\ ---- the LEDs, device 15

$F00 constant ports
: leds ( x -- ) ports io! ;

