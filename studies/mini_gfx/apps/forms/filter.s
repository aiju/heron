; int key_has(const char *key, const char *q, int qlen): whether the
; record's search text holds the query (both lower case; data.c's
; key_has_c in draft 2 assembly, filter_mode 2 in the asm and blk
; builds). A scan for the query's first character, four to a loop,
; then the rest compared until the query's end; a mismatch goes back to
; the scan just past the character it found. qlen isn't needed: the
; query ends in a 0.

        .global _key_has
        .section .text._key_has
_key_has:
        MOVS r4, byte [r2]      ; r4: the query's first character
        BEQ  .yes               ; an empty query is in everything
        INC  r2                 ; r2: the rest of the query
.scan:  MOVS r0, byte [r1]+
        BEQ  .no
        CMP  r0, r4
        BEQ  .hit
        MOVS r0, byte [r1]+
        BEQ  .no
        CMP  r0, r4
        BEQ  .hit
        MOVS r0, byte [r1]+
        BEQ  .no
        CMP  r0, r4
        BEQ  .hit
        MOVS r0, byte [r1]+
        BEQ  .no
        CMP  r0, r4
        BNE  .scan
.hit:   MOV  r5, r2             ; r5: the query, r6: the key, after the first
        MOV  r6, r1
.cmp:   MOVS r0, byte [r5]+
        BEQ  .yes
        CMP  r0, byte [r6]+
        BEQ  .cmp
        BRA  .scan
.yes:   MOV  r1, #1
        RET
.no:    MOV  r1, #0
        RET
