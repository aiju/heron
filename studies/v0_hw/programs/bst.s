; bst: insert 100 random keys into a binary search tree built from a static
; node pool, then walk it in order printing every 10th key, and print the
; tree height.

        .include "lib/start.s"

NKEYS = 100
NODE  = 6                       ; key, left, right (0 = no child)

main:   PUSH r8
        LI   r1, #0xBEEF
        CALL srand
        MVI  r8, NKEYS
.ins:   CALL rand
        BSR  insert
        DEC  r8
        BNE  .ins

        LI   r1, #s_keys        ; in-order walk
        CALL puts
        MVI  r1, 1              ; print the first key, then every 10th
        ST   r1, [countdown]
        LD   r1, [root]
        BSR  inorder
        CALL newline
        LI   r1, #s_visited
        CALL puts
        LD   r1, [visited]
        CALL print_u16
        LI   r1, #s_order
        CALL puts
        LI   r1, #s_yes
        LD   r2, [unsorted]
        BEQ  .ok
        LI   r1, #s_no
.ok:    CALL puts

        LI   r1, #s_height
        CALL puts
        LD   r1, [root]
        BSR  height
        CALL print_u16
        CALL newline
        POP  r8
        RET

; insert: r1 = key. Take the next node from the pool and link it in. r3
; holds the address of the link being followed (the root word, or a child
; field), so attaching the new node is a single store.
insert: LD   r2, [pool_next]
        ST   r1, [r2]
        ST   r0, [r2 + 2]
        ST   r0, [r2 + 4]
        LEA  r3, [r2 + NODE]
        ST   r3, [pool_next]
        LI   r3, #root
.walk:  LD   r4, [r3]           ; the node at this link, or 0
        BEQ  .link
        LD   r5, [r4]
        CMP  r1, r5
        LEA  r3, [r4 + 2]       ; LEA keeps the flags from the CMP:
        BLO  .walk              ; smaller keys go left...
        ADDI r3, 2              ; ...the rest right
        BRA  .walk
.link:  ST   r2, [r3]
        RET

; inorder: r1 = subtree. Visit every node in key order, printing a key
; whenever the countdown runs out, and check the keys come out ascending.
inorder:
        TST  r1, r1
        BEQ  .ret
        PUSH r8
        MOV  r8, r1
        LD   r1, [r8 + 2]       ; left subtree
        BSR  inorder
        LD   r1, [r8]           ; this key
        LD   r2, [lastkey]
        CMP  r1, r2
        BHS  .inorder
        ST   r1, [unsorted]     ; any non-zero value will do (keys are never 0)
.inorder:
        ST   r1, [lastkey]
        LD   r2, [visited]
        INC  r2
        ST   r2, [visited]
        LD   r2, [countdown]
        DEC  r2
        BNE  .quiet
        CALL space
        LD   r1, [r8]
        CALL print_u16
        MVI  r2, 10
.quiet: ST   r2, [countdown]
        LD   r1, [r8 + 4]       ; right subtree: a tail call, so a long
        POP  r8                 ; right spine doesn't grow the stack
        BRA  inorder
.ret:   RET

; height: r1 = subtree -> r1 = number of levels (0 for an empty tree).
height: TST  r1, r1
        BEQ  .ret
        PUSH r8
        PUSH r9
        MOV  r8, r1
        LD   r1, [r8 + 2]
        BSR  height
        MOV  r9, r1
        LD   r1, [r8 + 4]
        BSR  height
        CMP  r1, r9
        BHS  .max
        MOV  r1, r9
.max:   INC  r1
        POP  r9
        POP  r8
.ret:   RET

root:      .word 0
pool_next: .word pool
countdown: .word 0
visited:   .word 0
lastkey:   .word 0
unsorted:  .word 0
s_keys:    .asciz "every 10th key in order:"
s_visited: .asciz "visited "
s_order:   .asciz " nodes, in order: "
s_yes:     .asciz "yes\n"
s_no:      .asciz "NO\n"
s_height:  .asciz "height: "

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/rand.s"

        .align 2
pool:   .space NKEYS * NODE
