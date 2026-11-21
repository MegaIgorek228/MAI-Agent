import hashlib
import re
from dataclasses import dataclass
from heapq import nlargest
from textwrap import wrap
from typing import Any

from sqlalchemy import case, delete, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.embedding_service import EmbeddingProviderUnavailable, embed_texts, embeddings_configured
from app.models import KnowledgeChunk, KnowledgeSource

_SEARCH_TERMS = re.compile(r"[^\W_]+")
_QUERY_STOPWORDS = frozenset(
    "а в во где для до если за и из или как какой какие на о об от по про с со у что это "
    "a about an and are for how in is of on or the to what when where which".split()
)
_MAX_SEARCH_TERMS = 12
_EMBEDDING_BATCH_SIZE = 32
_MAX_SEMANTIC_DISTANCE = 0.60
_RECIPROCAL_RANK_OFFSET = 60


@dataclass(frozen=True)
class IndexedSource:
    source: KnowledgeSource
    search_mode: str


def split_text(text: str, chunk_size: int = 1200) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines():
        normalized = " ".join(line.split())
        for part in wrap(normalized, width=chunk_size, break_on_hyphens=False):
            if size + len(part) + bool(current) > chunk_size:
                chunks.append("\n".join(current))
                current = []
                size = 0
            size += len(part) + bool(current)
            current.append(part)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _index_vectors(chunks: list[str]) -> list[list[float]]:
    dimensions = KnowledgeChunk.__table__.c.embedding.type.dim
    if get_settings().embedding_dimensions != dimensions:
        raise EmbeddingProviderUnavailable("Embedding model dimensions differ from the database schema")
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), _EMBEDDING_BATCH_SIZE):
        vectors.extend(embed_texts(chunks[start : start + _EMBEDDING_BATCH_SIZE]))
    return vectors


def _stale_chunks(db: Session, source_id: int) -> list[KnowledgeChunk]:
    return list(
        db.scalars(
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.source_id == source_id,
                or_(
                    KnowledgeChunk.embedding.is_(None),
                    KnowledgeChunk.embedding_model.is_(None),
                    KnowledgeChunk.embedding_model != get_settings().embedding_model,
                ),
            )
            .order_by(KnowledgeChunk.ordinal)
        )
    )


def _index_chunks(chunks: list[KnowledgeChunk]) -> str:
    if not embeddings_configured():
        return "lexical"
    try:
        vectors = _index_vectors([chunk.content for chunk in chunks])
    except EmbeddingProviderUnavailable:
        return "lexical"
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
        chunk.embedding_model = get_settings().embedding_model
    return "hybrid"


def upsert_source(db: Session, url: str, title: str, text: str) -> IndexedSource:
    chunks = split_text(text)
    if not chunks:
        raise ValueError("Knowledge source must contain text")
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    source = db.scalar(select(KnowledgeSource).where(KnowledgeSource.url == url).with_for_update())
    content_changed = source is None or source.content_hash != source_hash
    if source is None:
        source = KnowledgeSource(url=url, title=title, content_hash=source_hash)
        db.add(source)
        db.flush()
    else:
        source.title = title
        source.content_hash = source_hash

    if content_changed:
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id))
        stale_chunks = [
            KnowledgeChunk(source_id=source.id, ordinal=ordinal, content=content)
            for ordinal, content in enumerate(chunks)
        ]
        db.add_all(stale_chunks)
    else:
        stale_chunks = _stale_chunks(db, source.id)
    mode = _index_chunks(stale_chunks)
    db.commit()
    db.refresh(source)
    return IndexedSource(source, mode)


def reindex_source(db: Session, source_id: int) -> IndexedSource | None:
    source = db.get(KnowledgeSource, source_id, with_for_update=True)
    if source is None:
        return None
    mode = _index_chunks(_stale_chunks(db, source.id))
    db.commit()
    db.refresh(source)
    return IndexedSource(source, mode)


def _terms(query: str) -> list[str]:
    terms: dict[str, None] = {}
    for word in _SEARCH_TERMS.findall(query):
        if word in _QUERY_STOPWORDS or len(word) < 2:
            continue
        # Common Russian inflections differ in the last one or two letters.
        cyrillic = all("а" <= letter <= "я" or letter == "ё" for letter in word)
        prefix = word[:-2] if len(word) >= 6 and cyrillic else word
        terms[prefix] = None
    return list(terms)[:_MAX_SEARCH_TERMS]


