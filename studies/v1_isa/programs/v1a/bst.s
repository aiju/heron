; bst: insert 100 random keys (xorshift16 seeded with 0xBEEF) into a binary
; search tree built from a static pool of nodes, then walk it in order,
; printing every 10th key and checking that the keys come out ascending, and
; print the tree's height. Equal keys go right.

        .include "lib/start.s"

NKEYS = 100

; A node is three words. The left link is first so that "the address of the
; left link" is the node address itself (see insert).
LEFT  = 0                       ; left subtree, or 0
RIGHT = 4                       ; right subtree, or 0
KEY   = 8
NODE  = 12

main:   SAVE r8-r13
        LI   r1, #0xBEEF
        BSR  srand
        LEA  r8, pool           ; r8 = the next free node
        LEA  r9, [r8 + NKEYS * NODE]
.ins:   BSR  rand
        MOV  r2, r8
        BSR  insert
        ADDI r8, NODE
        CMP  r8, r9
        BNE  .ins

        ; In-order walk. inorder keeps its running state in r10-r13.
        LEA  r1, s_keys
        BSR  puts
        MVI  r10, 1             ; r10 = countdown to the next printed key: the first, then every 10th
        MVI  r11, 0             ; r11 = nodes visited
        MVI  r12, 0             ; r12 = the previous key (keys are never 0)
        MVI  r13, 0             ; r13 = set if a key came out smaller than the one before
        LD   r1, [root]         ; (not empty: inorder needs a node)
        BSR  inorder
        BSR  newline
        LEA  r1, s_visited
        BSR  puts
        MOV  r1, r11
        BSR  print_u32
        LEA  r1, s_order
        BSR  puts
        LEA  r1, s_yes
        TST  r13, r13
        BEQ  .ok
        LEA  r1, s_no
.ok:    BSR  puts

        LEA  r1, s_height
        BSR  puts
        LD   r1, [root]
        BSR  height
        BSR  print_u32
        BSR  newline
        RESTORE r8-r13
        RET

; insert: r1 = key, r2 = an unused node (the pool is zero, so its links are
; already 0). r3 holds the address of the link being followed -- the root
; word or a link field -- so attaching the new node is a single store.
insert: ST   r1, [r2 + KEY]
        LEA  r3, root
.walk:  LD   r4, [r3]           ; the node at this link, or 0
        BEQ  .link
        LD   r5, [r4 + KEY]
        CMP  r1, r5
        MOV  r3, r4             ; = its left link; MOV leaves C alone, so
        BLO  .walk              ; smaller keys go left...
        ADDI r3, RIGHT          ; ...equal and larger ones right (ADDI: C too)
        BRA  .walk
.link:  ST   r2, [r3]
        RET

; inorder: r1 = a node (not 0). Visit its subtree in key order: count each
; node, check the keys ascend, print a key whenever the countdown runs out.
; Uses r10-r13 as described in main. The right subtree is a loop rather than
; a call, so a long right spine doesn't grow the stack.
inorder:
        PUSH r8
        MOV  r8, r1
.node:  LD   r1, [r8 + LEFT]
        BEQ  .visit
        BSR  inorder
.visit: LD   r1, [r8 + KEY]
        CMP  r1, r12
        BHS  .asc
        MVI  r13, 1             ; out of order
.asc:   MOV  r12, r1
        ADDI r11, 1
        ADDI r10, -1
        BNE  .right
        BSR  space
        MOV  r1, r12
        BSR  print_u32
        MVI  r10, 10
.right: LD   r8, [r8 + RIGHT]
        BNE  .node
        POP  r8
        RET

; height: r1 = a subtree, or 0 -> r1 = number of levels (0 for an empty one).
height: TST  r1, r1
        BEQ  .ret
        SAVE r8-r9
        MOV  r8, r1
        LD   r1, [r8 + LEFT]
        BSR  height
        MOV  r9, r1
        LD   r1, [r8 + RIGHT]
        BSR  height
        CMP  r1, r9
        BHS  .max
        MOV  r1, r9
.max:   ADDI r1, 1
        RESTORE r8-r9
.ret:   RET

s_keys:    .asciz "every 10th key in order:"
s_visited: .asciz "visited "
s_order:   .asciz " nodes, in order: "
s_yes:     .asciz "yes\n"
s_no:      .asciz "NO\n"
s_height:  .asciz "height: "
        .align 2

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/rand.s"

        .align 4
root:   .word 0
pool:   .space NKEYS * NODE
