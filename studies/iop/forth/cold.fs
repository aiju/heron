\ The IOP's Forth: the cold start, last, as it starts everything before it.

\ Client 0's rings and CPU 0's events, where the kernel expects them
\ (layout.py): no interrupt for its completions until it asks.
: kernel-rings ( -- )
   0 0. >sr K_IDX 8 + 2/ bus-fill
   K_REQ 0 cbank J.jreq reg !  $4000 0 cbank J.jpg reg !  K_REQS 16 * 1- 0 cbank J.jrmask reg !
   K_CMP 0 rset R_CMP + !  $4000 0 rset R_CMP + 1+ !  K_CMPS 8 * 1- 0 rset R_CMASK + !
   K_IDX 0 rset R_IDX + !  $4000 0 rset R_IDX + 1+ !
   0 0 0 notify!  0 ring-on
   K_EVRING 0 evs E_RING + !  $4000 0 evs E_RING + 1+ !  K_EVS 2* 1- 0 evs E_MASK + !
   K_EVBLK 0 evs E_BLK + !  $4000 0 evs E_BLK + 1+ !
   0 evring-on ;

: banner ( -- ) ." Heron IOP Forth, " here u. ." cells" cr ;
: cold ( -- )
   decimal  0 state !  0 handler !  0 evmask !  0 bells !
   tables  jobs-init
   uart-init  timer-init  7 leds
   kernel-rings  devices-init
   ['] server 1 spawn
   banner  quit ;
