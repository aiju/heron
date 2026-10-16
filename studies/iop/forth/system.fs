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
   U.jr_read OPTAB OP_READ + !  U.jr_write OPTAB OP_WRITE + !
   RTAB SOURCES 8 * erase
   RINGS 512 erase  REQQ 256 erase  EVRING 64 erase
   CPUS 0 do  i swab $7000 or  i 16 * EVRING + E_SEG + !  loop
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

\ ---- the clients' rings (RFC 0027, 7.1-7.2; RFC 0040, 5)

: rset ( c -- a ) 32 * RINGS + ;
: cbank ( c -- bank ) CLIENT_BANK + ;

\ Client c's ring job starts again from the request ring's first entry,
\ and its doorbell is answered. The client has set its head word (with
\ RING_EVENTS) to 0; the IOP sets the tail.
: ring-on ( c -- )
   >r
   0 r@ cbank J.jrtail reg !  0 r@ cbank J.jroff reg !  0 r@ cbank J.jpost reg !
   0 r@ cbank J.jirq reg !  U.jring r@ cbank J.jres reg !
   r@ r@ rset R_CL + !  r@ r@ cbank J.jcl reg !  r@ rset r@ cbank J.jset reg !
   0  r@ cbank J.jreq reg @ RING_TAIL +  r@ cbank J.jpg reg @  sr!
   1 r> lshift CLIENTS @ or CLIENTS ! ;

\ Client c's completions into the ring at a, in its CPU's RAM, of n
\ entries (0: none, they're dropped). The IOP writes its head, so sets it.
: cmp-ring ( a. n c -- )
   rset >r  dup 0<> r@ R_CON + !  8 * 1- r@ R_CMASK + !
   r@ R_CMP + 1+ !  r@ R_CMP + !  0 r@ R_COFF + !  0 r@ R_CHEAD + !
   r@ R_CON + @ if  0 r@ R_CMP + @ r@ R_CMP + 1+ @ bus!  then  rdrop ;
\ (Its RING_EVENTS, the head word's high half, follows jpost from the next
\ event on.)

\ Client c's rings, from settings in the shared RAM at a: the request
\ ring (low, high: in the shared RAM) and its entries, the completion
\ ring (low, high: in the CPU's RAM) and its entries.
variable rc
: ring-from ( a. c -- )
   rc !
   s@+ rc @ cbank J.jreq reg !  s@+ rc @ cbank J.jpg reg !  s@+ 16 * 1- rc @ cbank J.jrmask reg !
   s@+ >r s@+ >r s@+ >r 2drop  r> r> r> swap rot rc @ cmp-ring
   rc @ ring-on ;

\ Window n of client c's (0-3): [base, limit).
: window! ( base. limit. n c -- )
   rset >r  dup 1+ r@ R_NWIN + @ max r@ R_NWIN + !
   4 * R_WIN + r> + >r  r@ 3 + !  r@ 2 + !  r@ 1+ !  r> ! ;

\ Is [a, a + len) in one of client c's windows, as the ring jobs check
\ them? The kernel's is anywhere.
: du< ( d1 d2 -- f ) rot 2dup = if 2drop u< else swap u< nip nip then ;
: w@ ( a -- d ) dup @ swap 1+ @ ;
2variable ra
2variable re
: in-window? ( a. len c -- f )
   ?dup 0= if drop 2drop true exit then
   rset >r  >r 2dup ra 2!  r> 0 d+ re 2!
   r> dup R_NWIN + @ 0 ?do
      dup R_WIN + i 4 * +
      dup w@ ra 2@ 2swap du< 0=
      swap 2 + w@ re 2@ du< 0= and
      if drop unloop true exit then
   loop drop false ;
\ ---- events to the CPUs (RFC 0040, 4-5)

: evs ( cpu -- a ) 16 * EVRING + ;

\ CPU c's ring of events, from settings at a: the ring (low, high: in its
\ RAM) and its entries, the wake-me word (low, high: in the shared RAM).
\ The IOP writes its head, so sets it.
: evring-from ( a. cpu -- )
   >r
   s@+ r@ evs E_RING + !  s@+ r@ evs E_RING + 1+ !  s@+ 1- r@ evs E_MASK + !
   s@+ r@ evs E_WAKE + !  s@+ r@ evs E_WAKE + 1+ !  2drop
   0 r@ evs E_HEAD + !  0 r@ evs E_PEND + !
   0  r@ evs E_RING + @  r@ evs E_RING + 1+ @  bus!
   -1 r> evs E_ON + ! ;

\ A source's bit in EVMASK (INT 0-15) or ATNMASK (ATN0-3); the rings'
\ completions (SRC_RING + c) are masked by their ring jobs.
: line? ( src -- f ) SRC_RING u< ;
: src-bit ( src -- bit a ) dup 16 < if 1 swap lshift EVMASK else 16 - 1 swap lshift ATNMASK then ;
: unmask ( src -- ) dup line? if src-bit dup @ rot or swap ! else drop then ;
: mask ( src -- ) dup line? if src-bit dup @ rot invert and swap ! else drop then ;

\ The events for client c's completions that it has handled.
: seen ( c -- x ) cbank >r  r@ J.jreq reg @ RING_EVENTS +  r> J.jpg reg @  sr@ ;

\ Source src's routing (RFC 0040, 4.3): to CPU cpu at level (0: to
\ nobody); flags: the class, and a fast one's message source << 8; hold:
\ a slow one's batching, a lazy one's deadline, in ticks.
variable rsrc
: rt ( src -- a ) 8 * RTAB + ;
: route ( hold flags level cpu src -- )
   dup rsrc !  mask
   rsrc @ rt >r
   16 * r@ RT_CPU16 + !  dup r@ RT_LEVEL + !
   swap dup 3 and r@ RT_CLASS + !  $FF00 and r@ RT_MSG + !  swap r@ RT_HOLD + !
   rsrc @ line? 0= if  rsrc @ SRC_RING - dup seen swap cbank J.jpost reg !  then
   if  RT_CPU r> RT_OWNER + !  rsrc @ unmask  else  0 r> RT_OWNER + !  then ;

