/* What the IPC's fast path (fastipc.s) needs to know of the kernel's
 * structures, as the C has it. The build compiles this file and writes
 * each constant as an .equ (build/fen/gen/koffsets.s); nothing links it. */

#include <stddef.h>
#include "kernel.h"

#define OFF(name, type, member) const int name = offsetof(type, member);
#define K(name, value) const int name = value;

OFF(T_ID, struct thread, id)
OFF(T_STATE, struct thread, state)
OFF(T_PRIO, struct thread, prio)
OFF(T_SLICE, struct thread, slice)
OFF(T_PROC, struct thread, proc)
OFF(T_PC, struct thread, pc)
OFF(T_SR, struct thread, sr)
OFF(T_NEXT, struct thread, next)
OFF(T_PREV, struct thread, prev)
OFF(T_PORT, struct thread, port)
OFF(T_PEER, struct thread, peer)
OFF(T_PEER_PID, struct thread, peer_pid)
OFF(T_RCVID, struct thread, rcvid)
K(T_SIZE, sizeof(struct thread))

OFF(P_PID, struct proc, pid)

OFF(PT_OWNER, struct port, owner)
OFF(PT_PENDING, struct port, pending)
OFF(PT_SENDERS, struct port, senders)
OFF(PT_RECEIVERS, struct port, receivers)
K(PT_SIZE, sizeof(struct port))

K(TS_RUNNING, T_RUNNING)
K(TS_REPLY, T_REPLY)
K(TS_RECV, T_RECV)
K(K_MAX_PORTS, MAX_PORTS)
K(K_SLICE_TICKS, SLICE_TICKS)
