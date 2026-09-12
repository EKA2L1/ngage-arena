/* Documentation of the in-place GSBAPP.APP repair emitted by arena/setup.py.
 * Addresses are preferred virtual addresses in the recognized LXCE payload.
 * This file does not include or link the proprietary game executable.
 */
.syntax unified
.arm

/* 0x10016d7c: keep the caller-owned message cache before saving a sent message. */
sent_message:
    push {r4, lr}
    mov r4, r0
    str r1, [r0, #0x34]
    mov r0, r1
    mov r1, r2
    mov r2, r3
    mov r3, #1
    bl 0x100151a4
    mov r0, r4
    pop {r4, lr}
    b 0x10016da8
