\ The IOP's Forth: the kernel. The metacompiler (meta.py) compiles it over
\ the primitives in the microcode (ucode/prims.uc). Cells are 16 bits, a
\ character takes a cell, and addresses count cells in the SRAM.

\ ---- the dictionary's own variables (the metacompiler sets dp and latest)

variable dp
variable latest
variable state
variable leaves         \ the compiler's leaves still to resolve
variable 'abort         \ abort's action
user base
user >in
user #tib
user 'tib               \ the input line
user hld

-1 constant true
0 constant false
32 constant bl
S0 constant s0
R0 constant r0
TIB constant tib0
EVMASK constant evmask
EVTAB constant evtab
BELLS constant bells

\ ---- the stack and arithmetic

: tuck ( a b -- b a b ) swap over ;
: -rot ( a b c -- c a b ) rot rot ;
: 2swap ( a b c d -- c d a b ) rot >r rot r> ;
: 2over ( a b c d -- a b c d a b ) >r >r 2dup r> r> 2swap ;
: pick ( xn .. x0 n -- xn .. x0 xn ) sp@ + @ ;
: depth ( -- n ) s0 sp@ - 1- ;
: > ( a b -- f ) swap < ;
: u> ( a b -- f ) swap u< ;
: 0> ( n -- f ) 0 > ;
: min ( a b -- n ) 2dup > if swap then drop ;
: max ( a b -- n ) 2dup < if swap then drop ;
: umin ( a b -- u ) 2dup u> if swap then drop ;
: abs ( n -- u ) dup 0< if negate then ;
: within ( n lo hi -- f ) over - >r - r> u< ;
: * ( a b -- c ) um* drop ;
: s>d ( n -- d ) dup 0< ;
: dnegate ( d -- -d ) invert swap negate swap over 0= - ;
: dabs ( d -- ud ) dup 0< if dnegate then ;
: d+ ( d1 d2 -- d ) rot + >r over + swap over u> r> swap - ;
: sm/rem ( d n -- rem quot )
   2dup xor >r over >r abs >r dabs r> um/mod
   swap r> 0< if negate then swap r> 0< if negate then ;
