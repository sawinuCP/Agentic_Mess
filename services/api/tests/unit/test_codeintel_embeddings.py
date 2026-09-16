"""Local hashing embedder: determinism, normalization, discrimination."""

from __future__ import annotations

from app.codeintel.embeddings import EMBEDDING_DIM, cosine, embed_text


def test_embedding_is_deterministic_and_normalized() -> None:
    first = embed_text("def process_order(order_id): process the order")
    second = embed_text("def process_order(order_id): process the order")
    assert first == second  # required by incremental indexing (stable embeddings)
    assert len(first) == EMBEDDING_DIM
    norm = sum(v * v for v in first) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_similar_texts_score_higher_than_unrelated() -> None:
    query = embed_text("lease renewal heartbeat expiry")
    related = embed_text("class LeaseService: renew lease ttl expires_at heartbeat")
    unrelated = embed_text("render monaco editor tab strip stylesheet")
    assert cosine(query, related) > cosine(query, unrelated)
    assert cosine(query, unrelated) >= 0.0


def test_snake_and_camel_case_produce_the_same_tokens() -> None:
    assert embed_text("processOrder") == embed_text("process_order")


def test_cosine_handles_zero_vectors() -> None:
    zero = [0.0] * EMBEDDING_DIM
    other = embed_text("something")
    assert cosine(zero, other) == 0.0
