\ The IOP's Forth: the cold start, last, as it starts everything before it.

\ Client 0's request ring, where the kernel expects it (layout.py); no
\ completion ring or ring of events until it asks.
: kernel-rings ( -- )
   0 0. >sr K_REQ RING_ENTRIES + 2/ bus-fill
   K_REQ 0 cbank J.jreq reg !  $4000 0 cbank J.jpg reg !  K_REQS 16 * 1- 0 cbank J.jrmask reg !
   0. 0 0 cmp-ring  0 ring-on ;

: banner ( -- ) ." Heron IOP Forth, " here u. ." cells" cr ;
: cold ( -- )
   decimal  0 state !  0 handler !  0 evmask !  0 bells !
   tables  jobs-init
   uart-init  timer-init  7 leds
   kernel-rings  devices-init
   ['] server 1 spawn
   STATUS_READY S_READY 0 sr!
   banner  quit ;
