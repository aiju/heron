\ The IOP's Forth: the I/O cards (RFC 0037, 21) and the requests for them
\ (RFC 0027, 7.2): the CF card's sectors, the serial lines with their
\ line discipline.

\ ---- bytes at physical addresses: on the bus, or in the shared RAM

: sr? ( a. -- f ) nip $F000 and $4000 = ;
: pc@ ( a. -- c )
   2dup sr? 0= if busc@ exit then
   over 1 and >r  swap -2 and swap sr@  r> if swab then $FF and ;
variable pcv
: pc! ( c a. -- )
   2dup sr? 0= if busc! exit then
   rot pcv !  over 1 and >r  swap -2 and swap  2dup sr@
   r> if $FF and pcv @ swab or else $FF00 and pcv @ $FF and or then
   -rot sr! ;

\ ---- a client's windows, as the ring jobs check them

: du< ( d1 d2 -- f ) rot 2dup = if 2drop u< else swap u< nip nip then ;
: w@ ( a -- d ) dup @ swap 1+ @ ;
2variable ra
2variable re
\ Is [a, a + len) in one of client c's windows? The kernel's is anywhere.
: in-window? ( a. len c -- f )
   ?dup 0= if drop 2drop true exit then
   rset >r  >r 2dup ra 2!  r> 0 d+ re 2!
   r> dup R_NWIN + @ 0 ?do
      dup R_WIN + i 4 * +
      dup w@ ra 2@ 2swap du< 0=
      swap 2 + w@ re 2@ du< 0= and
      if drop unloop true exit then
   loop drop false ;
: window? ( a. len -- f )      \ the request's own client's
   0 req in-window? dup 0= if ST_WINDOW status ! then ;