: /mod ( n d -- rem quot ) >r s>d r> sm/rem ;
: / ( n d -- quot ) /mod nip ;
: mod ( n d -- rem ) /mod drop ;
: u2/ ( u -- u' ) 1 rshift ;
: 2/ ( n -- n' ) dup u2/ swap 0< if $8000 or then ;
: cell+ ( a -- a' ) 1+ ;
: cells ( n -- n ) ;
: chars ( n -- n ) ;
: char+ ( a -- a' ) 1+ ;

\ ---- memory

: here ( -- a ) dp @ ;
: allot ( n -- ) dp +! ;
: , ( x -- ) here ! 1 allot ;
: c, ( c -- ) , ;
: 2! ( lo hi a -- ) tuck ! 1+ ! ;
: 2@ ( a -- lo hi ) dup 1+ @ swap @ ;
: count ( a -- a+1 n ) dup 1+ swap @ ;
: move ( src dst n -- ) 0 ?do over @ over ! 1+ swap 1+ swap loop 2drop ;
: fill ( a n x -- ) -rot 0 ?do 2dup ! 1+ loop 2drop ;
: erase ( a n -- ) 0 fill ;

\ ---- the console: device 12 on the I/O bus, a 16C550

$C00 constant uart
: uart@ ( r -- c ) uart + io@ $FF and ;
: uart! ( c r -- ) uart + io! ;
: uart-init ( -- )
   $80 3 uart!  1 0 uart!  0 1 uart!   \ divisor 1: 921,600 baud
   3 3 uart!                           \ 8 bits, no parity, one stop bit
   $87 2 uart!                         \ the FIFOs on and emptied, a trigger at 8
   $2B 4 uart!                         \ DTR, RTS, OUT2, auto flow control
   1 1 uart! ;                         \ an interrupt while there's input

\ ---- tasks and events (RFC 0027, 6.4)

\ A task waits for INT line n: its wait register set, the line routed to
\ it and enabled; the native layer clears wait and masks the line at the
\ next tick after the line is up.
: wait-reg ( -- a ) up@ 35 + ;
: wait-int ( n -- )
   1 wait-reg !
   wait-reg over evtab + !
   1 swap lshift evmask @ or evmask !
   pause ;

\ The timer, device 14: counter 0 is the polling tick, every 10 us from
\ CLKB's 4 MHz; counter 2 times `ms`, its OUT on INT 14.
$E00 constant timer
: timer-init ( -- ) $34 timer 3 + io!  40 timer io!  0 timer io! ;
: 1ms ( -- ) $B0 timer 3 + io!  4000 dup $FF and timer 2 + io!  swab $FF and timer 2 + io!
   14 wait-int  $B0 timer 3 + io! ;      \ OUT2 low again: INT 14 down
: ms ( n -- ) 0 ?do 1ms loop ;

\ ---- characters in and out

: key? ( -- f ) 5 uart@ 1 and 0<> ;
: key ( -- c ) begin key? 0= while 12 wait-int repeat 0 uart@ ;
: emit ( c -- ) begin 5 uart@ $20 and 0= while pause repeat 0 uart! ;
: cr ( -- ) 13 emit 10 emit ;
: space ( -- ) bl emit ;
: spaces ( n -- ) 0 max 0 ?do space loop ;
: type ( a n -- ) 0 ?do dup @ emit 1+ loop drop ;

\ ---- strings inline in a thread: a count, then a cell a character

: (s") ( -- a n ) r> 1+ dup @ 2dup + >r swap 1+ swap ;
: (.") ( -- ) r> 1+ dup @ 2dup + >r swap 1+ swap type ;
: abort ( -- ) 'abort @ execute ;
: (abort") ( f -- ) r> 1+ dup @ 2dup + >r swap 1+ swap rot if type cr abort then 2drop ;

\ ---- numbers out

create numbuf 40 allot
: pad ( -- a ) numbuf 40 + ;
: hex ( -- ) 16 base ! ;
: decimal ( -- ) 10 base ! ;
: hold ( c -- ) hld @ 1- dup hld ! ! ;
: <# ( -- ) pad hld ! ;
: digit ( n -- c ) dup 9 > if 7 + then [char] 0 + ;
: ud/mod ( ud u -- rem udq ) >r 0 r@ um/mod r> swap >r um/mod r> ;
: # ( ud -- ud' ) base @ ud/mod rot digit hold ;
: #s ( ud -- 0 0 ) begin # 2dup or 0= until ;
: #> ( ud -- a n ) 2drop hld @ pad over - ;
: sign ( n -- ) 0< if [char] - hold then ;
: ud. ( ud -- ) <# #s #> type space ;
: u. ( u -- ) 0 ud. ;
: d. ( d -- ) tuck dabs <# #s rot sign #> type space ;
: . ( n -- ) s>d d. ;
: u.r ( u w -- ) >r 0 <# #s #> r> over - spaces type ;
: .r ( n w -- ) >r s>d tuck dabs <# #s rot sign #> r> over - spaces type ;
: .s ( -- ) [char] < emit depth 0 .r [char] > emit space
   depth 0 ?do depth i - 1- pick . loop ;

\ ---- the input line

: source ( -- a n ) 'tib @ #tib @ ;
: /string ( a n k -- a' n' ) tuck - >r + r> ;

\ A line from the console, with backspace; Return ends it.
: accept ( a n -- n )
   over + >r dup
   begin key dup 13 <> while
      dup 8 = over 127 = or if
         drop 2dup <> if 1- 8 emit space 8 emit then
      else dup bl < if drop else
         over r@ u< if dup emit over ! 1+ else drop then
      then then
   repeat drop rdrop swap - ;

variable wd
create wbuf 66 allot
: delim? ( c -- f ) wd @ bl = if bl 1+ u< else wd @ = then ;
: (parse) ( a n -- start len )
   over >r
   begin dup if over @ delim? 0= else 0 then while 1 /string repeat
   over r@ - >r  if 1+ then  source drop - >in !  r> r> swap ;
: parse ( c -- a n ) wd ! source >in @ /string (parse) ;
: word ( c -- c-addr ) wd ! source >in @ /string
   begin dup if over @ delim? else 0 then while 1 /string repeat
   (parse) 63 min dup wbuf ! wbuf 1+ swap move wbuf ;

\ ---- the dictionary: words are found whatever their case

: lower ( c -- c' ) dup [char] A [char] Z 1+ within if 32 + then ;
: same? ( a1 a2 n -- f )
   0 ?do over i + @ lower over i + @ lower <> if 2drop unloop false exit then loop
   2drop true ;
: (find) ( c-addr -- hdr | 0 )
   >r latest @
   begin dup while
      dup 1+ @ $203F and r@ @ = if
         r@ 1+ over 2 + r@ @ same? if rdrop exit then
      then @
   repeat rdrop ;
: >flags ( hdr -- x ) 1+ @ ;
: >xt ( hdr -- xt ) dup >flags $3F and + 2 + @ ;
: >body ( xt -- a ) 4 + ;

\ ---- numbers in: $ hex, % binary, # decimal, a sign, and a trailing .
\ for a double

: digit? ( c base -- n f ) >r lower [char] 0 - dup 9 > if 39 - dup 10 < if drop -1 then then dup r> u< ;
: ud* ( ud u -- ud' ) tuck * >r um* r> + ;
: >number ( ud a n -- ud' a' n' )
   begin dup while
      over @ base @ digit? 0= if drop exit then
      >r 2swap base @ ud* r> 0 d+ 2swap 1 /string
   repeat ;
: number? ( c-addr -- n 1 | d 2 | 0 )
   base @ >r count
   over @ [char] $ = if 16 base ! 1 /string then
   over @ [char] % = if 2 base ! 1 /string then
   over @ [char] # = if 10 base ! 1 /string then
   over @ [char] - = >r r@ if 1 /string then
   dup 0= if 2drop rdrop r> base ! 0 exit then
   0 0 2swap >number
   dup 0= if 2drop drop r> if negate then r> base ! 1 exit then
   1 = swap @ [char] . = and if r> if dnegate then r> base ! 2 exit then
   2drop rdrop r> base ! 0 ;

\ ---- the interpreter and compiler

: lit, ( x -- ) ['] lit , , ;
: compile, ( xt -- ) , ;
: compile-word ( hdr -- )
   dup >flags $8000 and if >xt execute exit then
   dup >flags $4000 and if
      >xt 1+ dup @ lit, 1+ dup @ ['] lit = if 1+ @ lit, else drop then exit
   then >xt , ;
: ?stack ( -- ) depth 0< if s0 sp! true abort" stack empty" then ;
: interpret ( -- )
   begin bl word dup @ while
      dup (find) ?dup if
         nip state @ if compile-word else >xt execute then
      else
         number? ?dup 0= if wbuf count type true abort"  ?" then
         state @ if 2 = if swap lit, then lit, else drop then
      then
      ?stack
   repeat drop ;
: query ( -- ) tib0 'tib !  tib0 TIB_SIZE accept #tib !  0 >in ! ;
: quit ( -- )
   r0 rp!  0 state !
   begin query space interpret state @ 0= if ."  ok" then cr again ;
: (abort) ( -- ) s0 sp! quit ;
' (abort) 'abort !

: [ ( -- ) 0 state ! ; immediate
: ] ( -- ) -1 state ! ;
: header ( "name" -- )
   bl word dup @ 0= abort" a name?"
   here latest @ , latest !  dup @ ,  count 0 ?do dup @ , 1+ loop drop ;
: flag! ( x -- ) latest @ 1+ dup @ rot or swap ! ;
: hide ( -- ) $2000 flag! ;
: reveal ( -- ) latest @ 1+ dup @ $2000 invert and swap ! ;
: : ( "name" -- ) header here 1+ , hide ] ;
: ; ( -- ) ['] exit , reveal postpone [ ; immediate
: immediate ( -- ) $8000 flag! ;
: constant ( x "name" -- ) header here 1+ , lit, ['] exit , $4000 flag! ;
: 2constant ( lo hi "name" -- ) header here 1+ , swap lit, lit, ['] exit , $4000 flag! ;
: variable ( "name" -- ) header here 1+ , here 3 + lit, ['] exit , 0 , $4000 flag! ;
: 2variable ( "name" -- ) variable 0 , ;
: create ( "name" -- ) header here 1+ , here 4 + lit, ['] exit , 0 , ;
: (does>) ( -- ) r> 1+ latest @ >xt 2 + ['] branch over ! 1+ ! ;
: does> ( -- ) ['] (does>) , ; immediate
: user ( n "name" -- ) header here 1+ , ['] (user) , , ['] exit , ;

: if ( -- a ) ['] 0branch , here 0 , ; immediate
: else ( a -- a' ) ['] branch , here 0 , swap here swap ! ; immediate
: then ( a -- ) here swap ! ; immediate
: begin ( -- a ) here ; immediate
: until ( a -- ) ['] 0branch , , ; immediate
: again ( a -- ) ['] branch , , ; immediate
: while ( a -- a' a ) postpone if swap ; immediate
: repeat ( a' a -- ) postpone again postpone then ; immediate
: >leave ( -- ) here leaves @ , leaves ! ;
: do ( -- l a ) ['] (do) , leaves @ 0 leaves ! here ; immediate
: ?do ( -- l a ) ['] (?do) , leaves @ 0 leaves ! >leave here ; immediate
: leave ( -- ) ['] unloop , ['] branch , >leave ; immediate
: resolve-leaves ( -- ) leaves @ begin ?dup while dup @ swap here swap ! repeat ;
: loop ( l a -- ) ['] (loop) , , resolve-leaves leaves ! ; immediate
: +loop ( l a -- ) ['] (+loop) , , resolve-leaves leaves ! ; immediate
: ' ( "name" -- xt ) bl word (find) dup 0= abort" ?" >xt ;
: ['] ( "name" -- ) ' lit, ; immediate
: char ( "c" -- c ) bl word 1+ @ ;
: [char] ( "c" -- ) char lit, ; immediate
: literal ( x -- ) lit, ; immediate
: postpone ( "name" -- )
   bl word (find) dup 0= abort" ?"
   dup >flags $8000 and if >xt , else >xt lit, ['] , , then ; immediate
: recurse ( -- ) latest @ >xt , ; immediate
: s, ( a n -- ) dup , 0 ?do dup @ , 1+ loop drop ;
create sbuf 80 allot
: s" ( "text" -- a n )
   [char] " parse state @ if ['] (s") , s, else 80 min >r sbuf r@ move sbuf r> then ; immediate
: ." ( "text" -- ) [char] " parse state @ if ['] (.") , s, else type then ; immediate
: abort" ( "text" -- ) ['] (abort") , [char] " parse s, ; immediate
: ( ( "text" -- ) [char] ) parse 2drop ; immediate
: \ ( "text" -- ) source nip >in ! ; immediate
: .( ( "text" -- ) [char] ) parse type ; immediate

\ ---- looking around

: .name ( hdr -- ) 1+ count $3F and type ;
: words ( -- ) latest @ begin ?dup while dup .name space @ repeat cr ;
: ? ( a -- ) @ . ;
