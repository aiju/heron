; Allocation and the copying garbage collector.

; cons: r3 = car, r4 = cdr -> r1 = the pair. Keeps r2-r12.
cons:   CMP  r14, [cons_limit]
        BHI  .gc
.go:    ST   r3, [r14]+
        ST   r4, [r14]+
        LEA  r1, [r14 - 7]
        RET
.gc:    BSR  gc
        CMP  r14, [cons_limit]
        BHI  heap_full
        BRA  .go

; cons_r: cons with r11 = car, r12 = cdr. Keeps r2-r12.
cons_r: CMP  r14, [cons_limit]
        BHI  .gc
.go:    ST   r11, [r14]+
        ST   r12, [r14]+
        LEA  r1, [r14 - 7]
        RET
.gc:    PUSH r11                ; (r9-r12 aren't roots)
        PUSH r12
        BSR  gc
        POP  r12
        POP  r11
        CMP  r14, [cons_limit]
        BHI  heap_full
        BRA  .go

; alloc: r2 = bytes (a multiple of 8) -> r1 = the (untagged) address.
; Keeps r2-r12. The caller must fill in the object before anything else
; can allocate.
alloc:  MOV  r1, r14
        ADD  r1, r2
        CMP  r1, [heap_limit]
        BHI  .gc
        MOV  r1, r14
        ADD  r14, r2
        RET
.gc:    BSR  gc
        MOV  r1, r14
        ADD  r1, r2
        CMP  r1, [heap_limit]
        BHI  heap_full
        MOV  r1, r14
        ADD  r14, r2
        RET

; gc: collect. Keeps r1-r12: r1-r8 are roots, updated if they point into
; the heap; r9-r12 are not, and come back as they were.
;
; Registers while collecting: r10 = the old half's start, r11 = its size,
; r14 = the next free byte in the new half, r12 = the scan pointer.
gc:     ST   r9, [gc_save]
        ST   r10, [gc_save + 4]
        ST   r11, [gc_save + 8]
        ST   r12, [gc_save + 12]
        SAVE r1-r8
        MOV  r1, [gc_count]
        INC  r1
        ST   r1, [gc_count]
        MOV  r1, r14            ; bytes allocated in this half
        SUB  r1, [cur_start]
        ADD  r1, [gc_alloc]
        ST   r1, [gc_alloc]
        ; swap the halves
        MOV  r10, [cur_start]
        MOV  r11, [cur_end]
        MOV  r1, [old_start]
        MOV  r2, [old_end]
        ST   r10, [old_start]
        ST   r11, [old_end]
        ST   r1, [cur_start]
        ST   r2, [cur_end]
        SUB  r11, r10           ; the old half's size
        MOV  r14, r1
        ; the roots: the root block, symbol space and the stack
        MOV  r6, #roots
        MOV  r7, #roots_end
        BSR  fwd_range
        MOV  r6, #SYM_BASE
        MOV  r7, [sym_free]
        BSR  fwd_range
        MOV  r6, sp
        MOV  r7, #STACK_TOP
        BSR  fwd_range
        ; scan what has been copied, copying what it points to
        MOV  r12, [cur_start]
.scan:  CMP  r12, r14
        BHS  .done
        MOV  r1, [r12]
        MOV  r2, r1
        AND  r2, #7
        CMP  r2, #5
        BEQ  .obj
        BSR  fwd                ; a pair: both words
        ST   r1, [r12]+
        MOV  r1, [r12]
        BSR  fwd
        ST   r1, [r12]+
        BRA  .scan
.obj:   BSR  objsize            ; r1 = header -> r2 = bytes, r3 = 1 if raw
        MOV  r7, r12
        ADD  r12, r2
        CMP  r3, #0
        BNE  .scan              ; a string: nothing to scan
        MOV  r6, r1             ; the fields: words 1 .. n
        LSR  r6, #8
        LSL  r6, #2
        ADD  r6, r7
        ADD  r6, #4             ; the end of the fields
        ADD  r7, #4
.field: CMP  r7, r6
        BHS  .scan
        MOV  r1, [r7]
        BSR  fwd
        ST   r1, [r7]+
        BRA  .field
.done:  MOV  r1, r14            ; bytes copied
        SUB  r1, [cur_start]
        ADD  r1, [gc_copied]
        ST   r1, [gc_copied]
        MOV  r1, r14            ; what this collection kept counts as allocated again
        SUB  r1, [cur_start]
        MOV  r2, [gc_alloc]
        SUB  r2, r1
        ST   r2, [gc_alloc]
        MOV  r1, [cur_end]
        ST   r1, [heap_limit]
        SUB  r1, #8
        ST   r1, [cons_limit]
.if gcverify
        BSR  gc_verify
.endif
        RESTORE r1-r8
        MOV  r9, [gc_save]
        MOV  r10, [gc_save + 4]
        MOV  r11, [gc_save + 8]
        MOV  r12, [gc_save + 12]
        RET

; fwd_range: update every word from r6 up to r7. Uses r1-r5.
fwd_range:
.loop:  CMP  r6, r7
        BHS  .done
        MOV  r1, [r6]
        BSR  fwd
        ST   r1, [r6]+
        BRA  .loop
.done:  RET

; objsize: r1 = a header -> r2 = the object's size in bytes (rounded up
; to 8), r3 = 1 for a string (its contents aren't values). Keeps r1.
objsize:
        MOV  r2, r1
        LSR  r2, #8             ; n
        MOV  r3, r1
        AND  r3, #0xF8
        CMP  r3, #T_STR << 3
        BEQ  .str
        LSL  r2, #2             ; 4 + 4n
        ADD  r2, #4 + 7
        AND  r2, #-8
        MOV  r3, #0
        RET
.str:   ADD  r2, #8 + 7         ; 8 + n
        AND  r2, #-8
        MOV  r3, #1
        RET

; fwd: r1 = a value -> r1 = its new value: if it points into the old half,
; the object is copied (once) and the pointer moves to the copy.
; Uses r2-r5; r10, r11 = the old half, r14 = where copies go.
fwd:    MOV  r2, r1
        AND  r2, #5
        CMP  r2, #1
        BNE  .keep              ; not a pointer (tag 001 or 011)
        MOV  r2, r1
        AND  r2, #-8            ; the object
        MOV  r3, r2
        SUB  r3, r10
        CMP  r3, r11
        BHS  .keep              ; not in the old half
        MOV  r3, [r2]           ; its first word
        MOV  r4, r3
        AND  r4, #7
        CMP  r4, #7
        BEQ  .moved
        MOV  r4, r1
        AND  r4, #7
        OR   r4, r14            ; the new pointer
        MOV  r5, r1
        AND  r5, #2
        BNE  .obj
        ST   r3, [r14]+         ; a pair: two words
        MOV  r3, [r2 + 4]
        ST   r3, [r14]+
        BRA  .fwd
.obj:   PUSH r1                 ; an object: its size from the header
        PUSH r2
        MOV  r1, r3
        BSR  objsize            ; r2 = bytes
        MOV  r5, r2
        POP  r2
        POP  r1
        PUSH r2
.copy:  MOV  r3, [r2]+
        ST   r3, [r14]+
        MOV  r3, [r2]+
        ST   r3, [r14]+
        SUB  r5, #8
        BNE  .copy
        POP  r2
.fwd:   MOV  r3, r4             ; leave a forwarding pointer
        OR   r3, #7
        ST   r3, [r2]
        MOV  r1, r4
.keep:  RET
.moved: AND  r3, #-8
        AND  r1, #7
        OR   r1, r3
        RET

.if gcverify
; gc_verify: after a collection, every pointer in the new half, on the
; stack and in symbol space must point below the heap or into what the new
; half holds. A debugging aid (the gcverify feature).
gc_verify:
        MOV  r12, [cur_start]
.obj:   CMP  r12, r14
        BHS  .roots
        MOV  r1, [r12]
        MOV  r2, r1
        AND  r2, #7
        CMP  r2, #5
        BEQ  .hdr
        BSR  .check
        MOV  r1, [r12 + 4]
        BSR  .check
        ADD  r12, #8
        BRA  .obj
.hdr:   BSR  objsize
        MOV  r7, r12
        ADD  r12, r2
        CMP  r3, #0
        BNE  .obj
        MOV  r6, r1
        LSR  r6, #8
        LSL  r6, #2
        ADD  r6, r7
        ADD  r6, #4
        ADD  r7, #4
.f:     CMP  r7, r6
        BHS  .obj
        MOV  r1, [r7]+
        BSR  .check
        BRA  .f
.roots: MOV  r7, sp
.s:     CMP  r7, #STACK_TOP
        BHS  .sym
        MOV  r1, [r7]+
        BSR  .check
        BRA  .s
.sym:   MOV  r7, #SYM_BASE
.y:     CMP  r7, [sym_free]
        BHS  .ok
        MOV  r1, [r7]+
        BSR  .check
        BRA  .y
.ok:    RET
.check: MOV  r2, r1
        AND  r2, #5
        CMP  r2, #1
        BNE  .fine
        MOV  r2, r1
        AND  r2, #-8
        CMP  r2, #HEAP_A
        BLO  .fine
        CMP  r2, [cur_start]
        BLO  .bad
        CMP  r2, r14
        BHS  .bad
.fine:  RET
.bad:   LEA  r1, [msg_dangling]
        BRA  fatal
msg_dangling:   .asciz "dangling pointer after a collection"
        .align 2
.endif