\ ---- the CF card in slot DISK_SLOT: the task file at 0-7, the device
\ control at 8 + 6. Its interrupt stays off: the driver polls, pausing,
\ as a sector is there in a few microseconds. The rings' disk requests
\ are native (ucode/jobs.uc's jr_read and jr_write); these words are the
\ console's, and find the card and its size at the cold start.

DISK_SLOT 256 * constant cf
: cf@ ( r -- c ) cf + io@ $FF and ;
: cf! ( c r -- ) cf + io! ;
variable disk?
2variable disk-sectors
: cf-ready ( -- s ) begin 7 cf@ dup $80 and while drop pause repeat ;
: cf-drq ( -- f ) cf-ready dup 1 and if drop false exit then 8 and 0<> ;
\ IDENTIFY DEVICE: its words 60-61 are the sectors addressable by LBA.
: cf-identify ( -- )
   0. disk-sectors 2!
   cf-ready drop  $E0 6 cf!  $EC 7 cf!
   cf-drq 0= if exit then
   256 0 do  cf io@  i 60 = if dup disk-sectors 1+ ! then  i 61 = if dup disk-sectors ! then  drop  loop ;
\ A card is there if its registers keep what's written: an empty slot
\ reads what was last on D, so each is read after the other's write.
: cf-init ( -- )
   2 14 cf!  $55 2 cf!  $AA 3 cf!  2 cf@ $55 =  3 cf@ $AA = and disk? !
   disk? @ if cf-identify  cf $8000 or DISKX ! then
   disk-sectors 2@ swap S_SECTORS 0 sr!  S_SECTORS 2 + 0 sr! ;
: cf-cmd ( sector. n cmd -- )
   >r  cf-ready drop  2 cf!
   over 3 cf!  over swab 4 cf!  dup 5 cf!  swab $0F and $E0 or 6 cf!  drop
   r> 7 cf! ;

\ n sectors from the disk to a, or from a to the disk: each sector a
\ native job between the data register and a. True if they all went.
: cf-read ( sector. a. n -- f )
   >r 2swap r@ $20 cf-cmd
   r> 0 ?do
      cf-drq 0= if 2drop unloop false exit then
      2dup cf -rot 256 io>bus  512 0 d+
   loop 2drop  cf-ready 1 and 0= ;
: cf-write ( sector. a. n -- f )
   >r 2swap r@ $30 cf-cmd
   r> 0 ?do
      cf-drq 0= if 2drop unloop false exit then
      2dup cf 256 bus>io  512 0 d+
   loop 2drop  cf-ready 1 and 0= ;

\ ---- the serial card in slot SERIAL_SLOT: two 16C550s from CLKA, line
\ n's registers at 8n + r

SERIAL_SLOT 256 * constant serial
: sl@ ( r n -- c ) 8 * + serial + io@ $FF and ;
: sl! ( c r n -- ) 8 * + serial + io! ;
: serial? ( -- f ) $5A 7 0 sl!  $A5 7 1 sl!  7 0 sl@ $5A = ;   \ (as cf-init)
: line-init ( n -- )
   >r  $80 3 r@ sl!  1 0 r@ sl!  0 1 r@ sl!  3 3 r@ sl!   \ 115,200 baud, 8 bits
   $07 2 r@ sl!  $2B 4 r@ sl!  1 1 r> sl! ;              \ FIFOs, a trigger at 1; an interrupt on input
: sl-emit ( c n -- ) begin 5 over sl@ $20 and 0= while pause repeat 0 swap sl! ;

\ The line discipline, for each line: its input so far, its mode (bit 0
\ raw, bit 1 no echo), whether a whole line is in (cooked), and the
\ receive request waiting for it.
create lbuf 256 allot
create lcnt 2 allot
create lmode 2 allot
create lline 2 allot
create rq-client 2 allot      \ its client + 1, or 0 for none
create rq-a 4 allot
create rq-len 2 allot
create rq-tag 2 allot
: lb ( n -- a ) 128 * lbuf + ;
: echo ( c n -- ) dup lmode + @ 2 and if 2drop else sl-emit then ;
: lput ( c n -- )
   dup lcnt + @ 127 u< if  dup lb over lcnt + @ + rot swap !  lcnt + 1 swap +!  else 2drop then ;
: rub ( n -- )
   dup lcnt + @ if  -1 over lcnt + +!  8 over echo  bl over echo  8 swap echo  else drop then ;
: lchar ( c n -- )
   dup lmode + @ 1 and if lput exit then
   over 8 = 2 pick 127 = or if nip rub exit then
   over 13 = if  nip  13 over echo  10 over echo  10 over lput  -1 swap lline + !  exit then
   2dup echo lput ;

\ The waiting receive gets what has come: a line, or (raw) anything.
variable dl
variable dk
: deliver ( n -- )
   dl !
   dl @ rq-client + @ 0= if exit then
   dl @ lmode + @ 1 and if dl @ lcnt + @ else dl @ lline + @ then 0= if exit then
   dl @ lcnt + @ dl @ rq-len + @ umin dk !
   dk @ 0 ?do  dl @ lb i + @  dl @ 2* rq-a + w@ i 0 d+ pc!  loop
   dl @ lb dk @ +  dl @ lb  dl @ lcnt + @ dk @ -  move
   dk @ negate dl @ lcnt + +!  0 dl @ lline + !
   dl @ rq-tag + @ ST_OK dk @ dl @ rq-client + @ 1- complete
   0 dl @ rq-client + ! ;

\ The card's task: each line's input through the discipline, then the
\ card's INT.
: serial-poll ( n -- ) begin 5 over sl@ 1 and while 0 over sl@ over lchar repeat deliver ;
: serial-task ( -- ) begin 0 serial-poll 1 serial-poll SERIAL_SLOT wait-int again ;

: line# ( -- n ) Q_BLO rq 1 and ;
: op-send ( -- )
   q-a Q_LEN rq window? 0= if exit then
   q-a Q_LEN rq 0 ?do  2dup i 0 d+ pc@ line# sl-emit  loop 2drop
   Q_LEN rq result ! ;
: op-recv ( -- )
   q-a Q_LEN rq window? 0= if exit then
   line# rq-client + @ if ST_BUSY status ! exit then
   q-a line# 2* rq-a + tuck 1+ ! !  Q_LEN rq line# rq-len + !  Q_TAG rq line# rq-tag + !
   0 req 1+ line# rq-client + !
   -1 later !  line# deliver ;
: op-mode ( -- ) Q_FLAGS rq line# lmode + ! ;

: dev-op ( op -- )
   dup OP_SEND = if drop op-send exit then
   dup OP_RECV = if drop op-recv exit then
   dup OP_MODE = if drop op-mode exit then
   no-op ;
' dev-op 'more !

: devices-init ( -- )
   TT_CF DISK_SLOT ttab!  TT_SERIAL SERIAL_SLOT ttab!
   cf-init
   lcnt 2 erase  lmode 2 erase  lline 2 erase  rq-client 2 erase
   serial? if  0 line-init  1 line-init  ['] serial-task 2 spawn  then ;
