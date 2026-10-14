; The nucleus's system calls (nucleus/nucleus.s), for user programs.
;
; SWI #n with arguments in r1-r5; results in r1 (and r2-r5 for messages).
; A system call is like a procedure call: r1-r7, HI and the flags may
; change, r8-r14 and sp don't.

SYS_NULL     = 0        ; nothing; r1 = 0
SYS_GETID    = 1        ; r1 = this thread's id
SYS_YIELD    = 2        ; let another thread of the same or higher priority run
SYS_EXIT     = 3        ; end this thread
SYS_PUTC     = 4        ; r1: a character for the console
SYS_WRITE    = 5        ; r1: buffer, r2: length; copies it to the console; r1 = length
SYS_CALL     = 6        ; r1: thread, r2-r5: message; waits for the reply: r1 = 0, r2-r5
SYS_RECV     = 7        ; waits for a call: r1 = the caller, r2-r5: its message
SYS_REPLYRECV = 8       ; r2-r5: the reply to the last caller; then as SYS_RECV
SYS_NOTIFY   = 9        ; r1: thread, r2: signal bits to set (wakes it if it waits)
SYS_WAIT     = 10       ; waits for signals: r1 = the bits, which are cleared
SYS_RINGSET  = 11       ; r1: the (page-aligned) address of this thread's ring
SYS_RINGENTER = 12      ; runs the requests in the ring; r1 = how many
SYS_MAPFLUSH = 13       ; softtlb: forget this context's map (it's a cache)
NSYS         = 14

; The ring (SYS_RINGSET, and between processes in shared pages): one page.
RING_SQHEAD  = 0        ; next request to run (the consumer advances it)
RING_SQTAIL  = 4        ; next free request slot (the producer advances it)
RING_CQHEAD  = 8        ; next completion to read (the producer of requests advances it)
RING_CQTAIL  = 12       ; next free completion slot
RING_SQ      = 64       ; 64 requests of 16 bytes: op, a1, a2, user data
RING_CQ      = 1088     ; 64 completions of 8 bytes: user data, result
RING_MASK    = 63

OP_NOP       = 0
OP_PUTC      = 1        ; a1: character
OP_WRITE     = 2        ; a1: buffer, a2: length

; The address space: the program at 0, shared pages at 0x400000 (if the
; process has them), demand-zero memory from 0x800000 to 0xFF0000 with
; the stack at its top, and the I/O page at 0xFFF000 (if the process has
; it: a user-level driver).
SHARED       = 0x400000
HEAP         = 0x800000
STACK_TOP    = 0xFF0000
IOPAGE       = 0xFFF000
UCONSOLE     = IOPAGE + 0xF00
UCYCLES      = IOPAGE + 0xF10
