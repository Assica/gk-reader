# -*- coding: utf-8 -*-
"""Frame-accurate word alignment with a wav2vec2 CTC model running on onnxruntime.

No torch required. Given a 16 kHz mono waveform and the known sentence text,
returns one [t0, t1] per word (seconds, relative to the clip).
"""
import json
import sys
from pathlib import Path

import numpy as np

MODEL_DIR = Path(r"E:\apple app\.work\models\wav2vec2-960h")
FRAME_SEC = 0.02          # wav2vec2-base front-end stride: 320 samples @ 16 kHz
NEG = -1e30

_sess = None
_vocab = None


def _init():
    global _sess, _vocab
    if _sess is not None:
        return
    # imported here so that widen()/words_of() can be used (and self-tested)
    # on machines without onnxruntime installed
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    so.intra_op_num_threads = 4
    _sess = ort.InferenceSession(str(MODEL_DIR / "model.onnx"), so, providers=["CPUExecutionProvider"])
    _vocab = {k: int(i) for k, i in json.loads((MODEL_DIR / "vocab.json").read_text(encoding="utf-8")).items()}


def words_of(text: str):
    out = []
    for raw in text.split():
        w = "".join(ch for ch in raw.upper() if ch.isalpha() or ch == "'")
        if w:
            out.append(w)
    return out


def _labels_for(words):
    """char ids with the '|' delimiter between words; word_of marks ownership."""
    _init()
    bar = _vocab.get("|")
    labels, word_of = [], []
    for wi, w in enumerate(words):
        if wi > 0 and bar is not None:
            labels.append(bar)
            word_of.append(-1)
        for ch in w:
            tid = _vocab.get(ch)
            if tid is None:
                continue
            labels.append(tid)
            word_of.append(wi)
    return np.array(labels, dtype=np.int64), np.array(word_of, dtype=np.int64)


def _viterbi_states(log_probs, labels):
    T = log_probs.shape[0]
    L = len(labels)
    S = 2 * L + 1
    ext = np.zeros(S, dtype=np.int64)
    ext[1::2] = labels

    score = np.full(S, NEG)
    score[0] = log_probs[0, 0]
    if S > 1:
        score[1] = log_probs[0, ext[1]]
    back = np.zeros((T, S), dtype=np.int8)

    idx = np.arange(S)
    ok2 = np.zeros(S, dtype=bool)
    ok2[2:] = (ext[2:] != 0) & (ext[2:] != ext[:-2])
    src2 = np.where(ok2, idx - 2, 0)

    for t in range(1, T):
        lp = log_probs[t]
        s1 = np.full(S, NEG)
        s1[1:] = score[:-1]
        s2 = np.full(S, NEG)
        s2[ok2] = score[src2[ok2]]
        cand = np.stack([score, s1, s2])
        ch = cand.argmax(axis=0)
        score = cand[ch, idx] + lp[ext]
        back[t] = ch

    states = np.zeros(T, dtype=np.int32)
    # Forced alignment must consume the whole transcript: the backtrace may only
    # start on the last label state (S-2) or the trailing blank (S-1).  Starting
    # from argmax(score) over *all* states ends the path wherever the model is
    # most confident; every word after that point then has zero frames and shows
    # up as a null in wordTimes even though the audio is fine.
    if S > 2:
        tail = score[S - 2:]
        i = (S - 2 + int(np.argmax(tail))) if np.max(tail) > NEG / 2 else int(np.argmax(score))
    else:
        i = int(np.argmax(score))
    for t in range(T - 1, -1, -1):
        states[t] = i
        i = max(0, i - int(back[t, i]))
    return states, ext


def align(audio: np.ndarray, text: str, stretch: bool = True):
    _init()
    words = words_of(text)
    if not words:
        return None
    labels, word_of = _labels_for(words)
    if len(labels) == 0:
        return None

    x = np.asarray(audio, dtype=np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)

    feeds = {"input_values": x[None, :]}
    if any(i.name == "attention_mask" for i in _sess.get_inputs()):
        feeds["attention_mask"] = np.ones((1, x.shape[0]), dtype=np.int64)
    logits = _sess.run(None, feeds)[0][0]
    m = logits - logits.max(axis=1, keepdims=True)
    log_probs = m - np.log(np.exp(m).sum(axis=1, keepdims=True))

    states, ext = _viterbi_states(log_probs, labels)
    T = states.shape[0]

    # frames belonging to each non-blank label position
    per_label = [[] for _ in range(len(labels))]
    for t in range(T):
        st = int(states[t])
        if st == 0:
            continue
        li = (st - 1) // 2
        if 0 <= li < len(labels) and ext[st] != 0:
            per_label[li].append(t)

    out = []
    for wi in range(len(words)):
        mine = [f for li, fs in enumerate(per_label) if word_of[li] == wi for f in fs]
        if not mine:
            out.append(None)
            continue
        out.append([round(min(mine) * FRAME_SEC, 3), round((max(mine) + 1) * FRAME_SEC, 3)])
    if stretch:
        out = widen(out, len(x) / 16000.0)
    return out


