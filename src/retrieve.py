"""Hybrid retrieval: semantic (Chroma) + lexical (BM25) fused with RRF.

Why hybrid? Semantic retrieval alone is weak on highly specific proper nouns
("Disconnect Penalty", "Crossplay", "BackOffice", "Twitch Drops") because embeddings
generalise them. BM25 nails those. The fusion of both is more robust than
either in isolation.

BM25 needs the raw chunk text, so on first query we materialise a BM25 index
from Chroma's stored documents and cache it in memory. The cache is rebuilt
when the Chroma collection's chunk count changes (cheap to detect).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv
from openai import OpenAI
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
CHROMA_DIR = ROOT / os.getenv("CHROMA_DIR", ".chroma")
COLLECTION_NAME = "support_kb"

RETRIEVE_TOP_K = int(os.getenv("RETRIEVE_TOP_K", "8"))
RETRIEVE_FINAL_K = int(os.getenv("RETRIEVE_FINAL_K", "4"))
RRF_K = 60  # Standard RRF constant from the original paper.

_TOKEN_SPLIT_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass
class Hit:
    chunk_id: str
    text: str
    metadata: dict
    score: float
    source: str  # "semantic" | "lexical" | "fused"

    @property
    def title(self) -> str:
        return str(self.metadata.get("title", ""))

    @property
    def heading(self) -> str:
        return str(self.metadata.get("heading_path", ""))


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_SPLIT_RE.findall(text)]


class Retriever:
    def __init__(self) -> None:
        self._openai = OpenAI()
        self._chroma = chromadb.PersistentClient(path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))
        self._collection = self._chroma.get_or_create_collection(COLLECTION_NAME)
        # BM25 index cache.
        self._bm25: BM25Okapi | None = None
        self._bm25_ids: list[str] = []
        self._bm25_docs: list[str] = []
        self._bm25_metas: list[dict] = []
        self._bm25_size: int = -1

    # --- BM25 cache -----------------------------------------------------
    def _refresh_bm25(self) -> None:
        count = self._collection.count()
        if self._bm25 is not None and count == self._bm25_size:
            return
        data = self._collection.get(include=["documents", "metadatas"])
        self._bm25_ids = list(data.get("ids") or [])
        self._bm25_docs = list(data.get("documents") or [])
        self._bm25_metas = list(data.get("metadatas") or [])
        tokenized = [_tokenize(d) for d in self._bm25_docs]
        self._bm25 = BM25Okapi(tokenized) if tokenized else None
        self._bm25_size = count

    # --- Core retrieval --------------------------------------------------
    def _embed(self, text: str) -> list[float]:
        resp = self._openai.embeddings.create(model=EMBED_MODEL, input=[text])
        return resp.data[0].embedding

    def _semantic(self, query: str, k: int, where: dict | None) -> list[Hit]:
        embedding = self._embed(query)
        kwargs: dict[str, Any] = {
            "query_embeddings": [embedding],
            "n_results": k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        res = self._collection.query(**kwargs)
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        hits: list[Hit] = []
        for i, _ in enumerate(ids):
            similarity = 1.0 - float(dists[i])  # cosine distance -> similarity
            hits.append(
                Hit(
                    chunk_id=ids[i],
                    text=docs[i],
                    metadata=metas[i] or {},
                    score=similarity,
                    source="semantic",
                )
            )
        return hits

    def _lexical(self, query: str, k: int, where: dict | None) -> list[Hit]:
        self._refresh_bm25()
        if self._bm25 is None:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        # Top-k by score.
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        hits: list[Hit] = []
        for idx in order:
            if scores[idx] <= 0:
                break
            meta = self._bm25_metas[idx] or {}
            if where and not _meta_matches(meta, where):
                continue
            hits.append(
                Hit(
                    chunk_id=self._bm25_ids[idx],
                    text=self._bm25_docs[idx],
                    metadata=meta,
                    score=float(scores[idx]),
                    source="lexical",
                )
            )
            if len(hits) >= k:
                break
        return hits

    def fetch_article_sections(
        self,
        article_id: str,
        heading_patterns: list[str],
    ) -> list[Hit]:
        """Return every chunk for `article_id` whose heading path contains any
        of `heading_patterns` (case-insensitive substring match).

        Used by the agent to guarantee that when an SOP matches, its
        Investigation / Procedures / Escalation / Information-to-collect
        sections are always in context, even if the initial top-k missed them.
        """
        if not article_id or not heading_patterns:
            return []
        try:
            data = self._collection.get(
                where={"article_id": article_id},
                include=["documents", "metadatas"],
            )
        except Exception:
            return []
        ids = list(data.get("ids") or [])
        docs = list(data.get("documents") or [])
        metas = list(data.get("metadatas") or [])
        patterns = [p.lower() for p in heading_patterns]
        hits: list[Hit] = []
        for i, chunk_id in enumerate(ids):
            meta = metas[i] or {}
            heading = str(meta.get("heading_path", "")).lower()
            if not any(p in heading for p in patterns):
                continue
            hits.append(
                Hit(
                    chunk_id=chunk_id,
                    text=docs[i],
                    metadata=meta,
                    score=0.0,
                    source="role_boost",
                )
            )
        return hits

    # --- Public API ------------------------------------------------------
    def search(
        self,
        query: str,
        k: int | None = None,
        top_k: int | None = None,
        where: dict | None = None,
    ) -> list[Hit]:
        """Return fused top-k hits for a single query string.

        `top_k` is how many candidates each retriever returns before fusion.
        `k` is the number of fused results returned. `where` is a Chroma
        metadata filter (also applied to BM25 results).
        """
        top_k = top_k or RETRIEVE_TOP_K
        k = k or RETRIEVE_FINAL_K
        sem = self._semantic(query, top_k, where)
        lex = self._lexical(query, top_k, where)
        return rrf_fuse(sem, lex, k=k)

    def multi_search(
        self,
        queries: list[str],
        k: int | None = None,
        top_k: int | None = None,
        where: dict | None = None,
    ) -> list[Hit]:
        """Run several queries (e.g. from the classifier) and fuse them."""
        k = k or RETRIEVE_FINAL_K
        top_k = top_k or RETRIEVE_TOP_K
        all_ranked: list[list[Hit]] = []
        for q in queries:
            all_ranked.append(self.search(q, k=top_k, top_k=top_k, where=where))
        return rrf_fuse_many(all_ranked, k=k)


# --- Fusion helpers --------------------------------------------------------


def rrf_fuse(list_a: list[Hit], list_b: list[Hit], k: int) -> list[Hit]:
    return rrf_fuse_many([list_a, list_b], k=k)


def rrf_fuse_many(ranked_lists: list[list[Hit]], k: int) -> list[Hit]:
    fused: dict[str, tuple[float, Hit]] = {}
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked):
            weight = 1.0 / (RRF_K + rank + 1)
            if hit.chunk_id in fused:
                prev_score, prev_hit = fused[hit.chunk_id]
                fused[hit.chunk_id] = (prev_score + weight, prev_hit)
            else:
                fused[hit.chunk_id] = (
                    weight,
                    Hit(
                        chunk_id=hit.chunk_id,
                        text=hit.text,
                        metadata=hit.metadata,
                        score=0.0,
                        source="fused",
                    ),
                )
    ordered = sorted(fused.values(), key=lambda pair: pair[0], reverse=True)
    out: list[Hit] = []
    for score, hit in ordered[:k]:
        hit.score = score
        out.append(hit)
    return out


def _meta_matches(meta: dict, where: dict) -> bool:
    """Minimal `where` evaluator for the BM25 path. Supports equality only
    and the `$in` operator, matching Chroma's most common usage in this app."""
    for key, expected in where.items():
        actual = meta.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
        else:
            if actual != expected:
                return False
    return True


@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    return Retriever()
