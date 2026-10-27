"""Knowledge-base catalog read straight from kb/**/*.md.

Two jobs:
- Serve the public help center (articles with `audience: public` only).
- Instant "as you type" suggestions using BM25 with prefix expansion. This is
  pure lexical search: no Chroma, no embeddings, no API calls per keystroke.

The mock pipeline also uses `search_sections()` over *all* articles (internal
SOPs included) as a stand-in for the hybrid retriever.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter
from rank_bm25 import BM25Okapi

from .settings import ROOT

KB_DIR = ROOT / "kb"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be but by can do for from has have how i if in is it its my "
    "of on or our so that the their them then there this to was we what when where "
    "which who why will with you your me im cant dont doesnt keep keeps get got".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


@dataclass
class Section:
    heading: str
    text: str


@dataclass
class Article:
    id: str
    slug: str
    title: str
    type: str
    category: str
    audience: str
    summary: str
    body: str
    source_url: str
    sections: list[Section] = field(default_factory=list)

    @property
    def is_public(self) -> bool:
        return self.audience == "public"


@dataclass
class SectionHit:
    article: Article
    section: Section
    score: float


def _split_sections(body: str) -> list[Section]:
    sections: list[Section] = []
    heading, lines = "Overview", []
    for line in body.splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            if any(s.strip() for s in lines):
                sections.append(Section(heading, "\n".join(lines).strip()))
            heading, lines = m.group(1).strip(), []
        else:
            lines.append(line)
    if any(s.strip() for s in lines):
        sections.append(Section(heading, "\n".join(lines).strip()))
    return sections


def _load_article(path: Path) -> Article | None:
    try:
        post = frontmatter.load(path)
    except Exception:
        return None
    meta = post.metadata
    body = post.content.strip()
    sections = _split_sections(body)
    summary = str(meta.get("summary") or "")
    if not summary and sections:
        summary = re.sub(r"\s+", " ", sections[0].text)[:160]
    return Article(
        id=str(meta.get("id") or path.stem),
        slug=str(meta.get("slug") or path.stem),
        title=str(meta.get("title") or path.stem),
        type=str(meta.get("type") or "unknown"),
        category=str(meta.get("category") or "general"),
        audience="public" if str(meta.get("audience", "")).lower() == "public" else "internal",
        summary=summary,
        body=body,
        source_url=str(meta.get("source_url") or ""),
        sections=sections,
    )


class Catalog:
    def __init__(self, kb_dir: Path = KB_DIR) -> None:
        self._kb_dir = kb_dir
        self._lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        articles = []
        if self._kb_dir.exists():
            for p in sorted(self._kb_dir.rglob("*.md")):
                if p.name.startswith("_"):
                    continue
                art = _load_article(p)
                if art:
                    articles.append(art)
        public = [a for a in articles if a.is_public]
        # Article-level index (public only) for suggestions. Title and summary are
        # repeated so they weigh more than body text.
        pub_docs = [tokenize(f"{a.title} {a.title} {a.summary} {a.summary} {a.body}") for a in public]
        # Section-level index (all articles) for the mock retriever.
        sec_refs = [(a, s) for a in articles for s in a.sections]
        sec_docs = [tokenize(f"{a.title} {s.heading} {s.text}") for a, s in sec_refs]
        with self._lock:
            self.articles = articles
            self.by_slug = {a.slug: a for a in articles}
            self.by_id = {a.id: a for a in articles}
            self.public = public
            self._pub_bm25 = BM25Okapi(pub_docs) if pub_docs else None
            self._vocab = sorted({t for d in pub_docs for t in d})
            self._sec_refs = sec_refs
            self._sec_bm25 = BM25Okapi(sec_docs) if sec_docs else None

    def _expand(self, tokens: list[str]) -> list[str]:
        """Prefix expansion so partial words match while the player is typing."""
        out: list[str] = []
        for t in tokens:
            out.append(t)
            if len(t) >= 3:
                out.extend(v for v in self._vocab if v != t and v.startswith(t))
        return out

    def suggest(self, query: str, limit: int = 5) -> list[tuple[Article, float]]:
        tokens = self._expand(tokenize(query))
        if not tokens or self._pub_bm25 is None:
            return []
        scores = self._pub_bm25.get_scores(tokens)
        ranked = sorted(zip(self.public, scores, strict=True), key=lambda p: p[1], reverse=True)
        return [(a, float(s)) for a, s in ranked if s > 0][:limit]

    def search_sections(self, query: str, limit: int = 6) -> list[SectionHit]:
        tokens = tokenize(query)
        if not tokens or self._sec_bm25 is None:
            return []
        scores = self._sec_bm25.get_scores(tokens)
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [
            SectionHit(self._sec_refs[i][0], self._sec_refs[i][1], float(scores[i]))
            for i in order[:limit]
            if scores[i] > 0
        ]

    def public_article(self, slug: str) -> Article | None:
        art = self.by_slug.get(slug)
        return art if art and art.is_public else None

    def resolve_public(self, *, article_id: str = "", title: str = "") -> Article | None:
        """Map a pipeline citation (article id or title) to a public article, if any."""
        art = self.by_id.get(article_id) if article_id else None
        if art is None and title:
            t = title.strip().lower()
            art = next((a for a in self.articles if a.title.lower() == t), None)
        return art if art and art.is_public else None


_catalog: Catalog | None = None


def get_catalog() -> Catalog:
    global _catalog
    if _catalog is None:
        _catalog = Catalog()
    return _catalog
