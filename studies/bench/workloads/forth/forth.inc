; What kernel.s and compiler.s share: the registers' jobs, the user area
; and the layout of a header. Included by both.
;
; Registers, everywhere in the Forth:
;   r8   ip, the next cell of the thread being run
;   r9   the data stack pointer: the second item is at [r9], the stack
;        grows down, and an empty stack has r9 = sp0
;   r11  the top of the data stack
;   r12  docol, which a colon definition's code field calls: CALL r12
;   r14  the user area, the system's variables, which mode E ([r14 + 4R])
;        reaches in one parcel
;   sp   the return stack: return addresses (old ips) and loop frames
;   r0-r7 scratch; r7 is the link register, which carries a code field's
;        body address into docol and the other runtimes
;   r10, r13 not used while threads run (cold start uses them)
;
; The threaded code is direct-threaded: a cell of a thread holds the
; address of machine code, and NEXT is the one instruction JMP [r8]+.
; A primitive's xt is its code; a defined word's xt is a code field of one
; parcel, a CALL to its runtime (docol, dovar, docon or dodoes), whose
; return address is the word's body.

; The user area, at r14
U_HERE   = 0                    ; the next free byte of the dictionary
U_LATEST = 4                    ; the header of the newest definition
U_STATE  = 8                    ; 0 interpreting, -1 compiling
U_IN     = 12                   ; the source text's next character
U_DOVAR  = 16                   ; the runtimes the code fields call through
U_DOCON  = 20                   ;   [r14 + n]: CREATE's words, constants
U_DODOES = 24                   ;   and the children of DOES>
U_SP0    = 28                   ; r9 when the data stack is empty
U_RP0    = 32                   ; sp while the outer interpreter runs
U_SIZE   = 36

; A header, 4-aligned:
;   +0   the link: the previous header in its thread of the dictionary
;   +4   the xt
;   +8   the name: a count byte, the characters, zeros to a multiple of 4;
;        the count byte holds the flags too, which find masks off
H_LINK   = 0
H_XT     = 4
H_NAME   = 8
IMMED    = 0x80                 ; in the count byte: run even when compiling
                                ; (its sign bit, which MOVS puts in N)
COUNT    = 0x3F                 ; the count byte's count, up to 63
