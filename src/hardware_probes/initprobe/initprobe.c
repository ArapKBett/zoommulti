/*
 * InitProbe - diagnostic ZDL for the load-time parameter materialization bug.
 *
 * Across all existing ports we see: turn knob, switch to another effect,
 * switch back; the UI shows the saved value, but the audio reads
 * params[5..N] as zero/default because the firmware does not call the
 * per-knob edit handlers on its own at load. Stock effects work because
 * their _init function explicitly invokes onf + each edit handler.
 *
 * Reverse-engineering (MS-70CDR LineSel/Exciter/BottomB/OptComp/ZNR):
 *   _init(state):
 *       push_rts
 *       1..3 __call_stub setup invocations:
 *           B31 = state[+136]  (or state[+140] for later calls)
 *           A4  = state[1]     (the params array)
 *           B4  = _<Name>_Coe  (effect-local coefficient table)
 *           A6  = Coe size in bytes (28 / 68 / 72)
 *           => registers the Coe table with the host's edit-handler runtime
 *       CALLP each edit handler with A4 = state
 *       pop_rts
 *
 * This probe is currently rolled back to the known-good stage 2 shape:
 * LineSel-style setup call only, no edit-handler calls. The audio path reads
 * Knob1 as gain so the unresolved materialization issue remains audible.
 *
 * Test plan on hardware:
 *   1. Loads cleanly? -> init wiring is OK.
 *   2. Move Knob1 and verify the audio gain changes.
 *   3. Switch to a different effect, switch back. If the UI shows the saved
 *      value but audio reads Knob1 as zero/default, setup alone is
 *      insufficient and edit-handler invocation remains the unsolved piece.
 */

#include <stdint.h>

#pragma CODE_SECTION(Fx_FLT_InitProbe, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

/* ===================================================================== *
 * Audio: Knob1 acts as a linear volume on the output accumulator. This  *
 * makes the param-materialization bug audible:                          *
 *                                                                       *
 *   params[5] reads 0 when uninitialized => audio is silent.            *
 *   params[5] reads the saved value when materialized => audio plays    *
 *                                                                       *
 * The LineSel edit handler stores raw knob values in roughly 0..0.14.   *
 * Multiply by ~7.14 (= 1/0.14) to get an approximate 0..1 gain when     *
 * the knob is normally turned. Inputs are accumulated, not assigned,    *
 * matching the GAIN port pattern.                                       *
 * ===================================================================== */
void Fx_FLT_InitProbe(unsigned int *ctx)
{
    float *fxBuf  = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    float *params = ZDL_PTR(float *, ctx[1]);
    float gain = params[5] * params[0] * (1.0f / 0.14f);

    int i;
    for (i = 0; i < 16; i++) {
        outBuf[i] += fxBuf[i] * gain;
    }
}

/* ===================================================================== *
 * Init shim - inline asm, no C frame, no callee-save register use.      *
 *                                                                       *
 * Stack frame during execution:                                         *
 *   *(SP + 8)   saved B3 (return address)                               *
 *                                                                       *
 * The linker resolves these references:                                 *
 *   _Fx_FLT_InitProbe_Coe                -> 68-byte _DUMMY_COE in .const*
 *   __c6xabi_call_stub                   -> LineSel handler-blob stub   *
 *   Fx_FLT_InitProbe_Knob{1,2,3}_edit    -> UI handlers only, not called *
 * ===================================================================== */

/* ===================================================================== *
 * ROLLED BACK to stage 2 (setup __call_stub only).                       *
 *                                                                       *
 * Stage 3 (add CALLP knob1_edit) froze the pedal on boot. The setup     *
 * __call_stub by itself was safe, so the crash sits in calling a        *
 * LineSel-cloned edit handler from init context. Most likely cause:     *
 * the cloned handler dereferences state[+31] as a callback fn ptr, and  *
 * at init time in our (custom-effect) host context that slot isn't      *
 * what stock LineSel's runtime puts there. Need a different             *
 * materialization strategy. See conversation for next-step options.     *
 * ===================================================================== */

asm("        .sect \".text\"");
asm("        .global Fx_FLT_InitProbe_init");
asm("        .ref __c6xabi_call_stub");
asm("        .ref _Fx_FLT_InitProbe_Coe");

asm("Fx_FLT_InitProbe_init:");
asm("        STW.D2T2  B3, *B15--[2]");
asm("        MVK.S1    136, A6");
asm("        ADD.L1    A4, A6, A6");
asm("        NOP       1");
asm("        LDW.D1T2  *A6[0], B31");
asm("        LDW.D1T1  *A4[1], A4");
asm("        MVKL.S2   _Fx_FLT_InitProbe_Coe, B4");
asm("        MVKH.S2   _Fx_FLT_InitProbe_Coe, B4");
asm("        MVK.S1    68, A6");
asm("        NOP       4");
asm("        CALLP.S2  __c6xabi_call_stub, B3");
asm("        LDW.D2T2  *++B15[2], B3");
asm("        NOP       4");
asm("        BNOP.S2   B3, 5");
