\ The IOP's Forth: the system (RFC 0027, 6.6 and 7): the native layer's
\ tables, the jobs' banks, the clients' rings and the server for their
\ requests, the routing of events to the CPUs, and the cold start.

\ ---- the native layer's tables (layout.py)

: tables ( -- )
   33 0 do  i u2/ negate 15 and  NEGHALF i + !  loop
   65 0 do  i u2/ u2/ negate 15 and  NEGQUART i + !  loop
   0 LEVELBIT !  9 1 do  1 i 1- lshift  LEVELBIT i + !  loop
   16 0 do  U.jr_badop OPTAB i + !  loop
   U.jr_copy OPTAB OP_COPY + !  U.jr_fill OPTAB OP_FILL + !  U.jr_zero OPTAB OP_ZERO + !
   EVTAB SOURCES 4 * erase
   RINGS 512 erase  REQQ 256 erase  EVRING 64 erase
   JLINK 256 erase ;

\ ---- the jobs' banks: the pool's in the free list, the clients' ring jobs

: job-init ( bank -- )
   >r  -1 r@ R.m1 reg !  CTRL_SESSION r@ J.jsoff reg !  CTRL_SESSION 8 or r@ J.json reg !
   r@ r@ J.jme reg !  r@ 0 reg r@ J.jbase reg !  rdrop ;
: jobs-init ( -- )
   0 JFREE !
   JOB_FIRST JOBS + JOB_FIRST do  i job-init  JFREE @ i J.jkind reg !  i 0 reg JFREE !  loop
   CLIENT_BANK CLIENTS_N + CLIENT_BANK do  i job-init  loop ;

\ ---- the shared RAM, from the Forth: physical addresses (region 4) or
\ offsets work alike, as the page register takes address bits 16-22

: s@+ ( a. -- a+2. x ) 2dup sr@ >r 2 0 d+ r> ;

\ ---- the clients' rings (RFC 0027, 7.1-7.2)

: rset ( c -- a ) 32 * RINGS + ;
: cbank ( c -- bank ) CLIENT_BANK + ;

\ Client c's ring job starts again from the ring's first entry, and its
\ doorbell is answered.
: ring-on ( c -- )
   >r
   0 r@ cbank J.jrtail reg !  r@ rset R_IDX + @ r@ cbank J.jidx reg !
   0 r@ cbank J.jirq reg !  U.jring r@ cbank J.jres reg !
   0 r@ rset R_CHEAD + !  r@ r@ rset R_CL + !
   r@ r@ cbank J.jcl reg !  r@ rset r@ cbank J.jset reg !
   0 r@ rset R_IDX + @ I_REQTAIL + r@ rset R_IDX + 1+ @ sr!
   0 r@ rset R_IDX + @ I_CMPHEAD + r@ rset R_IDX + 1+ @ sr!
   1 r> lshift CLIENTS @ or CLIENTS ! ;

\ Client c's rings, from settings in the shared RAM at a: the request
\ ring (low, high), its bytes, the completion ring likewise, the indices
\ (low, high); then its completions' interrupt: level | CPU << 8, and its
\ hold in ticks. The rings and indices share a 64 KB page.
variable rc
: notify! ( route hold c -- )
   rset >r  r@ R_HOLD + !  dup $FF and r@ R_LEVEL + !  swab $FF and 16 * r> R_CPU16 + ! ;
: ring-from ( a. c -- )
   rc !
   s@+ rc @ cbank J.jreq reg !  s@+ rc @ cbank J.jpg reg !  s@+ 1- rc @ cbank J.jrmask reg !
   s@+ rc @ rset R_CMP + !  s@+ rc @ rset R_CMP + 1+ !  s@+ 1- rc @ rset R_CMASK + !
   s@+ rc @ rset R_IDX + !  s@+ rc @ rset R_IDX + 1+ !
   s@+ >r s@+ r> swap rc @ notify!  2drop
   rc @ ring-on ;

\ Window n of client c's (0-3): [base, limit).
: window! ( base. limit. n c -- )
   rset >r  dup 1+ r@ R_NWIN + @ max r@ R_NWIN + !
   4 * R_WIN + r> + >r  r@ 3 + !  r@ 2 + !  r@ 1+ !  r> ! ;

\ ---- events to the CPUs (RFC 0027, 7.3)

