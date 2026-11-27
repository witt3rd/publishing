"""Word-level forced alignment for known narration text, without an ASR model.

Ported from papertalk's `scripts/align.mjs`: pauses in the audio are matched to
punctuation by dynamic programming (keeping speaking rate steady), and words
between pauses are spread by syllable count and snapped to loudness dips.
Zero extra dependencies — pure Python + stdlib `math`/`struct`/`re`.
"""
from __future__ import annotations

import math
import re
import struct
from typing import Sequence

_INF = 1e18
_GAMMA = (0.0, 0.3, 1.5, 2.5, 3.5, 4.5)
_MAXS = 8
_MAXJ = 45


def syllables(word: str) -> float:
    s = re.sub(r"[^a-z0-9']", "", word.lower().replace("\u2019", "'"))
    extra = 0
    if s.endswith("n't"):
        s = s[:-3]
        if s and s[-1] not in "aeiouy":
            extra = 1
    else:
        s = re.sub(r"'(s|re|ll|ve|d|m)$", "", s)
    s = s.replace("'", "")
    if not s:
        return 0.0
    if s.isdigit():
        return max(1.0, len(s) * 1.5)
    n = len(re.findall(r"[aeiouy]+", s))
    if n > 1 and re.search(r"[^aeiouy]e$", s) and not re.search(r"[^aeiouy]le$", s):
        n -= 1
    if n > 1 and re.search(r"[^aeiouytd]ed$", s):
        n -= 1
    return float(max(1, n) + extra)


def tokenize(text: str) -> list[dict]:
    """Split narration text into [{word, syl, brk}] for alignment.

    brk: 0 none, 2 comma/colon/semicolon/dash, 3 end of sentence, 4 end of line.
    """
    out: list[dict] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for li, line in enumerate(lines):
        toks = line.split()
        for ti, tok in enumerate(toks):
            clean = tok.strip(" \t\r\n\"'()[]{}")
            if not clean:
                continue
            syl = syllables(tok)
            if syl <= 0:
                continue
            brk = 0
            if ti == len(toks) - 1 and li < len(lines) - 1:
                brk = 4
            elif re.search(r"[.!?][\"')\]\u201d\u2019]*$", tok):
                brk = 3
            elif re.search(r"[,;:\u2014\u2013][\"')\]\u201d\u2019]*$", tok) or tok in ("\u2014", "\u2013", "--"):
                brk = 2
            out.append({"word": tok, "syl": syl, "brk": brk})
    if out:
        out[-1]["brk"] = 0
    return out


def _to_floats(samples) -> list[float]:
    """Accept int16 bytes, array('h'), numpy int16/float array, or sequence of floats in [-1, 1]."""
    if isinstance(samples, (bytes, bytearray, memoryview)):
        raw = bytes(samples)
        n = len(raw) // 2
        if n == 0:
            return []
        return [v / 32768.0 for v in struct.unpack(f"<{n}h", raw[: n * 2])]
    if hasattr(samples, "typecode"):
        if samples.typecode in ("h", "i", "l"):
            return [v / 32768.0 for v in samples]
        return [float(v) for v in samples]
    if hasattr(samples, "dtype"):
        import numpy as np
        arr = np.asarray(samples)
        if arr.size == 0:
            return []
        if np.issubdtype(arr.dtype, np.integer):
            return (arr.astype(np.float32) / 32768.0).tolist()
        return arr.astype(np.float32).tolist()
    return [float(v) for v in samples]


