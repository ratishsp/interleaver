"""Stage 3 — align L2 sentences to L1 sentences.

Two aligners, same interface and same dynamic-programming skeleton:

  * gale_church  — length-based (Gale & Church 1993). Pure Python, no deps,
                   no network. Decent for prose, the always-available default.
  * embed_align  — cosine similarity of LaBSE sentence embeddings. Much more
                   accurate (it actually reads meaning), but needs
                   sentence-transformers + a one-time model download.

Both return a list of "beads": (l2_sentences, l1_sentences) tuples, where each
side holds 0, 1, or 2 sentences. A bead is the unit we later turn into audio.
"""
from __future__ import annotations

import math

Bead = tuple[list[str], list[str]]

# Allowed bead shapes: (#source, #target). 1-1 is the norm; the rest cover the
# splits/merges/omissions a translator introduces.
BEAD_SHAPES = [(1, 1), (1, 0), (0, 1), (2, 1), (1, 2), (2, 2)]


# --------------------------------------------------------------------------- #
# Length-based (Gale & Church)
# --------------------------------------------------------------------------- #

# Prior cost of each bead shape (negative log probability, roughly per the paper).
_GC_PRIOR = {(1, 1): 0, (1, 0): 450, (0, 1): 450, (2, 1): 230, (1, 2): 230, (2, 2): 440}
_GC_VAR = 6.8  # variance of the length ratio


def _norm_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _gc_length_cost(src_chars: int, tgt_chars: int) -> float:
    if src_chars == 0 and tgt_chars == 0:
        return 0.0
    mean = (src_chars + tgt_chars) / 2
    if mean == 0:
        return 0.0
    z = abs((src_chars - tgt_chars) / math.sqrt(_GC_VAR * mean))
    tail = 2 * (1 - _norm_cdf(z))
    return -100 * math.log(tail) if tail > 1e-12 else 2500.0


def gale_church(src: list[str], tgt: list[str]) -> list[Bead]:
    src_len = [len(s) for s in src]
    tgt_len = [len(t) for t in tgt]

    def cost(pi: int, i: int, pj: int, j: int) -> float:
        return _gc_length_cost(sum(src_len[pi:i]), sum(tgt_len[pj:j]))

    return _dp_align(src, tgt, cost, _GC_PRIOR)


# --------------------------------------------------------------------------- #
# Embedding-based (LaBSE)
# --------------------------------------------------------------------------- #

_EMB_PRIOR = {(1, 1): 0.0, (1, 0): 1.0, (0, 1): 1.0, (2, 1): 0.4, (1, 2): 0.4, (2, 2): 0.6}
_EMB_SCALE = 1.0  # weight of the (1 - cosine) similarity term


def embed_align(src: list[str], tgt: list[str], model_name: str = "sentence-transformers/LaBSE") -> list[Bead]:
    import numpy as np
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    src_emb = model.encode(src, normalize_embeddings=True, show_progress_bar=False) if src else np.zeros((0, 1))
    tgt_emb = model.encode(tgt, normalize_embeddings=True, show_progress_bar=False) if tgt else np.zeros((0, 1))

    def group(emb, a: int, b: int):
        # Mean of normalized embeddings, renormalized — a cheap "what does this
        # span of sentences mean together" vector.
        v = emb[a:b].mean(axis=0)
        n = np.linalg.norm(v)
        return v / n if n else v

    def cost(pi: int, i: int, pj: int, j: int) -> float:
        if i == pi or j == pj:  # deletion/insertion bead: no similarity to score
            return _EMB_SCALE
        sim = float(group(src_emb, pi, i) @ group(tgt_emb, pj, j))
        return _EMB_SCALE * (1.0 - sim)

    return _dp_align(src, tgt, cost, _EMB_PRIOR)


# --------------------------------------------------------------------------- #
# Shared DP
# --------------------------------------------------------------------------- #

def _dp_align(src, tgt, cost_fn, prior) -> list[Bead]:
    n, m = len(src), len(tgt)
    inf = float("inf")
    dist = [[inf] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    dist[0][0] = 0.0

    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            best, best_back = inf, None
            for di, dj in BEAD_SHAPES:
                pi, pj = i - di, j - dj
                if pi < 0 or pj < 0 or dist[pi][pj] == inf:
                    continue
                c = dist[pi][pj] + cost_fn(pi, i, pj, j) + prior[(di, dj)]
                if c < best:
                    best, best_back = c, (pi, pj)
            dist[i][j], back[i][j] = best, best_back

    beads: list[Bead] = []
    i, j = n, m
    while not (i == 0 and j == 0):
        pi, pj = back[i][j]
        beads.append((src[pi:i], tgt[pj:j]))
        i, j = pi, pj
    beads.reverse()
    return beads


def align(src: list[str], tgt: list[str], method: str = "length", **kwargs) -> list[Bead]:
    if method == "length":
        return gale_church(src, tgt)
    if method == "embed":
        return embed_align(src, tgt, **kwargs)
    raise ValueError(f"Unknown alignment method: {method!r} (use 'length' or 'embed')")