: evs ( cpu -- a ) 16 * EVRING + ;
: evring-on ( cpu -- )
   >r  0 r@ evs E_HEAD + !  0 r@ evs E_PEND + !
   r@ swab $7000 or r@ evs E_SEG + !
   0 r@ evs E_BLK + @ B_HEAD + r@ evs E_BLK + 1+ @ sr!
   -1 r> evs E_ON + ! ;

\ CPU c's events, from settings at a: its ring (low, high), the ring's
\ bytes, the block (low, high). The ring and the block share a page.
: evring-from ( a. cpu -- )
   >r
   s@+ r@ evs E_RING + !  s@+ r@ evs E_RING + 1+ !  s@+ 1- r@ evs E_MASK + !
   s@+ r@ evs E_BLK + !  s@+ r@ evs E_BLK + 1+ !  2drop
   r> evring-on ;

\ A source's bit in EVMASK (INT 0-15) or ATNMASK (ATN0-3).
: src-bit ( src -- bit a ) dup 16 < if 1 swap lshift EVMASK else 16 - 1 swap lshift ATNMASK then ;
: unmask ( src -- ) src-bit dup @ rot or swap ! ;
: mask ( src -- ) src-bit dup @ rot invert and swap ! ;

\ Source src to CPU cpu at level, held back up to hold ticks if the level
\ is slow; level 0: to nobody.
variable rsrc
: route ( hold level cpu src -- )
   dup rsrc !  mask
   rsrc @ 4 * EVTAB + >r
   16 * r@ EV_CPU16 + !  dup r@ EV_LEVEL + !  swap r@ EV_HOLD + !
   if  EV_CPU r> EV_OWNER + !  rsrc @ unmask  else  0 r> EV_OWNER + !  then ;

\ ---- the server (RFC 0027, 7.2): the requests the ring jobs pass on,
\ from REQQ, in a task of its own

: req ( n -- x ) REQTAIL @ REQQ + + @ ;     \ 0 the client, then the request
: rq ( q -- x ) 1+ req ;
: q-a ( -- d ) Q_ALO rq Q_AHI rq ;
: q-b ( -- d ) Q_BLO rq Q_BHI rq ;
: kernel? ( -- f ) 0 req 0= ;
variable status
variable result

\ Its completion, and the client's interrupt.
: done ( -- )
   Q_TAG rq status @ result @ 0 0 req rset (complete)
   0 req rset >r
   r@ R_LEVEL + @ if  SRC_RING 0 req +  r@ R_CPU16 + @  r@ R_LEVEL + @  r@ R_HOLD + @  (post)  then
   rdrop
   REQTAIL @ 16 + $F0 and REQTAIL ! ;

\ Forth source from the kernel: len bytes at a, at most 256.
create fbuf 256 allot
: forth-req ( -- )
   Q_LEN rq 256 min >r
   r@ 0 ?do  q-a i -2 and 0 d+ sr@  i 1 and if swab then $FF and  fbuf i + !  loop
   fbuf r> evaluate ;

\ The disk: none yet (the CF card's words come later in the build).
variable 'read
variable 'write
: no-disk ( -- ) ST_DEVICE status ! ;
' no-disk 'read !
' no-disk 'write !

: op ( op -- )
   dup OP_NOP = if drop exit then
   dup OP_UNMASK = if drop Q_BLO rq unmask exit then
   dup OP_READ = if drop 'read @ execute exit then
   dup OP_WRITE = if drop 'write @ execute exit then
   kernel? 0= if drop ST_DENIED status ! exit then
   dup OP_RING = if drop q-a Q_BLO rq ring-from exit then
   dup OP_NOTIFY = if drop Q_BHI rq Q_LEN rq Q_BLO rq notify! exit then
   dup OP_WINDOW = if drop q-a q-b Q_FLAGS rq dup swab $FF and swap 15 and window! exit then
   dup OP_ROUTE = if drop Q_LEN rq Q_BHI rq dup $FF and swap swab $FF and Q_BLO rq route exit then
   dup OP_EVRING = if drop q-a Q_BLO rq evring-from exit then
   dup OP_FORTH = if drop forth-req exit then
   drop ST_BADOP status ! ;
: serve ( -- ) ST_OK status !  0 result !  Q_OP rq ['] op catch if drop ST_DEVICE status ! then  done ;
: server ( -- )
   begin
      1 wait-reg !  wait-reg SERVER !       \ waiting first: a request from now on wakes it
      REQHEAD @ REQTAIL @ = if  pause  else  0 wait-reg !  serve  then
   again ;

\ ---- the cold start

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
   kernel-rings
   ['] server 1 spawn
   banner  quit ;
