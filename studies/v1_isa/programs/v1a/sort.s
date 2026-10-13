; sort: quicksort 256 random numbers, insertion-sort 64 more; check that both
; came out sorted and print a checksum and a few of the values.
;
; The numbers are the 16-bit outputs of lib/rand.s (seed 12345), one per
; 32-bit word, compared unsigned. Arrays are passed as word pointers.

        .include "lib/start.s"

main:   LI   r1, #12345
        BSR  srand

        ; ---- quicksort ----
        LEA  r1, big
        LI   r2, #256
        BSR  fill
        LEA  r1, big
        LEA  r2, big + 4 * 255
        BSR  qsort
        LEA  r1, s_quick
        BSR  puts
        LEA  r1, big
        LI   r2, #256
        BSR  report
        LEA  r1, big
        LEA  r2, bigshow
        BSR  show

        ; ---- insertion sort ----
        LEA  r1, small
        MVI  r2, 64
        BSR  fill
        LEA  r1, small
        MVI  r2, 64
        BSR  isort
        LEA  r1, s_insert
        BSR  puts
        LEA  r1, small
        MVI  r2, 64
        BSR  report
        LEA  r1, small
        LEA  r2, smallshow
        BRA  show               ; tail call

; fill: r1 = array, r2 = count: store count random numbers.
fill:   SAVE r8-r9
        MOV  r8, r1
        MOV  r9, r2
.loop:  BSR  rand               ; clobbers r1, r2
        ST   r1, [r8]
        ADDI r8, 4
        ADDI r9, -1
        BNE  .loop
        RESTORE r8-r9
        RET

; qsort: sort the words from r1 to r2 (both inclusive) as unsigned numbers.
; Hoare partition around the middle element. It recurses into the smaller
; part and loops on the larger one, so the stack depth stays below log2(n).
qsort:  SAVE r8-r10
        MOV  r8, r1             ; r8 = lo
        MOV  r9, r2             ; r9 = hi
.again: CMP  r8, r9
        BHS  .done              ; fewer than two elements
        MOV  r3, r9             ; pivot = the middle element,
        SUB  r3, r8             ; lo + (hi - lo) / 2 rounded down to a word
        LSR  r3, #1
        BIC  r3, #3
        ADD  r3, r8
        LD   r10, [r3]
        MOV  r1, r8             ; r1 = &a[i]
        MOV  r2, r9             ; r2 = &a[j]
        BRA  .si
.nexti: ADDI r1, 4
.si:    LD   r3, [r1]           ; while a[i] < pivot: i++
        CMP  r3, r10
        BLO  .nexti
        BRA  .sj
.nextj: ADDI r2, -4
.sj:    LD   r4, [r2]           ; while a[j] > pivot: j--
        CMP  r10, r4
        BLO  .nextj
        CMP  r1, r2
        BHI  .split             ; i > j: partitioned
        ST   r4, [r1]           ; swap a[i] and a[j], i++, j--
        ST   r3, [r2]
        ADDI r1, 4
        ADDI r2, -4
        CMP  r1, r2
        BLS  .si
.split: MOV  r3, r2             ; now lo..j and i..hi are left. j can be lo - 4,
        SUB  r3, r8             ; so the sizes are compared signed
        MOV  r4, r9
        SUB  r4, r1
        CMP  r3, r4
        BGE  .right
        MOV  r10, r1            ; left part is smaller: sort it, loop on i..hi
        MOV  r1, r8
        BSR  qsort              ; r2 = j already
        MOV  r8, r10
        BRA  .again
.right: MOV  r10, r2            ; right part is smaller: sort it, loop on lo..j
        MOV  r2, r9
        BSR  qsort              ; r1 = i already
        MOV  r9, r10
        BRA  .again
.done:  RESTORE r8-r10
        RET

; isort: insertion sort of r2 >= 2 words at r1, unsigned.
isort:  MOV  r5, r1             ; r5 = start
        LSL  r2, #2
        ADD  r2, r1             ; r2 = end
        MOV  r3, r1             ; r3 = &a[k], the next element to insert,
        ADDI r3, 4              ; from k = 1
.outer: LD   r6, [r3]           ; r6 = v = a[k]
        MOV  r4, r3             ; r4 = &a[p], from p = k - 1 down
        ADDI r4, -4
.inner: LD   r7, [r4]
        CMP  r7, r6
        BLS  .place             ; a[p] <= v: v goes just above it
        ST   r7, [r4 + 4]       ; move a[p] up into the hole
        ADDI r4, -4
        CMP  r4, r5
        BHS  .inner             ; until a[0] has moved (r4 = start - 4)
.place: ST   r6, [r4 + 4]
        ADDI r3, 4
        CMP  r3, r2
        BLO  .outer
        RET

; report: r1 = array, r2 = count: print "sorted" or "NOT sorted" and a
; Fletcher-style checksum (s1 += x; s2 += s1; both mod 2^16, so the sums run
; in 32 bits and only the low 4 hex digits are printed).
report: SAVE r8-r9
        MVI  r3, 0              ; s1
        MVI  r4, 0              ; s2
        MVI  r5, 0              ; the previous value
        MVI  r6, 0              ; minus the number of out-of-order pairs
.loop:  LD   r7, [r1]
        ADD  r3, r7
        ADD  r4, r3
        CMP  r7, r5             ; C = 0 (borrow) if smaller than the previous one
        SBC  r6, r0             ; r6 -= borrow
        MOV  r5, r7
        ADDI r1, 4
        ADDI r2, -1
        BNE  .loop
        MOV  r8, r3
        MOV  r9, r4
        LEA  r1, s_sorted
        TST  r6, r6
        BEQ  .ok
        LEA  r1, s_notsorted
.ok:    BSR  puts
        MOV  r1, r8
        MVI  r2, 4
        BSR  print_hex
        BSR  space
        MOV  r1, r9
        MVI  r2, 4
        BSR  print_hex
        BSR  newline
        RESTORE r8-r9
        RET

; show: r1 = array, r2 = list of indices (bytes, count first): print
; "  a[i]=value a[i]=value ..." on one line.
show:   SAVE r8-r10
        MOV  r8, r1
        MOV  r9, r2             ; r9 -> the current index
        LDB  r10, [r9]          ; r10 = count
        BSR  space
.loop:  ADDI r9, 1
        BSR  space
        LEA  r1, s_a
        BSR  puts
        LDB  r1, [r9]
        BSR  print_u32
        LEA  r1, s_eq
        BSR  puts
        LDB  r1, [r9]           ; a[i]
        LSL  r1, #2
        ADD  r1, r8
        LD   r1, [r1]
        BSR  print_u32
        ADDI r10, -1
        BNE  .loop
        RESTORE r8-r10
        BRA  newline

s_quick:     .asciz "quicksort 256: "
s_insert:    .asciz "insertion sort 64: "
s_notsorted: .ascii "NOT "
s_sorted:    .asciz "sorted, checksum "
s_a:         .asciz "a["
s_eq:        .asciz "]="
bigshow:     .byte 6, 0, 1, 127, 128, 254, 255
smallshow:   .byte 3, 0, 31, 63

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/rand.s"

        .align 4
big:    .space 4 * 256
small:  .space 4 * 64
