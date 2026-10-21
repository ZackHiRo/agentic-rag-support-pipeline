"""Convert helpdesk HTML article exports into a parallel `kb/` markdown tree.

Input layout (already on disk, left untouched):
    game/{known-issues, news & updates, procedures, references}/*.html
    general/{handbook, procedures}/*.html
    **/*_files/                  -- asset folders, ignored
    ./*.html                     -- category index pages at the repo root, ignored

Output layout:
    kb/game/{known-issues, news-and-updates, procedures, references}/<slug>.md
    kb/general/{handbook, procedures}/<slug>.md
    kb/_duplicates.json          -- audit log for deduped article IDs

The conversion is purely syntactic: HTML -> markdown via markdownify. Article
body text is preserved verbatim; only structural tags are translated. Frontmatter
(id, title, type, category, source_url, source_html, source_hash, last_updated)
is added at the top of every file.

Running this script is idempotent and incremental: each output file records a
SHA-256 hash of its source <article-body> HTML; on re-run, files whose source
hash is unchanged are left alone. Pass --force to rewrite regardless.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter
from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_markdown
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]

# Source folder -> frontmatter `type` value.
SOURCE_FOLDERS: dict[tuple[str, str], str] = {
    ("game", "known-issues"): "known-issue",
    ("game", "news & updates"): "patch-note",
    ("game", "procedures"): "procedure",
    ("game", "references"): "reference",
    ("general", "handbook"): "handbook",
    ("general", "procedures"): "procedure",
}

# Source subfolder -> normalized output subfolder (no spaces / ampersands).
FOLDER_NORMALIZE: dict[str, str] = {
    "news & updates": "news-and-updates",
}

ZD_ARTICLE_RE = re.compile(r"zendesk\.com/hc/[^/]+/articles/(\d+)")


@dataclass
class Article:
    src_path: Path
    category: str  # "game" or "general"
    source_subfolder: str  # raw source folder name, e.g. "news & updates"
    type: str  # frontmatter type: procedure/reference/known-issue/patch-note/handbook
    article_id: str
    title: str
    slug: str
    source_url: str
    body_html: str
    body_hash: str
    last_updated: str
    # Populated by the two-pass link rewriter:
    converted_markdown: str = field(default="")


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "untitled"


def output_subfolder(article: Article) -> str:
    return FOLDER_NORMALIZE.get(article.source_subfolder, article.source_subfolder)


def output_rel_path(article: Article) -> Path:
    return Path(article.category) / output_subfolder(article) / f"{article.slug}.md"


def discover_html_files() -> list[tuple[Path, str, str]]:
    """Yield (path, category, source_subfolder) for every helpdesk article export."""
    found: list[tuple[Path, str, str]] = []
    for (category, subfolder), _type in SOURCE_FOLDERS.items():
        folder = ROOT / category / subfolder
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.html")):
            # Guard against accidental recursion into *_files asset folders.
            if any(part.endswith("_files") for part in path.parts):
                continue
            found.append((path, category, subfolder))
    return found


def parse_article(path: Path, category: str, source_subfolder: str) -> Article | None:
    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    article_tag = soup.find("article", id="main-content")
    if article_tag is None:
        return None

    title_tag = article_tag.find("h1", class_="article-title")
    if title_tag is None:
        return None
    title = (title_tag.get("title") or title_tag.get_text(strip=True)).strip()

    body_tag = article_tag.find("div", class_="article-body")
    if body_tag is None:
        return None

    canonical = soup.find("link", rel="canonical")
    source_url = canonical["href"].strip() if canonical and canonical.get("href") else ""
    id_match = ZD_ARTICLE_RE.search(source_url)
    article_id = id_match.group(1) if id_match else path.stem

    last_updated = ""
    meta_tag = article_tag.find("div", class_="article-meta")
    if meta_tag is not None:
        time_tag = meta_tag.find("time")
        if time_tag and time_tag.has_attr("datetime"):
            last_updated = time_tag["datetime"]

    body_html = str(body_tag)
    body_hash = hashlib.sha256(body_html.encode("utf-8")).hexdigest()

    return Article(
        src_path=path,
        category=category,
        source_subfolder=source_subfolder,
        type=SOURCE_FOLDERS[(category, source_subfolder)],
        article_id=article_id,
        title=title,
        slug=slugify(title),
        source_url=source_url,
        body_html=body_html,
        body_hash=body_hash,
        last_updated=last_updated,
    )


def build_link_map(articles: list[Article]) -> tuple[dict[str, Article], list[Article]]:
    """Map article_id -> canonical Article. When the same id appears twice,
    prefer the copy under `general/` (cross-queue canonical) and record the
    other as a duplicate to skip."""
    link_map: dict[str, Article] = {}
    to_skip: list[Article] = []
    for a in articles:
        existing = link_map.get(a.article_id)
        if existing is None:
            link_map[a.article_id] = a
            continue
        if a.category == "general" and existing.category != "general":
            to_skip.append(existing)
            link_map[a.article_id] = a
        else:
            to_skip.append(a)
    return link_map, to_skip


def rewrite_links(soup, current: Article, link_map: dict[str, Article]) -> None:
    """Rewrite helpdesk inter-article hrefs to relative markdown paths when we
    have the target locally. External or unknown targets are left as-is."""
    cur_out = output_rel_path(current)
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        m = ZD_ARTICLE_RE.search(href)
        if not m:
            continue
        target = link_map.get(m.group(1))
        if target is None or target.src_path == current.src_path:
            continue
        anchor = href.split("#", 1)[1] if "#" in href else ""
        rel = os.path.relpath(output_rel_path(target), cur_out.parent).replace("\\", "/")
        a_tag["href"] = f"{rel}#{anchor}" if anchor else rel


def replace_images(soup) -> None:
    """Swap <img> tags for text placeholders so the ./_files asset paths don't
    leak into the markdown. Alt text or filename is preserved."""
    for img in soup.find_all("img"):
        alt = (img.get("alt") or "").strip()
        if not alt:
            src = img.get("src") or ""
            alt = Path(src).name or "image"
        img.replace_with(f"[image: {alt}]")


def convert_body(article: Article, link_map: dict[str, Article]) -> str:
    soup = BeautifulSoup(article.body_html, "html.parser")
    replace_images(soup)
    rewrite_links(soup, article, link_map)
    # Unwrap decorative containers so markdownify doesn't emit empty blocks.
    for tag in soup.find_all(["figure", "figcaption"]):
        tag.unwrap()

    md_text = html_to_markdown(
        str(soup),
        heading_style="ATX",
        bullets="-",
        strip=["script", "style"],
        escape_asterisks=False,
        escape_underscores=False,
    )
    # Normalise whitespace: collapse runs of 3+ blank lines and trim.
    md_text = re.sub(r"[ \t]+\n", "\n", md_text)
    md_text = re.sub(r"\n{3,}", "\n\n", md_text).strip() + "\n"
    return md_text


def make_frontmatter(article: Article) -> dict:
    return {
        "id": article.article_id,
        "title": article.title,
        "type": article.type,
        "category": article.category,
        "slug": article.slug,
        "source_url": article.source_url,
        "source_html": str(article.src_path.relative_to(ROOT)).replace("\\", "/"),
        "source_hash": article.body_hash,
        "last_updated": article.last_updated,
    }


def write_article(article: Article, md_body: str, kb_root: Path, force: bool) -> str:
    """Write markdown to kb/<rel>/<slug>.md. Return a status string."""
    out_path = kb_root / output_rel_path(article)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not force:
        try:
            existing = frontmatter.load(out_path)
            if existing.metadata.get("source_hash") == article.body_hash:
                return "unchanged"
        except Exception:
            pass

    post = frontmatter.Post(md_body, **make_frontmatter(article))
    out_path.write_text(frontmatter.dumps(post, sort_keys=False), encoding="utf-8")
    return "written"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="Rewrite output even if source hash is unchanged.")
    parser.add_argument("--out", default="kb", help="Output KB root (default: kb).")
    args = parser.parse_args(argv)

    kb_root = (ROOT / args.out).resolve()

    files = discover_html_files()
    if not files:
        print("No helpdesk HTML articles found under game/ or general/.")
        return 1

    articles: list[Article] = []
    skipped_no_body: list[Path] = []
    for path, category, subfolder in tqdm(files, desc="Parsing", unit="article"):
        article = parse_article(path, category, subfolder)
        if article is None:
            skipped_no_body.append(path)
            continue
        articles.append(article)

    link_map, duplicates = build_link_map(articles)
    skip_paths = {a.src_path for a in duplicates}

    # Detect non-duplicate slug collisions within the same output folder.
    seen_out: dict[Path, Article] = {}
    slug_conflicts: list[tuple[Article, Article]] = []
    for article in articles:
        if article.src_path in skip_paths:
            continue
        rel = output_rel_path(article)
        if rel in seen_out and seen_out[rel].article_id != article.article_id:
            slug_conflicts.append((seen_out[rel], article))
        else:
            seen_out[rel] = article

    written = 0
    unchanged = 0
    for article in tqdm(articles, desc="Writing ", unit="article"):
        if article.src_path in skip_paths:
            continue
        md_body = convert_body(article, link_map)
        status = write_article(article, md_body, kb_root, force=args.force)
        if status == "written":
            written += 1
        else:
            unchanged += 1

    kb_root.mkdir(parents=True, exist_ok=True)
    if duplicates:
        dup_log = [
            {
                "article_id": dup.article_id,
                "title": dup.title,
                "skipped_source": str(dup.src_path.relative_to(ROOT)).replace("\\", "/"),
                "canonical_source": str(link_map[dup.article_id].src_path.relative_to(ROOT)).replace("\\", "/"),
            }
            for dup in duplicates
        ]
        (kb_root / "_duplicates.json").write_text(json.dumps(dup_log, indent=2), encoding="utf-8")

    print()
    print(f"Parsed:              {len(articles)}")
    print(f"Written:             {written}")
    print(f"Unchanged (cached):  {unchanged}")
    print(f"Duplicates skipped:  {len(duplicates)}")
    if skipped_no_body:
        print(f"Skipped (no body):   {len(skipped_no_body)}")
        for p in skipped_no_body:
            print(f"  - {p.relative_to(ROOT)}")
    if slug_conflicts:
        print(f"Slug conflicts:      {len(slug_conflicts)}  (same output filename, different article IDs)")
        for a, b in slug_conflicts:
            print(f"  - {a.slug}.md  <=  {a.src_path.name}  AND  {b.src_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
