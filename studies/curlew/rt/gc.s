; The copying collector (Cheney's), and how big objects are.
;
; A value is a pointer if its tag is 01 or 10 and it points into the half
; being collected. An indirection is never copied: a pointer to one
; becomes its value, so a collection also removes every indirection it
; meets. An object that has been copied gets FWD in its first word and
; the new value in its second (every object has two words at least).

; rt_gc: collect. The code calling it has saved its live values on the
; stack; r12 = the bytes it wants to allocate. Uses r0-r10 and r12; sets
; r13 and r14. Keeps r11 (which may hold the mask 1).
rt_gc:  MOV  -[sp], r7
        MOV  [gc_need], r12
        INC  [gc_count]
        MOV  r1, r14
        SUB  r1, [cur_start]
        ADD  r1, [gc_alloc]
        MOV  [gc_alloc], r1
        ; swap the halves: r8, r9 = the half being collected
        MOV  r8, [cur_start]
        MOV  r9, [cur_end]
        MOV  r1, [other_start]
        MOV  r2, [other_end]
        MOV  [cur_start], r1
        MOV  [cur_end], r2
        MOV  [other_start], r8
        MOV  [other_end], r9
        MOV  r14, r1
        ; the roots: the stack, the CAFs, the runtime's
        MOV  r10, sp
        MOV  r6, #STACK_TOP
        BSR  evac_range
        MOV  r10, #caf_start
        MOV  r6, #caf_end
        BSR  evac_range
        MOV  r10, #rt_roots
        MOV  r6, #rt_roots_end
        BSR  evac_range
        ; what has been copied, copying what it points to
        MOV  r10, [cur_start]
.scan:  CMP  r10, r14
        BHS  .done
        MOV  r1, [r10]
        MOV  r2, r1
        AND  r2, #3
        CMP  r2, #3
        BEQ  .obj
        MOV  r6, r10            ; a pair: both words
        ADD  r6, #8
        BSR  evac_range
        BRA  .scan
.obj:   MOV  r3, r10
        BSR  objsize            ; r1 = the header, r3 = the object -> r5 = words
        LSL  r5, #2
        MOV  r6, r10
        ADD  r6, r5
        ADD  r10, #4            ; the words after the header
        BSR  evac_range
        BRA  .scan
.done:  MOV  r1, r14
        SUB  r1, [cur_start]
        ADD  r1, [gc_copied]
        MOV  [gc_copied], r1
        MOV  r13, [cur_end]
        SUB  r13, #SLACK
        ; room for what was wanted, and SLACK for the next check
        MOV  r1, [gc_need]
        CMP  r1, #SLACK
        BHS  .big
        MOV  r1, #SLACK
.big:   ADD  r1, r14
        CMP  r1, [cur_end]
        BHI  rt_heap
        MOV  r7, [sp]+
        RET

; evac_range: evacuate the words from r10 up to r6, in place. Uses r1-r5.
evac_range:
        MOV  -[sp], r7
.loop:  CMP  r10, r6
        BHS  .end
        MOV  r1, [r10]
        BSR  evac
        MOV  [r10]+, r1
        BRA  .loop
.end:   MOV  r7, [sp]+
        RET

; evac: r1 = a value -> r1 = where it is now, copying its object into the
; new half if it hadn't been. Uses r2-r5; r8, r9 = the old half.
evac:   MOV  r2, r1
        AND  r2, #3
        BEQ  .ret               ; an immediate
        CMP  r2, #3
        BEQ  .ret               ; not a value (a header)
        MOV  r3, r1
        SUB  r3, r2             ; the object
        CMP  r3, r8
        BLO  .ret               ; static, or outside the heap
        CMP  r3, r9
        BHS  .ret
        MOV  r4, [r3]
        CMP  r4, #FWD
        BEQ  .moved
        CMP  r2, #1
        BNE  .eval
        CMP  r4, #ind_entry + 1
        BNE  .hdr
        MOV  r1, [r3 + 4]       ; an indirection: its value, which is evaluated
        BRA  evac
.eval:  MOV  r5, r4
        AND  r5, #3
        CMP  r5, #3
        BEQ  .hdr
        MOV  r5, #2             ; a pair
        BRA  .copy
.hdr:   MOV  r1, r4
        MOV  -[sp], r7
        BSR  objsize            ; -> r5 words
        MOV  r7, [sp]+
.copy:  MOV  r1, r14
        ADD  r1, r2             ; the new value
        MOV  r4, r3
.cp:    MOV  r2, [r4]+
        MOV  [r14]+, r2
        DBNZ r5, .cp
        MOV  r2, #FWD
        MOV  [r3], r2
        MOV  [r3 + 4], r1
.ret:   RET
.moved: MOV  r1, [r3 + 4]
        RET

; objsize: r1 = an object's header, r3 = the object -> r5 = its size in
; words. Uses r4.
objsize:
        MOV  r5, [r1 - 7]       ; the info word
        MOV  r4, r5
        AND  r4, #255
        CMP  r4, #K_PAP
        BEQ  .pap
        LSR  r5, #16
        RET
.pap:   MOV  r5, [r3 + 8]       ; 4n
        LSR  r5, #2
        ADD  r5, #3
        RET