def silences(x: Sequence[float], sr: int, min_pause: float = 0.1) -> dict:
    """10 ms frame loudness (dB) and silent stretches (head, tail, internal pauses)."""
    n_samples = len(x)
    dur = n_samples / sr if sr > 0 else 0.0
    hop = max(1, round(sr / 100))
    win = hop * 2
    nf = max(1, (n_samples - win) // hop + 1) if n_samples >= win else 1
    db = [0.0] * nf
    for f in range(nf):
        i0 = f * hop
        i1 = min(n_samples, i0 + win)
        e = 0.0
        for i in range(i0, i1):
            v = x[i]
            e += v * v
        db[f] = 10.0 * math.log10(e / win + 1e-12)
    sd = sorted(db)
    hi = sd[min(nf - 1, int(nf * 0.9))]
    lo = sd[min(nf - 1, int(nf * 0.1))]
    thr = max(hi - 30.0, lo + 6.0)

    def ft(f: int) -> float:
        return (f * hop + win / 2) / sr

    runs: list[dict] = []
    f = 0
    while f < nf:
        if db[f] >= thr:
            f += 1
            continue
        g = f
        while g < nf and db[g] < thr:
            g += 1
        runs.append({
            "a": 0.0 if f == 0 else ft(f),
            "b": dur if g >= nf else ft(g - 1) + 0.01,
            "head": f == 0,
            "tail": g >= nf,
        })
        f = g

    loud = sorted(v for v in db if v >= thr)
    soft = (loud[len(loud) // 2] if loud else hi) - 15.0

    def quiet(t0: float, t1: float) -> bool:
        for k in range(math.floor(t0 * 100), min(nf, math.ceil(t1 * 100))):
            if db[max(0, k)] >= soft:
                return False
        return True

    i = 0
    while i + 1 < len(runs):
        if runs[i + 1]["a"] - runs[i]["b"] <= 0.35 and quiet(runs[i]["b"], runs[i + 1]["a"]):
            runs[i] = {"a": runs[i]["a"], "b": runs[i + 1]["b"],
                       "head": runs[i]["head"], "tail": runs[i + 1]["tail"]}
            runs.pop(i + 1)
        else:
            i += 1

    for r in runs:
        if r["tail"] or r["b"] - r["a"] < 0.15:
            continue
        k = round(r["b"] * 100)
        lim = k + 30
        while k < nf and k < lim and db[k] < soft:
            k += 1
        r["b"] = max(r["b"], k / 100.0)

    head = runs[0]["b"] if runs and runs[0]["head"] else 0.0
    last = runs[-1] if runs else None
    tail = last["a"] if last and last["tail"] and not last["head"] else dur
    cands = [{"a": r["a"], "b": r["b"], "d": r["b"] - r["a"]}
             for r in runs if not r["head"] and not r["tail"] and r["b"] - r["a"] >= min_pause]
    return {"head": head, "tail": tail, "cands": cands, "db": db, "thr": thr, "dur": dur}


def align_words(samples, sr: int, text: str, *, offset: float = 0.0, min_pause: float = 0.1) -> list[dict]:
    """Align `text` to `samples` at `sr` Hz. Returns [{word, start, end}] (seconds, shifted by `offset`)."""
    words = tokenize(text)
    if not words:
        return []
    x = _to_floats(samples)
    dur = len(x) / sr if sr > 0 else 0.0
    if not x or dur <= 0:
        return [{"word": w["word"], "start": round(offset, 3), "end": round(offset, 3)} for w in words]

    S = silences(x, sr, min_pause=min_pause)
    head, tail, cands, db, thr = S["head"], S["tail"], S["cands"], S["db"], S["thr"]
    if tail <= head + 0.02:
        # Pure silence (e.g. synthetic zero-sample test): spread proportionally by syllable weight.
        head, tail = 0.0, dur
        cands = []

    n = len(words)
    P = len(cands)
    G = n - 1
    wt = [0.3 + w["syl"] for w in words]
    Wp = [0.0]
    for v in wt:
        Wp.append(Wp[-1] + v)

    Gp = [0.0]
    for g in range(G):
        b = words[g]["brk"]
        Gp.append(Gp[-1] + _GAMMA[b if 0 <= b < len(_GAMMA) else 0])

    def unassigned(g1: int, g2: int) -> float:
        return Gp[g2 + 1] - Gp[g1] if g2 >= g1 else 0.0

    Sp = [0.0]
    Dp = [0.0]
    for c in cands:
        Sp.append(Sp[-1] + max(0.0, c["d"] - 0.07) * 10.0)
        Dp.append(Dp[-1] + max(0.0, c["d"] - 0.08))

    def skip_cost(c1: int, c2: int) -> float:
        return Sp[c2 + 1] - Sp[c1] if c2 >= c1 else 0.0

    def skip_dur(c1: int, c2: int) -> float:
        return Dp[c2 + 1] - Dp[c1] if c2 >= c1 else 0.0

    def assign(c: int, g: int) -> float:
        b = words[g]["brk"]
        d = cands[c]["d"]
        if b == 0:
            return 20.0 * max(0.0, d - 0.05)
        if b == 2:
            return -2.5 * min(d, 0.5)
        return -3.0 * min(d, 0.7)

    long_pauses = sum(c["d"] for c in cands if c["d"] > 0.25)
    R = max(0.01, (tail - head - long_pauses) / Wp[n])

    def seg_cost(w1: int, w2: int, D: float) -> float:
        W = Wp[w2 + 1] - Wp[w1]
        if W <= 0 or D <= 0.04:
            return 1e9
        r = math.log(D / (R * W))
        return 2.0 * r * r * min(W, 8.0)

    pairs: list[tuple[int, int]] = []
    if P > 0 and G > 0:
        for _ in range(2):
            dp = [_INF] * (P * G)
            frm = [-2] * (P * G)
            for c in range(P):
                ca = cands[c]["a"]
                for g in range(G):
                    bv = _INF
                    bf = -2
                    if c <= _MAXS and g < _MAXJ:
                        v = seg_cost(0, g, ca - head - skip_dur(0, c - 1)) + skip_cost(0, c - 1) + unassigned(0, g - 1) + assign(c, g)
                        if v < bv:
                            bv, bf = v, -1
                    for c2 in range(max(0, c - 1 - _MAXS), c):
                        base = skip_cost(c2 + 1, c - 1) + assign(c, g)
                        D0 = ca - cands[c2]["b"] - skip_dur(c2 + 1, c - 1)
                        row = c2 * G
                        for g2 in range(max(0, g - _MAXJ), g):
                            prev = dp[row + g2]
                            if prev >= _INF:
                                continue
                            v = prev + base + seg_cost(g2 + 1, g, D0) + unassigned(g2 + 1, g - 1)
                            if v < bv:
                                bv, bf = v, row + g2
                    dp[c * G + g] = bv
                    frm[c * G + g] = bf
            ev = _INF
            es = -1
            if P <= _MAXS:
                ev = seg_cost(0, n - 1, tail - head - skip_dur(0, P - 1)) + skip_cost(0, P - 1) + unassigned(0, G - 1)
            for c in range(max(0, P - 1 - _MAXS), P):
                row = c * G
                cb = cands[c]["b"]
                tail_d = tail - cb - skip_dur(c + 1, P - 1)
                tail_sc = skip_cost(c + 1, P - 1)
                for g in range(max(0, G - _MAXJ), G):
                    prev = dp[row + g]
                    if prev >= _INF:
                        continue
                    v = prev + seg_cost(g + 1, n - 1, tail_d) + tail_sc + unassigned(g + 1, G - 1)
                    if v < ev:
                        ev, es = v, row + g
            pairs = []
            s = es
            while s >= 0:
                pairs.append((s // G, s % G))
                s = frm[s]
            pairs.reverse()
            sd = 0.0
            sw = 0.0
            pc, pg, pt = -1, -1, head
            for qc, qg in [*pairs, (P, n - 1)]:
                end = cands[qc]["a"] if qc < P else tail
                sd += end - pt - skip_dur(pc + 1, qc - 1)
                sw += Wp[qg + 1] - Wp[pg + 1]
                pc, pg = qc, qg
                pt = cands[qc]["b"] if qc < P else tail
            if sw > 0 and sd > 0:
                R = sd / sw

    # Place words within each segment using smoothed loudness peaks (syllables) and dips (boundaries).
    nf = len(db)
    sm = [0.0] * nf
    for f in range(nf):
        e = 0.0
        k = 0
        for g in range(max(0, f - 2), min(nf, f + 3)):
            e += 10.0 ** (db[g] / 10.0)
            k += 1
        sm[f] = 10.0 * math.log10(e / k + 1e-12)
    loud_sm = sorted(v for v in sm if v > -60.0)
    med = loud_sm[len(loud_sm) // 2] if loud_sm else -20.0

    PK = [0] * (nf + 1)
    SL = [0] * (nf + 1)
    for f in range(nf):
        peak = sm[f] > med - 14.0
        if peak:
            for g in range(max(0, f - 6), min(nf, f + 7)):
                if g != f and (sm[g] > sm[f] or (sm[g] == sm[f] and g < f)):
                    peak = False
                    break
        if peak:
            lmin = min(sm[max(0, f - 25): f + 1])
            rmin = min(sm[f: min(nf, f + 26)])
            peak = sm[f] - max(lmin, rmin) >= 3.0
        PK[f + 1] = PK[f] + (1 if peak else 0)
        SL[f + 1] = SL[f] + (1 if db[f] < thr else 0)

    starts = [0.0] * n
    ends = [0.0] * n
    pg = -1
    pt = head
    for qc, qg in [*pairs, (P, n - 1)]:
        w1 = pg + 1
        w2 = qg
        t1 = cands[qc]["a"] if qc < P else tail
        f0 = min(nf - 1, max(0, round(pt * 100)))
        f1 = min(nf, max(f0 + 1, round(t1 * 100)))
        m = w2 - w1 + 1
        bnd = [f0]
        if m > 1:
            W = Wp[w2 + 1] - Wp[w1]
            rate = max(1.0, f1 - f0 - (SL[f1] - SL[f0])) / W

            def bc(f: int) -> float:
                return -3.0 if db[f] < thr else max(-1.5, min(1.0, (sm[f] - med) / 10.0))

            def wc(i: int, a: int, b: int) -> float:
                e = rate * wt[i]
                ds = max(1.0, b - a - (SL[b] - SL[a]))
                r = math.log(ds / e)
                pk = PK[b] - PK[a] - words[i]["syl"]
                return r * r + 0.35 * min(2.0, pk * pk)

            L = f1 - f0 + 1
            dp2 = [[_INF] * L for _ in range(m - 1)]
            bk = [[-1] * L for _ in range(m - 1)]
            for i in range(m - 1):
                e = rate * wt[w1 + i]
                lo = max(2, math.floor(e * 0.3))
                hi = math.ceil(e * 3.0) + 40
                for f in range(f0 + 1, f1):
                    best = _INF
                    arg = -1
                    if i == 0:
                        if lo <= f - f0 <= hi:
                            best = wc(w1, f0, f)
                    else:
                        prev_row = dp2[i - 1]
                        a_lo = max(f0 + 1, f - hi)
                        a_hi = f - lo
                        for a in range(a_lo, a_hi + 1):
                            pv = prev_row[a - f0]
                            if pv >= _INF:
                                continue
                            v = pv + wc(w1 + i, a, f)
                            if v < best:
                                best, arg = v, a
                    if best < _INF:
                        dp2[i][f - f0] = best + bc(f)
                        bk[i][f - f0] = arg
            best = _INF
            arg = -1
            last_row = dp2[m - 2]
            for f in range(f0 + 1, f1):
                pv = last_row[f - f0]
                if pv >= _INF:
                    continue
                v = pv + wc(w2, f, f1)
                if v < best:
                    best, arg = v, f
            inner: list[int] = []
            f_cur = arg
            for i in range(m - 2, -1, -1):
                if f_cur < 0:
                    break
                inner.append(f_cur)
                f_cur = bk[i][f_cur - f0]
            inner.reverse()
            if len(inner) == m - 1:
                bnd.extend(inner)
            else:
                for i in range(1, m):
                    bnd.append(round(f0 + ((Wp[w1 + i] - Wp[w1]) / W) * (f1 - f0)))
        bnd.append(f1)
        for i in range(m):
            starts[w1 + i] = bnd[i] / 100.0
            ends[w1 + i] = bnd[i + 1] / 100.0
        for i in range(1, m):
            a = bnd[i]
            b = bnd[i]
            while a > bnd[i - 1] + 1 and a - 1 < nf and db[a - 1] < thr:
                a -= 1
            while b < bnd[i + 1] - 1 and b < nf and db[b] < thr:
                b += 1
            if b - a >= 4:
                ends[w1 + i - 1] = a / 100.0
                starts[w1 + i] = b / 100.0
        pg = qg
        pt = cands[qc]["b"] if qc < P else tail

    return [
        {"word": words[i]["word"], "start": round(offset + starts[i], 3), "end": round(offset + ends[i], 3)}
        for i in range(n)
    ]
