/*
 * bpmhunt.c
 *
 * Memory-inspector probe. The Addr knob selects a 4-byte offset into the
 * firmware RAM region around 0xc009c1a0 (the base of state[31]'s per-slot
 * table). The audio function dereferences the chosen address and turns
 * the low 8 bits of the read value into a 0..2 audible gain.
 *
 * If a specific knob setting produces audio whose gain CHANGES when the
 * user taps the tempo button at different BPMs, that knob's address
 * points at BPM-related firmware memory.
 *
 * Risks:
 *   - Reading arbitrary firmware addresses from the audio context may
 *     fault if the address is outside the audio-context's read view.
 *     We restrict the scan window to known-valid firmware-RAM addresses
 *     in the 0xc009c1a0..0xc009c1dc range (used by stock effects via
 *     state[31]).
 *   - The state[31] postbox is preserved (the LineSel handler is
 *     unpatched), so user-interaction freeze risk is minimal.
 */

#include <stdint.h>

#include "bpmhunt_params.h"

#pragma CODE_SECTION(Fx_FLT_BpmHunt, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

/* Base of state[31]'s per-slot table — also the start of the firmware
 * RAM globals we want to scan. */
#define FIRMWARE_RAM_BASE  0xc009c1a0u

void Fx_FLT_BpmHunt(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf  = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    /* Preserve LineSel current-sample plumbing. */
    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    /* LineSel handler stores raw knob in roughly 0..0.14 float for a max=15
     * slot (each unit of knob travel ≈ 0.009 in raw). Map to a 0..15 idx,
     * clamping defensively in case the host adjusts the curve with the
     * pedal_flags=0x28 sync-style slot. */
    float raw = params[BPMHUNT_ADDR_SLOT];
    if (raw < 0.0f) raw = -raw;
    if (raw > 1.0f) raw = 1.0f;
    int idx = (int)(raw * (15.0f / 0.14f));
    if (idx < 0) idx = 0;
    if (idx > 15) idx = 15;

    /* Read the firmware-RAM word at base + 4*idx. The address is in
     * the same range stock effects access via state[31]. */
    volatile unsigned int *target = (volatile unsigned int *)(FIRMWARE_RAM_BASE + ((unsigned int)idx << 2));
    unsigned int value = *target;

    /* Bottom 8 bits of the read value -> 0..2 gain. */
    float gain = (float)(value & 0xFFu) * (2.0f / 255.0f);

    int i;
    for (i = 0; i < 16; i++) {
        outBuf[i] += fxBuf[i] * gain;
    }
}
