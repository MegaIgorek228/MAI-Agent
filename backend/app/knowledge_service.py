import hashlib
import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.embedding_service import embed_texts, embeddings_configured
from app.models import KnowledgeChunk, KnowledgeSource


def split_text(text: str, chunk_size: int = 1200) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    return [normalized[index : index + chunk_size] for index in range(0, len(normalized), chunk_size)]


def upsert_source(db: Session, url: str, title: str, text: str) -> KnowledgeSource:
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    source = db.scalar(select(KnowledgeSource).where(KnowledgeSource.url == url))
    if source is None:
        source = KnowledgeSource(url=url, title=title, content_hash=source_hash)
        db.add(source)
        db.flush()
    elif source.content_hash == source_hash:
        return source
    else:
        source.title = title
        source.content_hash = source_hash

    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id))
    chunks = split_text(text)
    vectors = embed_texts(chunks) if embeddings_configured() else [None] * len(chunks)
    for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
        db.add(KnowledgeChunk(source_id=source.id, ordinal=ordinal, content=chunk, embedding=vector))
    db.commit()
    db.refresh(source)
    return source


def search_knowledge(db: Session, query: str, limit: int = 5) -> list[KnowledgeChunk]:
    if embeddings_configured() and db.bind is not None and db.bind.dialect.name == "postgresql":
        from app.embedding_service import embed_texts

        vector = embed_texts([query])[0]
        return list(
            db.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.embedding.is_not(None))
                .order_by(KnowledgeChunk.embedding.cosine_distance(vector))
                .limit(limit)
            )
        )
    pattern = f"%{query.strip()}%"
    return list(
        db.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.content.ilike(pattern))
            .order_by(KnowledgeChunk.source_id, KnowledgeChunk.ordinal)
            .limit(limit)
        )
    )
