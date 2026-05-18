/*
 * OTT -- custom over-the-top multiband dynamics for Zoom Multistomp.
 *
 * This is not an Ableton/Airwindows port. It is an original pedal-safe
 * approximation of the common OTT sound: split into three bands, apply
 * upward compression to quiet details and downward compression to peaks, then
 * blend with the dry signal.
 *
 * Controls:
 *   DryWet   parallel blend
 *   Time     envelope/gain smoothing speed
 *   Output   post gain
 *   SplitFrq moves the low/high split pair together
 */

#include <stdint.h>

#include "ott_params.h"

#ifndef OTT_AUDIO_FUNC
#define OTT_AUDIO_FUNC Fx_DYN_OTT
#endif

#define OTT_DO_PRAGMA(x) _Pragma(#x)
#define OTT_EXPAND_PRAGMA(x) OTT_DO_PRAGMA(x)
#define OTT_CODE_SECTION(func) OTT_EXPAND_PRAGMA(CODE_SECTION(func, ".audio"))
#define OTT_ALWAYS_INLINE(func) OTT_EXPAND_PRAGMA(FUNC_ALWAYS_INLINE(func))
OTT_CODE_SECTION(OTT_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define OTT_MAGIC 0x4F545431u
#define OTT_VERSION 1u
#define OTT_RAW_MAX 0.14f
#define OTT_RAW_TO_NORM 7.1428571f

typedef struct OTTState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t reserved;

    float lowLpL;
    float lowLpR;
    float highLpL;
    float highLpR;

    float envLowL;
    float envMidL;
    float envHighL;
    float envLowR;
    float envMidR;
    float envHighR;

    float gainLowL;
    float gainMidL;
    float gainHighL;
    float gainLowR;
    float gainMidR;
    float gainHighR;
} OTTState;

OTT_ALWAYS_INLINE(align4)
static inline uintptr_t align4(uintptr_t x)
{
    return (x + 3u) & ~(uintptr_t)3u;
}

OTT_ALWAYS_INLINE(clampf_local)
static inline float clampf_local(float x, float lo, float hi)
{
    if (x < lo) return lo;
    if (x > hi) return hi;
    return x;
}

OTT_ALWAYS_INLINE(absf_local)
static inline float absf_local(float x)
{
    return (x < 0.0f) ? -x : x;
}

OTT_ALWAYS_INLINE(param_norm)
static inline float param_norm(float raw, float fallback_norm, int group_empty)
{
    if (raw != raw) return clampf_local(fallback_norm, 0.0f, 1.0f);
    if (raw < 0.0f) return clampf_local(fallback_norm, 0.0f, 1.0f);
    if (raw <= 0.0001f) return group_empty ? clampf_local(fallback_norm, 0.0f, 1.0f) : 0.0f;
    if (raw <= (OTT_RAW_MAX * 1.1f)) return clampf_local(raw * OTT_RAW_TO_NORM, 0.0f, 1.0f);
    if (raw <= 1.0f) return clampf_local(raw, 0.0f, 1.0f);
    if (raw <= 100.0f) return clampf_local(raw * 0.01f, 0.0f, 1.0f);
    return clampf_local(fallback_norm, 0.0f, 1.0f);
}

OTT_ALWAYS_INLINE(recip_approx_pos)
static inline float recip_approx_pos(float x)
{
    union { float f; uint32_t u; } conv;
    conv.f = x;
    conv.u = 0x7EF311C3u - conv.u;
    float y = conv.f;
    y = y * (2.0f - x * y);
    y = y * (2.0f - x * y);
    return y * (2.0f - x * y);
}

OTT_ALWAYS_INLINE(ott_init_state)
static inline void ott_init_state(OTTState *st)
{
    st->magic = OTT_MAGIC;
    st->version = OTT_VERSION;
    st->initialized = 1u;
    st->reserved = 0u;

    st->lowLpL = st->lowLpR = 0.0f;
    st->highLpL = st->highLpR = 0.0f;
    st->envLowL = st->envMidL = st->envHighL = 0.02f;
    st->envLowR = st->envMidR = st->envHighR = 0.02f;
    st->gainLowL = st->gainMidL = st->gainHighL = 1.0f;
    st->gainLowR = st->gainMidR = st->gainHighR = 1.0f;
}

OTT_ALWAYS_INLINE(follow_env)
static inline float follow_env(float env, float x, float attack, float release)
{
    float a = absf_local(x);
    float c = (a > env) ? attack : release;
    return env + (a - env) * c;
}

OTT_ALWAYS_INLINE(ott_target_gain)
static inline float ott_target_gain(float env)
{
    float e = env + 0.0002f;
    float gain = 1.0f;

    if (e > 0.20f) {
        float compressed = 0.20f + (e - 0.20f) * 0.25f;
        gain = compressed * recip_approx_pos(e);
    } else if (e < 0.055f) {
        float lift = (0.055f - e) * recip_approx_pos(e + 0.018f);
        gain = 1.0f + lift * 0.85f;
    }

    return clampf_local(gain, 0.30f, 3.25f);
}

