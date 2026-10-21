"""Build (or refresh) the Chroma vector index from the markdown KB.

Pipeline for each `kb/**/*.md` file:
  1. Parse frontmatter + body with `frontmatter`.
  2. Split the body into heading-aware chunks (one chunk per `##` section,
     recursively split on `###` if a chunk exceeds TOKEN_BUDGET).
  3. Count tokens with tiktoken and embed with OpenAI embeddings.
  4. Upsert into Chroma with full metadata for filtered retrieval.

Incremental behavior: the article's `source_hash` (from frontmatter) is
written into every chunk's metadata. On re-run, if the stored hash for an
article matches the current markdown file, the article is skipped. Pass
`--force` to re-embed everything.

Usage:
  python -m src.ingest               # incremental
  python -m src.ingest --force       # re-embed everything
  python -m src.ingest --dry-run     # show what would change without calling OpenAI
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import chromadb
import frontmatter
import tiktoken
from chromadb.config import Settings
from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "kb"

load_dotenv(ROOT / ".env")

COLLECTION_NAME = "support_kb"
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
CHROMA_DIR = ROOT / os.getenv("CHROMA_DIR", ".chroma")

# Target chunk size in tokens. 500 keeps each chunk < context-expensive but
# large enough to retain a whole "Investigation" or "Procedures" section.
TOKEN_BUDGET = 500
# Minimum tokens for a standalone chunk; anything smaller is merged with the
# previous chunk to avoid retrieval noise from tiny snippets.
MIN_CHUNK_TOKENS = 60
# Hard cap so we never exceed the embedding model's 8k input limit.
HARD_MAX_TOKENS = 2000

ENCODER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(ENCODER.encode(text))


@dataclass
class ChunkRecord:
    chunk_id: str
    article_id: str
    title: str
    type: str
    category: str
    slug: str
    source_url: str
    source_hash: str
    heading_path: str
    text: str
    token_count: int

    def metadata(self) -> dict:
        return {
            "article_id": self.article_id,
            "title": self.title,
            "type": self.type,
            "category": self.category,
            "slug": self.slug,
            "source_url": self.source_url,
            "source_hash": self.source_hash,
            "heading_path": self.heading_path,
            "token_count": self.token_count,
        }


def iter_markdown_files() -> list[Path]:
    files: list[Path] = []
    for p in sorted(KB.rglob("*.md")):
        if p.name.startswith("_"):
            continue
        files.append(p)
    return files


# --- Heading-aware chunking ------------------------------------------------


HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def parse_sections(markdown: str) -> list[tuple[list[str], str]]:
    """Split markdown into (heading_path, body) sections.

    `heading_path` is a list of heading texts from the top-most h1 down to
    the current section. Only the portion ABOVE the next section of the same
    or higher level is included in `body`. Level-1 headings are rare in these
    articles (they're added by frontmatter tools), so we treat `##` as the
    primary split boundary.
    """
    lines = markdown.splitlines()
    sections: list[tuple[list[str], list[str]]] = []
    stack: list[tuple[int, str]] = []  # (level, text)
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            heading_path = [h for _, h in stack]
            if not heading_path:
                heading_path = ["(preamble)"]
            sections.append((heading_path, buffer.copy()))

    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            flush()
            buffer.clear()
            level = len(m.group(1))
            heading_text = re.sub(r"[*_`]", "", m.group(2)).strip()
            # Pop stack to the new level.
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading_text))
        else:
            buffer.append(line)
    flush()

    return [(path, "\n".join(body).strip()) for path, body in sections if "\n".join(body).strip()]


def split_oversize(heading_path: list[str], body: str) -> list[tuple[list[str], str]]:
    """If a section's body exceeds TOKEN_BUDGET, split by blank-line paragraphs."""
    if count_tokens(body) <= TOKEN_BUDGET:
        return [(heading_path, body)]

    paragraphs = re.split(r"\n{2,}", body)
    out: list[tuple[list[str], str]] = []
    current: list[str] = []
    current_tokens = 0
    for para in paragraphs:
        t = count_tokens(para)
        if current and current_tokens + t > TOKEN_BUDGET:
            out.append((heading_path, "\n\n".join(current)))
            current = [para]
            current_tokens = t
        else:
            current.append(para)
            current_tokens += t
    if current:
        out.append((heading_path, "\n\n".join(current)))
    return out


def chunk_article(post: frontmatter.Post, md_path: Path) -> list[ChunkRecord]:
    meta = post.metadata
    article_id = str(meta.get("id") or md_path.stem)
    title = str(meta.get("title") or md_path.stem)
    type_ = str(meta.get("type") or "unknown")
    category = str(meta.get("category") or "unknown")
    slug = str(meta.get("slug") or md_path.stem)
    source_url = str(meta.get("source_url") or "")
    source_hash = str(meta.get("source_hash") or "")

    raw_sections = parse_sections(post.content)
    refined: list[tuple[list[str], str]] = []
    for heading_path, body in raw_sections:
        refined.extend(split_oversize(heading_path, body))

    chunks: list[ChunkRecord] = []
    for i, (heading_path, body) in enumerate(refined):
        heading_str = " > ".join(heading_path) or "(root)"
        full_text = f"# {title}\n\n## {heading_str}\n\n{body}"
        tok = count_tokens(full_text)
        if tok > HARD_MAX_TOKENS:
            # Emergency truncation: embedding model's 8k cap is plenty, but
            # keep chunks tight for retrieval quality.
            encoded = ENCODER.encode(full_text)[:HARD_MAX_TOKENS]
            full_text = ENCODER.decode(encoded)
            tok = HARD_MAX_TOKENS
        if tok < MIN_CHUNK_TOKENS and chunks:
            # Merge into previous chunk.
            prev = chunks[-1]
            merged_text = prev.text + "\n\n" + body
            prev.text = merged_text
            prev.token_count = count_tokens(merged_text)
            continue
        chunks.append(
            ChunkRecord(
                chunk_id=f"{article_id}::{i:03d}::{slug}",
                article_id=article_id,
                title=title,
                type=type_,
                category=category,
                slug=slug,
                source_url=source_url,
                source_hash=source_hash,
                heading_path=heading_str,
                text=full_text,
                token_count=tok,
            )
        )
    return chunks


# --- Embedding + Chroma upsert --------------------------------------------


def embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    # OpenAI embeddings accept up to 2048 inputs per request; 100 is plenty.
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def upsert_chunks(collection, client: OpenAI, chunks: list[ChunkRecord], batch_size: int = 64) -> None:
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        texts = [c.text for c in batch]
        embeddings = embed_batch(client, texts)
        collection.upsert(
            ids=[c.chunk_id for c in batch],
            embeddings=embeddings,
            metadatas=[c.metadata() for c in batch],
            documents=texts,
        )


def article_needs_reindex(collection, article_id: str, source_hash: str) -> bool:
    """True if Chroma has no chunks for this article or the stored hash is stale."""
    existing = collection.get(where={"article_id": article_id}, include=["metadatas"])
    metas = existing.get("metadatas") or []
    if not metas:
        return True
    return any((m or {}).get("source_hash") != source_hash for m in metas)


def delete_article(collection, article_id: str) -> None:
    collection.delete(where={"article_id": article_id})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="Re-embed everything, ignoring cached source hashes.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change but don't call OpenAI.")
    args = parser.parse_args(argv)

    md_files = iter_markdown_files()
    if not md_files:
        print("No markdown files found in kb/. Did you run `python -m src.html_to_md` first?")
        return 1

    if not args.dry_run and not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 2

    client = OpenAI() if not args.dry_run else None
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"embed_model": EMBED_MODEL, "hnsw:space": "cosine"},
    )

    total_chunks = 0
    to_reindex: list[tuple[Path, list[ChunkRecord]]] = []
    skipped = 0

    for md_path in tqdm(md_files, desc="Scanning", unit="file"):
        try:
            post = frontmatter.load(md_path)
        except Exception as exc:
            print(f"[skip] {md_path.name}: frontmatter error: {exc}", file=sys.stderr)
            continue
        source_hash = str(post.metadata.get("source_hash") or "")
        article_id = str(post.metadata.get("id") or md_path.stem)

        if not args.force and not article_needs_reindex(collection, article_id, source_hash):
            skipped += 1
            continue

        chunks = chunk_article(post, md_path)
        total_chunks += len(chunks)
        to_reindex.append((md_path, chunks))

    print(f"Articles to (re)embed: {len(to_reindex)}")
    print(f"Articles unchanged:    {skipped}")
    print(f"Chunks:                {total_chunks}")

    if args.dry_run or not to_reindex:
        return 0

    t0 = time.perf_counter()
    for md_path, chunks in tqdm(to_reindex, desc="Embedding", unit="article"):
        article_id = chunks[0].article_id if chunks else None
        if article_id:
            delete_article(collection, article_id)
        if chunks:
            upsert_chunks(collection, client, chunks)
    elapsed = time.perf_counter() - t0

    total_in_db = collection.count()
    print(f"Done in {elapsed:.1f}s. Collection now has {total_in_db} chunks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