\ ---- the server (RFC 0027, 7.2): the requests the ring jobs pass on,
\ from REQQ, in a task of its own

: req ( n -- x ) REQTAIL @ REQQ + + @ ;     \ 0 the client, then the request
: rq ( q -- x ) 1+ req ;
: q-a ( -- d ) Q_ALO rq Q_AHI rq ;
: q-b ( -- d ) Q_BLO rq Q_BHI rq ;
: kernel? ( -- f ) 0 req 0= ;
variable status
variable result

\ A completion into client c's ring; its ring job posts its event, if
\ it's due, when it next finds its ring empty.
variable cc
: complete ( tag status result c -- )
   cc !  0 cc @ rset (complete)
   1 cc @ cbank J.jirq reg !  cc @ cbank (enqueue) ;
variable later          \ the request completes later, from elsewhere
: done ( -- )
   later @ 0= if  Q_TAG rq status @ result @ 0 req complete  then  0 later !
   REQTAIL @ 16 + $F0 and REQTAIL ! ;

\ Forth source from the kernel: len bytes at a, at most 256.
create fbuf 256 allot
: forth-req ( -- )
   Q_LEN rq 256 min >r
   r@ 0 ?do  q-a i -2 and 0 d+ sr@  i 1 and if swab then $FF and  fbuf i + !  loop
   fbuf r> evaluate ;

\ A client's own completion ring, in its windows.
: op-cmpring ( -- )
   q-a Q_LEN rq 8 * RING_ENTRIES + 0 req in-window? 0= if ST_WINDOW status ! exit then
   q-a Q_LEN rq 0 req cmp-ring ;

\ The devices' ops (devices.fs) after these.
: no-op ( op -- ) drop ST_BADOP status ! ;
variable 'more
' no-op 'more !

: op ( op -- )
   dup OP_NOP = if drop exit then
   dup OP_UNMASK = if drop Q_BLO rq unmask exit then
   dup OP_CMPRING = if drop op-cmpring exit then
   dup OP_SERVER 16 + u< 0= if 'more @ execute exit then
   kernel? 0= if drop ST_DENIED status ! exit then
   dup OP_RING = if drop q-a Q_BLO rq ring-from exit then
   dup OP_WINDOW = if drop q-a q-b Q_FLAGS rq dup swab $FF and swap 15 and window! exit then
   dup OP_ROUTE = if drop Q_LEN rq Q_FLAGS rq Q_BHI rq dup $FF and swap swab $FF and Q_BLO rq route exit then
   dup OP_EVRING = if drop q-a Q_BLO rq evring-from exit then
   dup OP_FORTH = if drop forth-req exit then
   no-op ;
: serve ( -- ) ST_OK status !  0 result !  Q_OP rq ['] op catch if drop ST_DEVICE status ! then  done ;
: server ( -- )
   begin
      1 wait-reg !  wait-reg SERVER !       \ waiting first: a request from now on wakes it
      REQHEAD @ REQTAIL @ = if  pause  else  0 wait-reg !  serve  then
   again ;

