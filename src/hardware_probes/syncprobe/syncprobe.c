/*
 * syncprobe.c
 *
 * Hardware probe for the tempo-sync ABI documented in
 * docs/TEMPO-SYNC.md. The descriptor entry for the one knob has
 * pedal_flags = 0x28 (the tempo-sync bit shared by TAPEECH3 and STOMPDLY).
 * The edit handler is a single-byte patch of the LineSel-cloned knob1
 * blob that swaps the state[31] read for a state[24] read. Everything
 * else about the handler is the same proven LineSel shape:
 * push B3, MV A4,A7, the LDW (now of state[24]), then __c6xabi_call_stub,
 * the MVK 2 to B4 (still the LineSel knob_id constant), the SHL/scale,
 * and finally the state[7] tail-call that stores to params[A0+20].
 *
 * Because B4 is wrong for state[24] (TAPEECH3 uses larger constants),
 * the value that lands in params[5] is likely garbage. That is fine.
 * This build's job is to answer two narrower questions:
 *
 *   1. Does the load path tolerate a 0x28-flagged knob in a custom ZDL?
 *      We have only ever shipped 0x28 on TapeEcho4's Tempo slot before,
 *      and that pedal experiment predates the new TEMPO-SYNC findings.
 *
 *   2. Does invoking state[24] from a custom handler freeze the pedal?
 *      If turning the knob is non-fatal, state[24] is reachable from
 *      our handler context and we can iterate on the argument convention
 *      next build.
 *
 * The audio body just turns whatever ends up in params[5] into a DC
 * offset / gain on the input so any change is audible.
 */

#include <stdint.h>

#include "syncprobe_params.h"

#pragma CODE_SECTION(Fx_FLT_SyncProbe, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

void Fx_FLT_SyncProbe(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf  = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    /* Preserve the LineSel current-sample plumbing (ctx[11]/ctx[12]).
     * ParamTap demonstrates this is required to keep audio routing alive
     * even when the effect does no DSP. */
    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    /*
     * params[5] is whatever the patched handler stored after invoking
     * state[24]. We have no idea of its range, so map it through a wide
     * gain window and clip. If state[24] returned 0 the audio drops to
     * silence; if it returned anything, the input is amplified.
     */
    float raw = params[SYNCPROBE_SYNC_SLOT];
    /* Wrap negatives, clip large values; map to a 0..2 gain range. */
    if (raw < 0.0f) raw = -raw;
    if (raw > 1.0f) raw = 1.0f;
    float gain = 0.10f + raw * 1.90f;

    int i;
    for (i = 0; i < 16; i++) {
        outBuf[i] += fxBuf[i] * gain;
    }
}
