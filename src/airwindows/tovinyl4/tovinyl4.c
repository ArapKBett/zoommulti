/*
 * ToVinyl4 by Chris Johnson (airwindows) - MIT licence.
 * Zoom Multistomp port candidate.
 *
 * Source reference:
 *   airwindows-ref/plugins/WinVST/ToVinyl4/ToVinyl4Proc.cpp
 *
 * The mid/side cascaded one-pole histories, groove-wear difference
 * histories, sense triggers, and antialias state are held in the
 * host-provided ctx[3] descriptor arena rather than .fardata. The
 * float32 dither tail is omitted, matching the existing Zoom Airwindows
 * ports. The desktop overallscale (sampleRate/44100) is assumed to be
 * 1.0 on the pedal, which is the same simplification the other ports
 * already make.
 */

#include <stdint.h>

#include "../common/zoom_params.h"
#include "tovinyl4_params.h"

#ifndef TOVINYL4_AUDIO_FUNC
#define TOVINYL4_AUDIO_FUNC Fx_SFX_ToVinyl4
#endif

#define TOVINYL4_DO_PRAGMA(x) _Pragma(#x)
#define TOVINYL4_EXPAND_PRAGMA(x) TOVINYL4_DO_PRAGMA(x)
#define TOVINYL4_CODE_SECTION(func) TOVINYL4_EXPAND_PRAGMA(CODE_SECTION(func, ".audio"))
TOVINYL4_CODE_SECTION(TOVINYL4_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define TOVINYL4_MAGIC 0x54564E34u
#define TOVINYL4_VERSION 1u
#define TOVINYL4_CLEAR_STEP 256u

#define TOVINYL4_CASCADE 26
#define TOVINYL4_WEAR_TAPS 10

typedef struct ToVinyl4State {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t clearIndex;

    float midSample[TOVINYL4_CASCADE];
    float sideSample[TOVINYL4_CASCADE];

    float aMid[TOVINYL4_WEAR_TAPS];
    float bMid[TOVINYL4_WEAR_TAPS];
    float aSide[TOVINYL4_WEAR_TAPS];
    float bSide[TOVINYL4_WEAR_TAPS];

    float aMidPrev;
    float bMidPrev;
    float aSidePrev;
    float bSidePrev;

    float ataLastOutL;
    float ataLastOutR;

    float s1L, s2L, s3L;
    float o1L, o2L, o3L;
    float s1R, s2R, s3R;
    float o1R, o2R, o3R;

    uint32_t fpdL;
    uint32_t fpdR;
} ToVinyl4State;

static inline uintptr_t align4(uintptr_t x)
{
    return (x + 3u) & ~(uintptr_t)3u;
}

static inline float recip_approx_pos(float x)
{
    union { float f; uint32_t u; } conv;
    conv.f = x;
    conv.u = 0x7EF311C3u - conv.u;
    float y = conv.f;
    y = y * (2.0f - x * y);
    y = y * (2.0f - x * y);
    y = y * (2.0f - x * y);
    return y;
}

static inline float tv_param_norm(float raw, float fallback_norm, int group_empty)
{
    if (raw != raw) return zoom_clamp01(fallback_norm);
    if (raw < 0.0f) return zoom_clamp01(fallback_norm);
    if (raw <= 0.0001f) return group_empty ? zoom_clamp01(fallback_norm) : 0.0f;
    if (raw <= 1.0f) return zoom_clamp01(raw);
    if (raw <= 100.0f) return zoom_clamp01(raw * 0.01f);
    return zoom_clamp01(fallback_norm);
}

static inline void tv_reset_header(ToVinyl4State *st)
{
    st->magic = TOVINYL4_MAGIC;
    st->version = TOVINYL4_VERSION;
    st->initialized = 0u;
    st->clearIndex = 16u;
}

static inline void tv_finish_init(ToVinyl4State *st)
{
    int i;
    for (i = 0; i < TOVINYL4_CASCADE; i++) {
        st->midSample[i] = 0.0f;
        st->sideSample[i] = 0.0f;
    }
    for (i = 0; i < TOVINYL4_WEAR_TAPS; i++) {
        st->aMid[i] = 0.0f;
        st->bMid[i] = 0.0f;
        st->aSide[i] = 0.0f;
        st->bSide[i] = 0.0f;
    }
    st->aMidPrev = 0.0f;
    st->bMidPrev = 0.0f;
    st->aSidePrev = 0.0f;
    st->bSidePrev = 0.0f;
    st->ataLastOutL = 0.0f;
    st->ataLastOutR = 0.0f;
    st->s1L = st->s2L = st->s3L = 0.0f;
    st->o1L = st->o2L = st->o3L = 0.0f;
    st->s1R = st->s2R = st->s3R = 0.0f;
    st->o1R = st->o2R = st->o3R = 0.0f;
    st->fpdL = 0x1234567u;
    st->fpdR = 0x89ABCDFu;
    st->initialized = 1u;
}

static inline void tv_clear_chunk(ToVinyl4State *st)
{
    uint32_t *w = (uint32_t *)(void *)st;
    uint32_t startWord = st->clearIndex >> 2;
    uint32_t endWord = startWord + (TOVINYL4_CLEAR_STEP >> 2);
    uint32_t totalWords = (uint32_t)(sizeof(ToVinyl4State) >> 2);
    uint32_t i;

    if (endWord > totalWords) endWord = totalWords;
    for (i = startWord; i < endWord; i++) {
        w[i] = 0u;
    }
    st->clearIndex = endWord << 2;
    if (endWord >= totalWords) {
        tv_finish_init(st);
    }
}

/*
 * Fill the 10-tap moving-average weights for one channel of the groove-wear
 * stage. The source does this once per audio block using if-trees against a
 * "gain" counter that walks from `span` down to 0.0; each cell either takes
 * 1.0 and decrements, or takes the leftover fractional and stops. After the
 * walk every cell is scaled by 1/max(span,1). With `span` in [1.0, 10.0]
 * the loop fills `floor(span)` cells with 1.0, one with the fractional, and
 * zeros the tail - exactly what the source generates, just without 10
 * unrolled if statements.
 */
static inline void tv_fill_wear(float *taps, float span)
{
    float gain = span;
    int i;
    for (i = 0; i < TOVINYL4_WEAR_TAPS; i++) {
        if (gain > 1.0f) {
            taps[i] = 1.0f;
            gain -= 1.0f;
        } else {
            taps[i] = gain;
            gain = 0.0f;
        }
    }
    float scale = span < 1.0f ? 1.0f : span;
    float invScale = recip_approx_pos(scale);
    for (i = 0; i < TOVINYL4_WEAR_TAPS; i++) {
        taps[i] *= invScale;
    }
}

static inline void tv_process_sample(ToVinyl4State *st,
                                     float *sampleL, float *sampleR,
                                     const float *midAmount, const float *midaltAmount,
                                     const float *sideAmount, const float *sidealtAmount,
                                     const float *fMid, const float *fSide,
                                     float intensity)
{
    float inputSampleL = *sampleL;
    float inputSampleR = *sampleR;
    if (inputSampleL > -1.18e-23f && inputSampleL < 1.18e-23f) inputSampleL = (float)st->fpdL * 1.18e-17f;
    if (inputSampleR > -1.18e-23f && inputSampleR < 1.18e-23f) inputSampleR = (float)st->fpdR * 1.18e-17f;

    /* L side trigger */
    st->s3L = st->s2L;
    st->s2L = st->s1L;
    st->s1L = inputSampleL;
    float smoothL = (st->s3L + st->s2L + st->s1L) * (1.0f / 3.0f);
    float d1L = st->s1L - st->s2L;
    float d2L = st->s2L - st->s3L;
    float scaledD1L = d1L * (1.0f / 1.3f);
    float m1L = d1L * scaledD1L;
    float m2L = d2L * scaledD1L;
    float senseL = m1L - m2L;
    if (senseL < 0.0f) senseL = -senseL;
    senseL = intensity * intensity * senseL;
    st->o3L = st->o2L;
    st->o2L = st->o1L;
    st->o1L = senseL;
    if (st->o2L > senseL) senseL = st->o2L;
    if (st->o3L > senseL) senseL = st->o3L;

    /* R side trigger */
    st->s3R = st->s2R;
    st->s2R = st->s1R;
    st->s1R = inputSampleR;
    float smoothR = (st->s3R + st->s2R + st->s1R) * (1.0f / 3.0f);
    float d1R = st->s1R - st->s2R;
    float d2R = st->s2R - st->s3R;
    float scaledD1R = d1R * (1.0f / 1.3f);
    float m1R = d1R * scaledD1R;
    float m2R = d2R * scaledD1R;
    float senseR = m1R - m2R;
    if (senseR < 0.0f) senseR = -senseR;
    senseR = intensity * intensity * senseR;
    st->o3R = st->o2R;
    st->o2R = st->o1R;
    st->o1R = senseR;
    if (st->o2R > senseR) senseR = st->o2R;
    if (st->o3R > senseR) senseR = st->o3R;

    if (senseL > 1.0f) senseL = 1.0f;
    if (senseR > 1.0f) senseR = 1.0f;

    inputSampleL = inputSampleL * (1.0f - senseL) + smoothL * senseL;
    inputSampleR = inputSampleR * (1.0f - senseR) + smoothR * senseR;

    float tempMid = inputSampleL + inputSampleR;
    float tempSide = inputSampleL - inputSampleR;
    float mid = tempMid;
    float side = tempSide;

    /* 26-stage mid cascade. Each stage is a one-pole that absorbs `tempSample`
     * with coefficient midAmount[i] (geometric series midAmount * 0.992^i),
     * and `tempSample` becomes the leftover not absorbed by this stage. */
    {
        float t = mid;
        int i;
        for (i = 0; i < TOVINYL4_CASCADE; i++) {
            float prev = st->midSample[i];
            float upd = prev * midaltAmount[i] + t * midAmount[i];
            st->midSample[i] = upd;
            t -= upd;
        }
        float midCorrectionLP = mid - t;
        mid -= midCorrectionLP;

        /* aMid difference network */
        int j;
        for (j = TOVINYL4_WEAR_TAPS - 1; j > 0; j--) {
            st->aMid[j] = st->aMid[j - 1];
        }
        float midDelta = mid - st->aMidPrev;
        st->aMid[0] = midDelta;
        float acc = 0.0f;
        for (j = 0; j < TOVINYL4_WEAR_TAPS; j++) {
            acc += st->aMid[j] * fMid[j];
        }
        float midCorrA = midDelta - acc;
        st->aMidPrev = mid;
        mid -= midCorrA;

        /* bMid difference network. Sums into the running correction but
         * notably does NOT subtract from `mid` itself (matches source). */
        for (j = TOVINYL4_WEAR_TAPS - 1; j > 0; j--) {
            st->bMid[j] = st->bMid[j - 1];
        }
        float midDeltaB = mid - st->bMidPrev;
        st->bMid[0] = midDeltaB;
        float accB = 0.0f;
        for (j = 0; j < TOVINYL4_WEAR_TAPS; j++) {
            accB += st->bMid[j] * fMid[j];
        }
        float midCorrB = midDeltaB - accB;
        st->bMidPrev = mid;

        /* Total mid correction = LP correction + A correction + B correction.
         * Final mid output is the original `tempMid` minus everything. */
        float midCorrectionTotal = midCorrectionLP + midCorrA + midCorrB;
        mid = tempMid - midCorrectionTotal;
    }

    /* 26-stage side cascade */
    {
        float t = side;
        int i;
        for (i = 0; i < TOVINYL4_CASCADE; i++) {
            float prev = st->sideSample[i];
            float upd = prev * sidealtAmount[i] + t * sideAmount[i];
            st->sideSample[i] = upd;
            t -= upd;
        }
        float sideCorrectionLP = side - t;
        side -= sideCorrectionLP;

        int j;
        for (j = TOVINYL4_WEAR_TAPS - 1; j > 0; j--) {
            st->aSide[j] = st->aSide[j - 1];
        }
        float sideDelta = side - st->aSidePrev;
        st->aSide[0] = sideDelta;
        float acc = 0.0f;
        for (j = 0; j < TOVINYL4_WEAR_TAPS; j++) {
            acc += st->aSide[j] * fSide[j];
        }
        float sideCorrA = sideDelta - acc;
        st->aSidePrev = side;
        side -= sideCorrA;

        for (j = TOVINYL4_WEAR_TAPS - 1; j > 0; j--) {
            st->bSide[j] = st->bSide[j - 1];
        }
        float sideDeltaB = side - st->bSidePrev;
        st->bSide[0] = sideDeltaB;
        float accB = 0.0f;
        for (j = 0; j < TOVINYL4_WEAR_TAPS; j++) {
            accB += st->bSide[j] * fSide[j];
        }
        float sideCorrB = sideDeltaB - accB;
        st->bSidePrev = side;

        float sideCorrectionTotal = sideCorrectionLP + sideCorrA + sideCorrB;
        side = tempSide - sideCorrectionTotal;
    }

    inputSampleL = (mid + side) * 0.5f;
    inputSampleR = (mid - side) * 0.5f;

    /* ataLastOut antialias mix uses senseL/2, senseR/2 (matches source) */
    senseL *= 0.5f;
    senseR *= 0.5f;
    float blendL = st->ataLastOutL * senseL + inputSampleL * (1.0f - senseL);
    st->ataLastOutL = inputSampleL;
    float blendR = st->ataLastOutR * senseR + inputSampleR * (1.0f - senseR);
    st->ataLastOutR = inputSampleR;

    *sampleL = blendL;
    *sampleR = blendR;
}

void TOVINYL4_AUDIO_FUNC(unsigned int *ctx)
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
    uintptr_t requiredEnd = stateBase + sizeof(ToVinyl4State);
    uintptr_t bytes = end - base;

    if (base == 0u || end <= base) return;
    if ((base & 3u) != 0u || (end & 3u) != 0u || (span & 3u) != 0u) return;
    if (bytes < sizeof(ToVinyl4State) || span < bytes) return;
    if (requiredEnd > end) return;

    ToVinyl4State *st = (ToVinyl4State *)stateBase;
    if (st->magic != TOVINYL4_MAGIC || st->version != TOVINYL4_VERSION) {
        tv_reset_header(st);
        return;
    }
    if (!st->initialized) {
        tv_clear_chunk(st);
        return;
    }

    /* Param read with group-empty fallback (raw=0 means user knob at 0 unless
     * every slot is zero, which signals an uninitialized param block). */
    float rawA = params[TOVINYL4_BRIGHT_SLOT];
    float rawB = params[TOVINYL4_SIDERLL_SLOT];
    float rawC = params[TOVINYL4_DEHISS_SLOT];
    float rawD = params[TOVINYL4_WEAR_SLOT];
    int groupEmpty = (rawA <= 0.0001f) && (rawB <= 0.0001f)
                  && (rawC <= 0.0001f) && (rawD <= 0.0001f);

    float A = tv_param_norm(rawA, TOVINYL4_BRIGHT_DEFAULT_NORM, groupEmpty);
    float B = tv_param_norm(rawB, TOVINYL4_SIDERLL_DEFAULT_NORM, groupEmpty);
    float C = tv_param_norm(rawC, TOVINYL4_DEHISS_DEFAULT_NORM, groupEmpty);
    float D = tv_param_norm(rawD, TOVINYL4_WEAR_DEFAULT_NORM, groupEmpty);

    /* overallscale = sampleRate/44100 in the source; the pedal runs at 44.1k
     * so overallscale = 1.0 and divides drop out. */
    const float invFuss = 1.0f / 50000.0f;
    float resonance = 0.992f;

    float midCutoff = (A * A) * 290.0f + 10.0f;
    float midBase = midCutoff * invFuss;
    float sideCutoff = (B * B) * 290.0f + 10.0f;
    float sideBase = sideCutoff * invFuss;

    float midAmount[TOVINYL4_CASCADE];
    float midaltAmount[TOVINYL4_CASCADE];
    float sideAmount[TOVINYL4_CASCADE];
    float sidealtAmount[TOVINYL4_CASCADE];

    float coefMid = midBase * resonance;
    float coefSide = sideBase * resonance;
    int i;
    for (i = 0; i < TOVINYL4_CASCADE; i++) {
        midAmount[i] = coefMid;
        midaltAmount[i] = 1.0f - coefMid;
        coefMid *= resonance;
        sideAmount[i] = coefSide;
        sidealtAmount[i] = 1.0f - coefSide;
        coefSide *= resonance;
    }

    float intensity = C * C * C * 32.0f;

    float fMid[TOVINYL4_WEAR_TAPS];
    float fSide[TOVINYL4_WEAR_TAPS];
    tv_fill_wear(fMid, D * 9.0f + 1.0f);
    tv_fill_wear(fSide, D * 4.5f + 1.0f);

    for (i = 0; i < 8; i++) {
        float sL = fxBuf[i];
        float sR = fxBuf[i + 8];
        tv_process_sample(st, &sL, &sR,
                          midAmount, midaltAmount,
                          sideAmount, sidealtAmount,
                          fMid, fSide,
                          intensity);
        fxBuf[i] = sL;
        fxBuf[i + 8] = sR;
    }
}
