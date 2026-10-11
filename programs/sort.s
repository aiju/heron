; sort: quicksort 256 random words, insertion-sort 64 more; check that both
; came out sorted and print a checksum and a few values.

        .include "lib/start.s"

main:   LI   r1, #12345
        CALL srand

        ; ---- quicksort ----
        LI   r1, #big
        LI   r2, #256
        CALL fill
        LI   r1, #big
        LI   r2, #big + 2 * 255
        CALL qsort
        LI   r1, #s_quick
        CALL puts
        LI   r1, #big
        LI   r2, #256
        CALL report
        LI   r1, #bigshow
        CALL show

        ; ---- insertion sort ----
        LI   r1, #small
        MVI  r2, 64
        CALL fill
        LI   r1, #small
        MVI  r2, 64
        CALL isort
        LI   r1, #s_insert
        CALL puts
        LI   r1, #small
        MVI  r2, 64
        CALL report
        LI   r1, #smallshow
        CALL show
        RET

; fill: r1 = array, r2 = count: store count random words.
fill:   PUSH r8
        PUSH r9
        MOV  r8, r1
        MOV  r9, r2
.loop:  CALL rand               ; clobbers r1, r2
        ST   r1, [r8]
        ADDI r8, 2
        DEC  r9
        BNE  .loop
        POP  r9
        POP  r8
        RET

; qsort: sort the words from r1 to r2 (both inclusive) as unsigned numbers.
; Hoare partition around the middle element. It recurses into the smaller
; part and loops on the larger one, so the stack depth stays below log2(n).
qsort:  PUSH r8
        PUSH r9
        PUSH r10
        MOV  r8, r1             ; r8 = lo
        MOV  r9, r2             ; r9 = hi
.again: CMP  r8, r9
        BHS  .done              ; fewer than two elements
        MOV  r3, r9             ; pivot = the middle element
        SUB  r3, r8
        SHR  r3
        BIC  r3, #1             ; keep it word aligned
        ADD  r3, r8
        LD   r10, [r3]
        MOV  r1, r8             ; r1 = i
        MOV  r2, r9             ; r2 = j
.scani: LD   r3, [r1]           ; while a[i] < pivot: i++
        CMP  r3, r10
        BHS  .scanj
        ADDI r1, 2
        BRA  .scani
.scanj: LD   r4, [r2]           ; while a[j] > pivot: j--
        CMP  r10, r4
        BHS  .check
        ADDI r2, -2
        BRA  .scanj
.check: CMP  r1, r2
        BHI  .split
        ST   r4, [r1]           ; swap a[i] and a[j]
        ST   r3, [r2]
        ADDI r1, 2
        ADDI r2, -2
        CMP  r1, r2
        BLS  .scani
.split: MOV  r3, r2             ; now lo..j and i..hi are left. j can be lo - 2,
        SUB  r3, r8             ; so these sizes are compared signed
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
.done:  POP  r10
        POP  r9
        POP  r8
        RET

; isort: insertion sort of r2 words at r1, unsigned.
isort:  MOV  r5, r1             ; r5 = start
        SHL  r2
        ADD  r2, r1             ; r2 = end
        MOV  r3, r1             ; r3 = next element to insert
.outer: ADDI r3, 2
        CMP  r3, r2
        BHS  .done
        LD   r6, [r3]           ; r6 = value
        MOV  r4, r3             ; r4 = the slot before the hole, so the moves
        ADDI r4, -2             ; are [r4] -> [r4 + 2]: offsets can't be negative
.inner: CMP  r4, r5
        BLO  .place
        LD   r7, [r4]
        CMP  r7, r6
        BLS  .place
        ST   r7, [r4 + 2]
        ADDI r4, -2
        BRA  .inner
.place: ST   r6, [r4 + 2]
        BRA  .outer
.done:  RET

; report: r1 = array, r2 = count: print "sorted" or "NOT sorted" and a
; Fletcher-style checksum (s1 += x; s2 += s1, both mod 2^16).
report: PUSH r8
        PUSH r9
        PUSH r10
        MOV  r8, r1
        MOV  r9, r2
        MVI  r3, 0              ; s1
        MVI  r4, 0              ; s2
        MVI  r5, 0              ; previous value
        MVI  r6, 0              ; 1 if out of order
.loop:  LD   r7, [r1]
        ADD  r3, r7
        ADD  r4, r3
        CMP  r7, r5
        BHS  .inorder
        MVI  r6, 1
.inorder:
        MOV  r5, r7
        ADDI r1, 2
        DEC  r2
        BNE  .loop
        MOV  r10, r4
        MOV  r9, r3
        LI   r1, #s_sorted
        TST  r6, r6
        BEQ  .ok
        LI   r1, #s_notsorted
.ok:    CALL puts
        MOV  r1, r9
        CALL print_hex16
        CALL space
        MOV  r1, r10
        CALL print_hex16
        CALL newline
        POP  r10
        POP  r9
        POP  r8
        RET

; show: r1 = list of (label, address) pairs ending in 0: print "label=value".
show:   PUSH r8
        MOV  r8, r1
.loop:  LD   r1, [r8]
        BEQ  .done
        CALL puts
        LD   r1, [r8 + 2]
        LD   r1, [r1]
        CALL print_u16
        ADDI r8, 4
        BRA  .loop
.done:  POP  r8
        JMP  newline

s_quick:    .asciz "quicksort 256: "
s_insert:   .asciz "insertion sort 64: "
s_sorted:   .asciz "sorted, checksum "
s_notsorted: .asciz "NOT sorted, checksum "
s_a0:       .asciz "  a[0]="
s_a1:       .asciz " a[1]="
s_a31:      .asciz " a[31]="
s_a63:      .asciz " a[63]="
s_a127:     .asciz " a[127]="
s_a128:     .asciz " a[128]="
s_a254:     .asciz " a[254]="
s_a255:     .asciz " a[255]="
        .align 2
bigshow:    .word s_a0, big, s_a1, big + 2, s_a127, big + 254, s_a128, big + 256
            .word s_a254, big + 508, s_a255, big + 510, 0
smallshow:  .word s_a0, small, s_a31, small + 62, s_a63, small + 126, 0

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/rand.s"

big:    .space 512
small:  .space 128
