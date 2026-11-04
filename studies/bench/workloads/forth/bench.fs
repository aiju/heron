\ The program the Forth workload compiles and runs: classic jobs for a
\ small machine, each folding what it finds into results it reports at
\ the end. workload.py puts the size's parameters in front of this text
\ as constants, and reference() does the same jobs in Python.

\ ---- tools

: bounds ( a n -- a+n a ) over + swap ;
: erase ( a n -- ) 0 fill ;
: array ( n "name" -- ) create cells allot  does> ( i -- a ) swap cells + ;

\ A checksum of bytes, as the harness's bench_hash: h <- h * 33 xor byte,
\ by a shift and an add
: checksum ( a n -- h ) 5381 -rot bounds ?do dup 5 lshift + i c@ xor loop ;

\ Random numbers: a linear congruential generator's top 16 bits
variable seed
: random ( -- u ) seed @ 1103515245 * 12345 + dup seed ! 16 rshift ;

\ Text out, into a buffer, with Forth's pictured numbers
create out 8192 allot
variable #out
: out-char ( c -- ) out #out @ + c!  1 #out +! ;
: out-type ( a n -- ) tuck out #out @ + swap move  #out +! ;
create digits 12 allot
variable hld
: hold ( c -- ) -1 hld +!  hld @ c! ;
: # ( u -- u' ) 10 /mod swap [char] 0 + hold ;
: out-u ( u -- ) digits 12 + hld !  begin # dup 0= until drop
  hld @  digits 12 + over - out-type ;

\ ---- the sieve of Eratosthenes, as BYTE ran it: flag i is 2i + 3

create flags sieve-size allot
: sieve ( -- primes )
  flags sieve-size 1 fill
  0  sieve-size 0 do
    flags i + c@ if
      i 2* 3 +
      dup i +  begin dup sieve-size < while
        0 over flags + c!  over +
      repeat  2drop  1+
    then
  loop ;

\ ---- recursion: Fibonacci, and the n queens

: fib ( n -- fib ) dup 2 < if exit then  dup 1- recurse  swap 2 - recurse + ;

\ The queens go on a row at a time, the columns and diagonals they take
\ as bit masks: cols, and left and right, which move a column each row
variable full
variable solutions
: try ( cols left right -- )
  2 pick full @ = if drop 2drop 1 solutions +! exit then
  2dup or 3 pick or invert full @ and              ( c l r free )
  begin ?dup while
    dup negate over and  tuck xor >r               ( c l r bit )
    3 pick over or  3 pick 2 pick or 2*  3 pick 3 pick or 1 rshift
    recurse drop r>
  repeat drop 2drop ;
: queens ( n -- solutions )
  1 swap lshift 1- full !  0 solutions !  0 0 0 try  solutions @ ;

\ ---- quicksort, of cells, in the order a word ( x y -- f ) gives

variable 'before
: exchange ( a1 a2 -- ) 2dup @ swap @ rot ! swap ! ;

\ Lomuto's partition, the cell at hi the pivot
variable pivot
: partition ( lo hi -- mid )
  dup @ pivot !
  2dup swap ?do                                    ( store hi )
    i @ pivot @ 'before @ execute if  over i exchange  swap cell+ swap  then
  4 +loop
  over exchange ;

: qsort ( lo hi -- )
  2dup < if
    2dup partition  rot over 4 - recurse  cell+ swap recurse
  else 2drop then ;
: sort ( a n -- ) 1- cells over + qsort ;

\ Random numbers sorted, and written out
sort-n array numbers
: sorting ( -- )
  12345 seed !  sort-n 0 do random i numbers ! loop
  ['] < 'before !  0 numbers sort-n sort
  0 #out !  sort-n 0 do i numbers @ out-u 32 out-char loop ;

\ ---- the game of life, on a board of life-size squares a side inside a
\ border of dead ones

life-size 2 + constant stride
stride dup * constant area
create board-a area allot
create board-b area allot
variable board
variable next-board

\ The square and its eight neighbours: three is born or stays, four stays
: row3 ( a -- n ) dup c@  over 1+ c@ +  swap 2 + c@ + ;
: nine ( a -- n ) stride - 1-  dup row3  over stride + row3 +  swap stride 2* + row3 + ;
: rule ( alive n -- alive' ) dup 3 = if 2drop 1 exit then  4 = and 1 and ;

: generation ( -- )
  life-size 1+ 1 do
    i stride * 1+  dup life-size + swap do
      board @ i +  dup c@ swap nine rule  next-board @ i + c!
    loop
  loop
  board @ next-board @  board ! next-board ! ;

: life ( -- )
  board-a area erase  board-b area erase
  board-a board !  board-b next-board !  777 seed !
  life-size 1+ 1 do  life-size 1+ 1 do
    random 3 and 0= 1 and  j stride * i + board-a + c!
  loop loop
  life-gens 0 do generation loop ;

\ ---- the text, counted as wc counts it, and how often each word comes,
\ in a hash table; a word is a run of letters, upper case read as lower

variable lines
variable words
create word 64 allot
variable len
256 constant buckets
buckets array bucket
variable distinct
4096 array entries
\ An entry: the next in its bucket, the count, the word as counted string;
\ entries holds them all, in the order they came
: entry-name ( e -- a n ) 2 cells + count ;

: string-hash ( a n -- u ) 0 -rot bounds ?do 31 * i c@ + loop  buckets 1- and ;
: lookup ( a n -- e | 0 )
  2dup string-hash bucket @
  begin dup while
    >r 2dup r@ entry-name compare 0= if 2drop r> exit then  r> @
  repeat nip nip ;
: new-entry ( a n -- e )
  2dup string-hash bucket  align here >r  dup @ ,  r@ swap !
  0 ,  dup c,  here swap dup allot move  align
  r@ distinct @ entries !  1 distinct +!  r> ;

: add-word ( -- )
  len @ if
    1 words +!
    word len @  2dup lookup ?dup if nip nip else new-entry then
    1 swap cell+ +!  0 len !
  then ;

: wc ( -- chars )
  0 lines !  0 words !  0 len !  0 distinct !
  0 bucket buckets cells erase
  corpus dup >r  bounds do
    i c@  dup 10 = if 1 lines +! then
    dup [char] A - 26 u< if 32 + then
    dup [char] a - 26 u< if  word len @ + c!  1 len +!  else drop add-word then
  loop  add-word  r> ;

\ The words and their counts in alphabetical order, written out
: before-name ( e1 e2 -- f ) >r entry-name r> entry-name compare 0< ;
: table ( -- )
  ['] before-name 'before !  0 entries distinct @ sort
  0 #out !  distinct @ 0 do
    i entries @  dup entry-name out-type  32 out-char  cell+ @ out-u  10 out-char
  loop ;

\ ---- the run

: run ( -- )
  sieve s" primes" report
  fib-n fib s" fib" report
  queens-n queens s" queens" report
  sorting  out #out @ checksum s" sorted" report
  life  board @ area checksum s" life" report
  wc s" chars" report  lines @ s" lines" report
  words @ s" words" report  distinct @ s" distinct" report
  table  out #out @ checksum s" table" report ;
run
