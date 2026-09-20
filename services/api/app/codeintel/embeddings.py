"""Local hashing embedder (Phase 5): deterministic, offline, dim-256.

Semantic retrieval with zero external services: tokens (camelCase/snake_case split
+ word trigrams) are additively hashed into a fixed-dimension signed bag, then
L2-normalized. Deterministic across runs and machines — required for incremental
indexing (an unchanged file must keep its embedding). An OpenAI-compatible
embedding endpoint can be layered later behind the same interface.
"""

from __future__ import annotations

import hashlib
import re

EMBEDDING_DIM = 256

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        for chunk in raw.split("_"):  # snake_case split
            for part in _CAMEL_RE.split(chunk):  # camelCase split
                part = part.lower()
                if len(part) >= 2:
                    out.append(part)
                    # word trigrams keep rare-but-distinctive fragments comparable
                    if len(part) > 4:
                        for i in range(len(part) - 2):
                            out.append(part[i : i + 3])
    return out


def _bucket(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little") % EMBEDDING_DIM


def embed_text(text: str) -> list[float]:
    """Deterministic L2-normalized embedding of ``text`` (dim = 256)."""
    vector = [0.0] * EMBEDDING_DIM
    tokens = _tokens(text)
    if not tokens:
        return vector
    for token in tokens:
        vector[_bucket(token)] += 1.0
    norm = sum(value * value for value in vector) ** 0.5
    if norm > 0:
        vector = [value / norm for value in vector]
    return vector


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity of two equal-length vectors (0.0 for zero vectors)."""
    if len(left) != len(right):
        raise ValueError("embedding dimensions differ")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = sum(a * a for a in left) ** 0.5
    norm_right = sum(b * b for b in right) ** 0.5
    if norm_left == 0 or norm_right == 0:
        return 0.0
    return dot / (norm_left * norm_right)
