; sort: quicksort 256 random numbers, insertion-sort 64 more; check that both
; came out sorted and print a checksum and a few of the values.
;
; The numbers are the 16-bit outputs of lib/rand.s (seed 12345), one per
; 32-bit word, compared unsigned. Arrays are passed as word pointers.

        .include "lib/start.s"

main:   MOV  r1, #12345
        BSR  srand

        ; ---- quicksort ----
        MOV  r1, #big
        MOV  r2, #256
        BSR  fill
        MOV  r1, #big
        MOV  r2, #big + 4 * 255
        BSR  qsort
        LEA  r1, [s_quick]
        BSR  puts
        MOV  r1, #big
        MOV  r2, #256
        BSR  report
        MOV  r1, #big
        LEA  r2, [bigshow]
        BSR  show

        ; ---- insertion sort ----
        MOV  r1, #small
        MOV  r2, #64
        BSR  fill
        MOV  r1, #small
        MOV  r2, #64
        BSR  isort
        LEA  r1, [s_insert]
        BSR  puts
        MOV  r1, #small
        MOV  r2, #64
        BSR  report
        MOV  r1, #small
        LEA  r2, [smallshow]
        BRA  show               ; tail call

; fill: r1 = array, r2 = count: store count random numbers.
fill:   SAVE r8-r9
        MOV  r8, r1
        MOV  r9, r2
.loop:  BSR  rand               ; clobbers r1, r2
        MOV  [r8]+, r1
        DEC  r9
        BNE  .loop
        RESTORE r8-r9
        RET

; qsort: sort the words from r1 to r2 (both inclusive) as unsigned numbers.
; Hoare partition around the middle element. It recurses into the smaller
; part and loops on the larger one, so the stack depth stays below log2(n).
;
; The scans load and step the pointer in one instruction: [r1]+ for i going
; up, -[r2] for j going down, so during the partition r1 = &a[i] and
; r2 = &a[j] + 4. (Comparing the pivot straight with memory, CMP r10, [r1]+,
; saves an instruction per step but then the swap has to load both values
; again; that came out 1.3% slower overall.)
qsort:  SAVE r8-r10
        MOV  r8, r1             ; r8 = lo
        MOV  r9, r2             ; r9 = hi
.again: CMP  r8, r9
        BHS  .done              ; fewer than two elements
        MOV  r3, r9             ; pivot = the middle element,
        SUB  r3, r8             ; lo + (hi - lo) / 2 rounded down to a word
        LSR  r3, #1
        AND  r3, #-4
        MOV  r10, [r8 + r3]
        MOV  r1, r8             ; r1 = &a[i]
        LEA  r2, [r9 + 4]       ; r2 = &a[j] + 4
.si:    MOV  r3, [r1]+          ; while a[i] < pivot: i++
        CMP  r3, r10
        BLO  .si
        SUB  r1, #4             ; (the scan went one past a[i])
.sj:    MOV  r4, -[r2]          ; while a[j] > pivot: j--
        CMP  r10, r4
        BLO  .sj                ; now r2 = &a[j]
        CMP  r1, r2
        BHI  .split             ; i > j: partitioned
        MOV  [r1]+, r4          ; swap a[i] and a[j], and i++
        MOV  [r2], r3           ; (j-- comes with the next -[r2])
        CMP  r1, r2             ; i <= j, i.e. r1 <= r2 - 4: carry on
        BLO  .si
        SUB  r2, #4             ; r2 = &a[j]
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
; Two pointers walk down together with -[r]: r4 reads the elements below the
; hole, r1 writes the hole, so every access is a one-parcel instruction and
; both ways out of the inner loop leave the hole at -[r1].
isort:  MOV  r5, r1             ; r5 = start
        LSL  r2, #2
        ADD  r2, r1             ; r2 = end
        LEA  r3, [r1 + 4]       ; r3 = &a[k], the next element to insert, from k = 1
.outer: MOV  r6, [r3]+          ; r6 = v = a[k], r3 = &a[k + 1]
        MOV  r1, r3             ; -[r1] is the hole, a[k] first
        LEA  r4, [r3 - 4]       ; -[r4] is the element below it, a[k - 1] first
.inner: MOV  r7, -[r4]
        CMP  r7, r6
        BLS  .place             ; a[p] <= v: v goes just above it
        MOV  -[r1], r7          ; move a[p] up into the hole
        CMP  r4, r5
        BHI  .inner             ; until a[0] has moved
.place: MOV  -[r1], r6
        CMP  r3, r2
        BLO  .outer
        RET

; report: r1 = array, r2 = count: print "sorted" or "NOT sorted" and a
; Fletcher-style checksum (s1 += x; s2 += s1; both mod 2^16, so the sums run
; in 32 bits and only the low 4 hex digits are printed).
report: SAVE r8-r9
        MOV  r3, #0             ; s1
        MOV  r4, #0             ; s2
        MOV  r5, #0             ; the previous value
        MOV  r6, #0             ; minus the number of out-of-order pairs
        CLR  r0                 ; r0 = 0, for the SBC
.loop:  MOV  r7, [r1]+
        ADD  r3, r7
        ADD  r4, r3
        CMP  r7, r5             ; C = 0 (borrow) if smaller than the previous one
        SBC  r6, r0             ; r6 -= borrow
        MOV  r5, r7
        DEC  r2
        BNE  .loop
        MOV  r8, r3
        MOV  r9, r4
        LEA  r1, [s_sorted]
        TST  r6, r6
        BEQ  .ok
        LEA  r1, [s_notsorted]
.ok:    BSR  puts
        MOV  r1, r8
        MOV  r2, #4
        BSR  print_hex
        BSR  space
        MOV  r1, r9
        MOV  r2, #4
        BSR  print_hex
        BSR  newline
        RESTORE r8-r9
        RET

; show: r1 = array, r2 = list of indices (bytes, count first): print
; "  a[i]=value a[i]=value ..." on one line.
show:   SAVE r8-r10
        MOV  r8, r1
        MOV  r9, r2
        MOV  r10, byte [r9]+    ; r10 = count, r9 -> the first index
        BSR  space
.loop:  BSR  space
        LEA  r1, [s_a]
        BSR  puts
        MOV  r1, byte [r9]
        BSR  print_u32
        LEA  r1, [s_eq]
        BSR  puts
        MOV  r1, byte [r9]+
        MOV  r1, [r8 + r1*4]    ; a[i]
        BSR  print_u32
        DEC  r10
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