def _select_hits(*extra: Any):
    return select(
        KnowledgeChunk.source_id,
        KnowledgeChunk.ordinal,
        KnowledgeChunk.content,
        KnowledgeSource.url.label("source_url"),
        KnowledgeSource.title.label("source_title"),
        KnowledgeSource.updated_at.label("source_updated_at"),
        KnowledgeSource.content_hash.label("source_content_hash"),
        *extra,
    ).join(KnowledgeSource, KnowledgeSource.id == KnowledgeChunk.source_id)


def _lexical_hits(db: Session, phrase: str, terms: list[str], limit: int) -> list[dict[str, Any]]:
    if db.get_bind().dialect.name == "postgresql":
        title = KnowledgeSource.title
        content = KnowledgeChunk.content
        scores = [
            case((title.icontains(phrase, autoescape=True) | content.icontains(phrase, autoescape=True), 3), else_=0),
            *(
                case((title.icontains(term) | content.icontains(term), 1), else_=0)
                for term in terms
            ),
        ]
        score = sum(scores[1:], scores[0])
        rows = db.execute(
            _select_hits()
            .where(score > 0)
            .order_by(score.desc(), KnowledgeChunk.source_id, KnowledgeChunk.ordinal)
            .limit(limit)
        ).mappings()
        return [dict(row) for row in rows]

    # SQLite's case folding is ASCII-only, so match Russian sources in Python for local mode.
    matches: list[tuple[int, dict[str, Any]]] = []
    for row in db.execute(_select_hits().execution_options(yield_per=100)).mappings():
        title = row["source_title"].casefold().replace("ё", "е")
        content = row["content"].casefold().replace("ё", "е")
        score = 3 * (phrase in title or phrase in content)
        score += sum(term in title or term in content for term in terms)
        if score:
            matches.append((score, dict(row)))
            if len(matches) > 2 * limit:
                matches = nlargest(limit, matches, key=_match_rank)
    return [row for _, row in nlargest(limit, matches, key=_match_rank)]


def _match_rank(match: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
    score, row = match
    return score, -row["source_id"], -row["ordinal"]


def _semantic_hits(db: Session, query: str, limit: int) -> list[dict[str, Any]]:
    if not embeddings_configured() or db.get_bind().dialect.name != "postgresql":
        return []
    current_model = KnowledgeChunk.embedding_model == get_settings().embedding_model
    available = db.scalar(
        select(KnowledgeChunk.id).where(current_model, KnowledgeChunk.embedding.is_not(None)).limit(1)
    )
    if available is None:
        return []
    try:
        (vector,) = _index_vectors([query])
    except EmbeddingProviderUnavailable:
        return []
    distance = KnowledgeChunk.embedding.cosine_distance(vector)
    rows = db.execute(
        _select_hits((1 - distance).label("similarity"))
        .where(current_model, distance <= _MAX_SEMANTIC_DISTANCE)
        .order_by(distance, KnowledgeChunk.source_id, KnowledgeChunk.ordinal)
        .limit(limit)
    ).mappings()
    return [dict(row) for row in rows]


def search_knowledge(db: Session, query: str, limit: int = 5) -> list[dict[str, Any]]:
    query = " ".join(query.split())
    if not query:
        return []
    phrase = query.casefold().replace("ё", "е") if db.get_bind().dialect.name == "sqlite" else query.casefold()
    lexical = _lexical_hits(db, phrase, _terms(phrase), limit)
    semantic = _semantic_hits(db, query, limit)
    matched: dict[tuple[int, int], dict[str, Any]] = {}
    ranks: dict[tuple[int, int], float] = {}
    for method, results in (("lexical", lexical), ("semantic", semantic)):
        for rank, item in enumerate(results, start=1):
            key = item["source_id"], item["ordinal"]
            if key in matched:
                item["match_type"] = "hybrid"
            else:
                item["match_type"] = method
            item["source_updated_at"] = item["source_updated_at"].isoformat()
            matched[key] = item
            ranks[key] = ranks.get(key, 0) + 1 / (_RECIPROCAL_RANK_OFFSET + rank)
    return [matched[key] for key in sorted(matched, key=lambda key: (-ranks[key], key))[:limit]]
