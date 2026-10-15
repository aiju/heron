; bst: insert 100 random keys (xorshift16 seeded with 0xBEEF) into a binary
; search tree built from a static pool of nodes, then walk it in order,
; printing every 10th key and checking that the keys come out ascending, and
; print the tree's height. Equal keys go right.

        .include "lib/start.s"

NKEYS = 100

; A node is three words. The key is first so the insert walk can compare
; with [node]+ and be left pointing at the left link.
KEY   = 0
LEFT  = 4                       ; left subtree, or 0
RIGHT = 8                       ; right subtree, or 0
NODE  = 12

main:   SAVE r7-r13
        MOV  r1, #0xBEEF
        BSR  srand
        LEA  r8, [pool]         ; r8 = the next free node
.ins:   BSR  rand
        MOV  r2, r8
        BSR  insert
        ADD  r8, #NODE
        CMP  r8, #pool + NKEYS * NODE
        BNE  .ins

        ; In-order walk. inorder keeps its running state in r10-r13.
        LEA  r1, [s_keys]
        BSR  puts
        MOV  r10, #1            ; r10 = countdown to the next printed key: the first, then every 10th
        MOV  r11, #0            ; r11 = nodes visited
        MOV  r12, #0            ; r12 = the previous key (keys are never 0)
        MOV  r13, #0            ; r13 = set if a key came out smaller than the one before
        MOV  r1, [root]         ; (not empty: inorder needs a node)
        BSR  inorder
        BSR  newline
        LEA  r1, [s_visited]
        BSR  puts
        MOV  r1, r11
        BSR  print_u32
        LEA  r1, [s_order]
        BSR  puts
        LEA  r1, [s_yes]
        TST  r13, r13
        BEQ  .ok
        LEA  r1, [s_no]
.ok:    BSR  puts

        LEA  r1, [s_height]
        BSR  puts
        MOV  r1, [root]
        BSR  height
        BSR  print_u32
        BSR  newline
        RESTORE r7-r13
        RET

; insert: r1 = key, r2 = an unused node (the pool is zero, so its links are
; already 0). r3 holds the address of the link being followed -- the root
; word or a link field -- so attaching the new node is a single store.
insert: MOV  [r2], r1           ; the key
        LEA  r3, [root]
.walk:  MOVS r4, [r3]           ; the node at this link, or 0
        BEQ  .link
        CMP  r1, [r4]+          ; its key; r4 moves on to its left link
        MOV  r3, r4             ; MOV leaves C alone, so
        BLO  .walk              ; smaller keys go left...
        ADD  r3, #RIGHT - LEFT  ; ...equal and larger ones right
        BRA  .walk
.link:  MOV  [r3], r2
        RET

; inorder: r1 = a node (not 0). Visit its subtree in key order: count each
; node, check the keys ascend, print a key whenever the countdown runs out.
; Uses r10-r13 as described in main. The right subtree is a loop rather than
; a call, so a long right spine doesn't grow the stack. The node is r14, the
; current object, so its fields are one-parcel slots.
inorder:
        PUSH r7
        PUSH r14
        MOV  r14, r1
.node:  MOVS r1, [r14 + LEFT]
        BEQ  .visit
        BSR  inorder
.visit: MOV  r1, [r14]          ; the key
        CMP  r1, r12
        BHS  .asc
        MOV  r13, #1            ; out of order
.asc:   MOV  r12, r1
        INC  r11
        DEC  r10
        BNE  .right
        BSR  space
        MOV  r1, r12
        BSR  print_u32
        MOV  r10, #10
.right: MOVS r14, [r14 + RIGHT]
        BNE  .node
        POP  r14
        JMP  [sp]+

; height: r1 = a subtree, or 0 -> r1 = number of levels (0 for an empty one).
; The node is r14, as in inorder.
height: TST  r1, r1
        BEQ  .ret
        PUSH r7
        SAVE r13-r14
        MOV  r14, r1
        MOV  r1, [r14 + LEFT]
        BSR  height
        MOV  r13, r1
        MOV  r1, [r14 + RIGHT]
        BSR  height
        CMP  r1, r13
        BHS  .max
        MOV  r1, r13
.max:   INC  r1
        RESTORE r13-r14
        JMP  [sp]+
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