def widen(spans, clip_len, pad_head=0.10, pad_tail=0.15, min_dur=0.12,
          gap=0.002, _round_eps=0.001):
    """Stretch each span into the silence around it, keeping the list ordered.

    CTC gives tight boundaries: a short word can end up a couple of frames long,
    and consecutive words leave gaps. Stretching to the midpoint with the
    neighbours makes a tapped word sound complete without dragging in the next.

    The old version pushed ``b`` forward whenever a word was shorter than
    ``min_dur``; that could push ``b_i`` past ``a_{i+1}`` and the whole page's
    wordTimes were then thrown away as non-monotonic.  This version can never
    produce overlapping spans:

    * a word shorter than ``min_dur`` borrows room from *before* it
      (``a = b - min_dur``), never from the next word;
    * an entry that CTC failed on (``None``) keeps its slot: its neighbours do
      not stretch into the gap, which is left for fix_wordtimes.py;
    * the result is strictly increasing and every kept span is at least
      ``min_dur`` long whenever the clip is long enough to hold that;
    * everything lies inside ``[0, clip_len]``.

    ``gap`` is the silence kept between adjacent words and ``_round_eps``
    compensates for rounding the result to milliseconds, so the guarantees
    still hold for the values actually written to JSON.
    """
    out = [None] * len(spans)
    idx = [i for i, s in enumerate(spans) if s]
    m = len(idx)
    if m == 0 or clip_len is None or clip_len <= 0:
        return out

    # 1) clamp the tight CTC spans and force them left-to-right
    tight = []
    prev_end = 0.0
    for i in idx:
        t0 = min(max(float(spans[i][0]), 0.0), clip_len)
        t1 = min(max(float(spans[i][1]), 0.0), clip_len)
        t0 = max(t0, prev_end)
        t1 = max(t1, t0)
        tight.append((t0, t1))
        prev_end = t1

    # 2) desired boundaries: midpoint with the neighbouring *kept* word, but if
    #    a word CTC failed on sits between them, stay on the tight edge so the
    #    missing word still has a gap to be interpolated into
    desired = []
    for k, (t0, t1) in enumerate(tight):
        pos = idx[k]
        if k == 0:
            a = max(0.0, t0 - pad_head) if pos == 0 else t0
        elif pos == idx[k - 1] + 1:
            a = (tight[k - 1][1] + t0) / 2
        else:
            a = t0
        if k + 1 == m:
            b = min(clip_len, t1 + pad_tail) if pos + 1 == len(spans) else t1
        elif pos + 1 == idx[k + 1]:
            b = (t1 + tight[k + 1][0]) / 2
        else:
            b = t1
        if b <= a:                      # degenerate (zero-frame) tight span
            a = max(0.0, min(t0, clip_len - min_dur))
            b = min(clip_len, a + min_dur)
            if b <= a:
                a, b = 0.0, clip_len
        desired.append((a, b))

    # 3) reserve room for the minimum duration and for a strict gap between
    #    words; shrink the minimum (never the ordering) when the clip is tight
    min_d = min_dur + 2 * _round_eps
    gap_d = gap + 2 * _round_eps
    if m * min_d + (m - 1) * gap_d > clip_len:
        min_d = (clip_len - (m - 1) * gap_d) / m
        if min_d <= 2 * _round_eps:
            gap_d = 0.0
            min_d = clip_len / m

    # 4) forward pass: a span may not start before the previous one ended
    vals = []
    for k, (a, b) in enumerate(desired):
        a = max(a, 0.0) if k == 0 else max(a, vals[-1] + gap_d)
        b = max(b, a + min_d)
        vals.extend((a, b))

    # 5) if the minimum made the page overflow, pull the whole chain back from
    #    the clip end (this keeps every lower bound)
    if vals[-1] > clip_len:
        vals[-1] = float(clip_len)
        for j in range(len(vals) - 2, -1, -1):
            lower = min_d if j % 2 == 0 else gap_d
            vals[j] = min(vals[j], vals[j + 1] - lower)
        if vals[0] < 0.0:
            vals = [v - vals[0] for v in vals]
            if vals[-1] > clip_len:     # pathological: compress into the clip
                scale = clip_len / vals[-1]
                vals = [v * scale for v in vals]

    for k, i in enumerate(idx):
        a, b = round(vals[2 * k], 3), round(vals[2 * k + 1], 3)
        if b <= a:                      # sub-millisecond clip: keep precision
            a, b = vals[2 * k], vals[2 * k + 1]
        out[i] = [a, b]
    return out


if __name__ == "__main__":
    import json as _j
    import wave

    sys.stdout.reconfigure(encoding="utf-8")
    lib = Path(r"E:\apple app\library")
    wavdir = Path(r"E:\apple app\.work\wav16")
    bid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    with wave.open(str(wavdir / f"{bid:02d}.wav"), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    book = _j.loads((lib / "books" / f"{bid:02d}.json").read_text(encoding="utf-8"))
    for p in book["pages"][:5]:
        a, b = p["audio"]
        res = align(x[int(a * sr): int(b * sr)], p["text"])
        print(f'\n p{p["n"]}: {p["text"]!r}  ({b-a:.2f}s)')
        for w, sp in zip(words_of(p["text"]), res or []):
            print(f"    {w:12} {'FAILED' if sp is None else f'{sp[0]:5.2f} → {sp[1]:5.2f}   ({sp[1]-sp[0]:.2f}s)'}")