OTT_ALWAYS_INLINE(smooth_gain)
static inline float smooth_gain(float current, float target, float timeNorm)
{
    float coeff = 0.018f + (1.0f - timeNorm) * 0.20f;
    return current + (target - current) * coeff;
}

OTT_ALWAYS_INLINE(process_band)
static inline float process_band(float band, float *env, float *gain, float attack,
                                 float release, float timeNorm)
{
    *env = follow_env(*env, band, attack, release);
    *gain = smooth_gain(*gain, ott_target_gain(*env), timeNorm);
    return band * *gain;
}

OTT_ALWAYS_INLINE(process_sample)
static inline float process_sample(OTTState *st, float input, int right,
                                   float dryWet, float timeNorm,
                                   float outGain, float splitNorm)
{
    float lowCoeff = 0.006f + splitNorm * splitNorm * 0.085f;
    float highCoeff = lowCoeff * 8.0f + 0.035f;
    if (highCoeff > 0.55f) highCoeff = 0.55f;

    float *lowLp = right ? &st->lowLpR : &st->lowLpL;
    float *highLp = right ? &st->highLpR : &st->highLpL;

    *lowLp += (input - *lowLp) * lowCoeff;
    *highLp += (input - *highLp) * highCoeff;

    float low = *lowLp;
    float mid = *highLp - *lowLp;
    float high = input - *highLp;

    float attack = 0.035f + (1.0f - timeNorm) * 0.30f;
    float release = 0.0015f + (1.0f - timeNorm) * 0.035f;

    float outLow;
    float outMid;
    float outHigh;
    if (right) {
        outLow = process_band(low, &st->envLowR, &st->gainLowR, attack, release, timeNorm);
        outMid = process_band(mid, &st->envMidR, &st->gainMidR, attack, release, timeNorm);
        outHigh = process_band(high, &st->envHighR, &st->gainHighR, attack, release, timeNorm);
    } else {
        outLow = process_band(low, &st->envLowL, &st->gainLowL, attack, release, timeNorm);
        outMid = process_band(mid, &st->envMidL, &st->gainMidL, attack, release, timeNorm);
        outHigh = process_band(high, &st->envHighL, &st->gainHighL, attack, release, timeNorm);
    }

    float wet = (outLow + outMid + outHigh) * 0.78f;
    return (input * (1.0f - dryWet) + wet * dryWet) * outGain;
}

void OTT_AUDIO_FUNC(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    if (params[0] < 0.5f) return;

    volatile unsigned int *desc = ZDL_PTR(volatile unsigned int *, ctx[3]);
    if (!desc) return;

    uintptr_t base = (uintptr_t)desc[0];
    uintptr_t end = (uintptr_t)desc[1];
    unsigned int span = desc[2];
    uintptr_t stateBase = align4(base);
    uintptr_t requiredEnd = stateBase + sizeof(OTTState);
    uintptr_t bytes = end - base;

    if (base == 0u || end <= base) return;
    if ((base & 3u) != 0u || (end & 3u) != 0u || (span & 3u) != 0u) return;
    if (bytes < sizeof(OTTState) || span < bytes) return;
    if (requiredEnd > end) return;

    OTTState *st = (OTTState *)stateBase;
    if (st->magic != OTT_MAGIC || st->version != OTT_VERSION || !st->initialized) {
        ott_init_state(st);
        return;
    }

    int page1Empty = (params[OTT_DRYWET_SLOT] <= 0.0001f &&
                      params[OTT_TIME_SLOT] <= 0.0001f &&
                      params[OTT_OUTPUT_SLOT] <= 0.0001f);
    int page2Empty = (params[OTT_SPLITFRQ_SLOT] <= 0.0001f);

    float dryWet = param_norm(params[OTT_DRYWET_SLOT], OTT_DRYWET_DEFAULT_NORM, page1Empty);
    float timeNorm = param_norm(params[OTT_TIME_SLOT], OTT_TIME_DEFAULT_NORM, page1Empty);
    float outputNorm = param_norm(params[OTT_OUTPUT_SLOT], OTT_OUTPUT_DEFAULT_NORM, page1Empty);
    float splitNorm = param_norm(params[OTT_SPLITFRQ_SLOT], OTT_SPLITFRQ_DEFAULT_NORM, page2Empty);
    float outGain = outputNorm * 2.0f;

    int i;
    for (i = 0; i < 8; i++) {
        fxBuf[i] = process_sample(st, fxBuf[i], 0, dryWet, timeNorm, outGain, splitNorm);
        fxBuf[i + 8] = process_sample(st, fxBuf[i + 8], 1, dryWet, timeNorm, outGain, splitNorm);
    }
}
