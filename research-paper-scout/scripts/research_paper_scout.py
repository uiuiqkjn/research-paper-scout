#!/usr/bin/env python3
"""Search OpenAlex, arXiv, and Semantic Scholar for ranked paper lists."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


S2_FIELDS = ",".join(
    [
        "title",
        "abstract",
        "year",
        "venue",
        "publicationVenue",
        "citationCount",
        "referenceCount",
        "influentialCitationCount",
        "authors",
        "externalIds",
        "url",
        "publicationTypes",
        "references.title",
        "references.year",
        "references.externalIds",
    ]
)

SURVEY_TERMS = (
    "survey",
    "review",
    "systematic review",
    "meta-analysis",
    "meta analysis",
    "overview",
    "taxonomy",
    "tutorial",
    "perspective",
)

QUALITY_VENUES = {
    "nature",
    "science",
    "cell",
    "pnas",
    "nejm",
    "lancet",
    "jama",
    "neurips",
    "icml",
    "iclr",
    "acl",
    "emnlp",
    "naacl",
    "cvpr",
    "iccv",
    "eccv",
    "sigir",
    "kdd",
    "www",
    "chi",
    "uist",
    "sigmod",
    "vldb",
    "icse",
    "fse",
    "pldi",
    "osdi",
    "sosp",
    "siggraph",
    "tvcg",
    "ieee vr",
    "ismar",
    "hpg",
    "i3d",
    "egsr",
}

DOMAIN_GENERIC_TERMS = {
    "adaptive",
    "confidence",
    "consistent",
    "disocclusion",
    "efficient",
    "feature",
    "fourier",
    "guided",
    "image",
    "invalid",
    "local",
    "low",
    "mask",
    "neural",
    "partial",
    "reconstruct",
    "reconstruction",
    "render",
    "rendering",
    "resolution",
    "reuse",
    "sample",
    "sampling",
    "screen",
    "space",
    "super",
    "temporal",
    "tile",
    "tiles",
    "view",
}


@dataclass
class Paper:
    title: str
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    venue: str | None = None
    abstract: str | None = None
    authors: list[str] = field(default_factory=list)
    citations: int = 0
    references_count: int = 0
    influential_citations: int = 0
    url: str | None = None
    sources: set[str] = field(default_factory=set)
    references: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0
    relevance: float = 0.0
    content_similarity: float = 0.0
    concept_coverage: float = 0.0
    domain_focus: float = 0.0
    method_focus: float = 0.0
    is_survey: bool = False


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "using",
    "via",
    "with",
    "within",
}


def http_json(url: str, headers: dict[str, str] | None = None, data: bytes | None = None) -> Any:
    request = urllib.request.Request(url, headers=headers or {}, data=data)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def http_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def norm_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = value.lower().strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value)
    value = value.replace("doi:", "").strip()
    return value or None


def norm_title(value: str | None) -> str:
    value = (value or "").lower()
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def split_csvish(value: str | None) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in re.split(r"[,;|]", value) if x.strip()]


def content_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", value.lower())
    normalized = []
    for token in tokens:
        if len(token) <= 2 or token in STOPWORDS:
            continue
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("ing") and len(token) > 5:
            token = token[:-3]
        elif token.endswith("ed") and len(token) > 4:
            token = token[:-2]
        elif token.endswith("s") and len(token) > 4:
            token = token[:-1]
        normalized.append(token)
    return normalized


def token_counts(tokens: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return counts


def cosine_similarity(left: str, right: str) -> float:
    left_counts = token_counts(content_tokens(left))
    right_counts = token_counts(content_tokens(right))
    if not left_counts or not right_counts:
        return 0.0
    dot = sum(count * right_counts.get(token, 0) for token, count in left_counts.items())
    left_norm = math.sqrt(sum(count * count for count in left_counts.values()))
    right_norm = math.sqrt(sum(count * count for count in right_counts.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def concept_coverage(topic: str, keywords: list[str], text: str) -> float:
    concepts = [topic] + keywords
    text_tokens = set(content_tokens(text))
    scores = []
    for concept in concepts:
        concept_tokens = set(content_tokens(concept))
        if not concept_tokens:
            continue
        scores.append(len(concept_tokens & text_tokens) / len(concept_tokens))
    return sum(scores) / len(scores) if scores else 0.0


def build_query(topic: str, keywords: list[str]) -> str:
    parts = [topic] + keywords
    return " ".join(p for p in parts if p)


def make_search_queries(topic: str, keywords: list[str], venues: list[str] | None = None) -> list[str]:
    """Build several focused queries instead of one brittle keyword blob."""
    queries: list[str] = []
    cleaned_keywords = [k for k in keywords if k]
    if topic:
        queries.append(topic)
        topic_tokens = content_tokens(topic)
        if len(topic_tokens) > 3:
            queries.append(" ".join(topic_tokens[:8]))
    for keyword in cleaned_keywords:
        if len(keyword) >= 4:
            queries.append(keyword)
    # Pair distinctive topic terms with important method terms so broad words
    # such as "adaptive sampling" cannot dominate recall by themselves.
    anchor = " ".join(domain_anchor_tokens(topic, keywords)[:4])
    if anchor:
        for keyword in cleaned_keywords[:12]:
            if keyword.lower() not in anchor.lower():
                queries.append(f"{anchor} {keyword}")
    for venue in venues or []:
        if topic and venue:
            queries.append(f"{topic} {venue}")
    seen: set[str] = set()
    result: list[str] = []
    for query in queries:
        query = clean_text(query)
        key = query.lower()
        if query and key not in seen:
            seen.add(key)
            result.append(query)
    return result[:24]


def domain_anchor_tokens(topic: str, keywords: list[str]) -> list[str]:
    tokens = content_tokens(topic)
    # Preserve distinctive acronyms and compact terms from keywords.
    for keyword in keywords:
        for raw in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]*", keyword):
            compact = raw.lower().replace("-", "")
            if len(compact) >= 3:
                tokens.append(compact)
    anchors: list[str] = []
    for token in tokens:
        if token in DOMAIN_GENERIC_TERMS:
            continue
        if token not in anchors:
            anchors.append(token)
    return anchors or list(dict.fromkeys(content_tokens(topic)))[:6]


def search_openalex_query(query: str, year_from: int, year_to: int, per_page: int) -> list[Paper]:
    params = {
        "search": query,
        "filter": f"from_publication_date:{year_from}-01-01,to_publication_date:{year_to}-12-31",
        "per-page": str(min(max(per_page, 1), 200)),
        "sort": "cited_by_count:desc",
    }
    email = os.environ.get("OPENALEX_MAILTO")
    if email:
        params["mailto"] = email
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = http_json(url)
    papers: list[Paper] = []
    for item in data.get("results", []):
        title = clean_text(item.get("display_name"))
        if not title:
            continue
        doi = norm_doi(item.get("doi"))
        authors = [
            clean_text(a.get("author", {}).get("display_name"))
            for a in item.get("authorships", [])
            if a.get("author", {}).get("display_name")
        ]
        source = ((item.get("primary_location") or {}).get("source") or {})
        venue = clean_text(source.get("display_name"))
        abstract = inverted_index_to_text(item.get("abstract_inverted_index"))
        paper = Paper(
            title=title,
            year=item.get("publication_year"),
            doi=doi,
            venue=venue or None,
            abstract=abstract,
            authors=authors,
            citations=int(item.get("cited_by_count") or 0),
            url=item.get("id"),
            sources={"OpenAlex"},
        )
        papers.append(paper)
    return papers


def search_openalex(topic: str, keywords: list[str], venues: list[str], year_from: int, year_to: int, per_page: int) -> list[Paper]:
    papers: list[Paper] = []
    per_query = max(10, min(50, per_page // 3))
    for query in make_search_queries(topic, keywords, venues)[:12]:
        papers.extend(search_openalex_query(query, year_from, year_to, per_query))
        time.sleep(0.1)
    return dedupe(papers)


def inverted_index_to_text(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        words.extend((pos, word) for pos in positions)
    return " ".join(word for _, word in sorted(words)) or None


def search_arxiv(topic: str, keywords: list[str], year_from: int, year_to: int, max_results: int) -> list[Paper]:
    terms = [topic] + keywords
    query = " OR ".join(f'all:"{term}"' for term in terms if term)
    params = {
        "search_query": query,
        "start": "0",
        "max_results": str(min(max(max_results, 1), 100)),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    text = http_text(url)
    root = ET.fromstring(text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    papers: list[Paper] = []
    for entry in root.findall("a:entry", ns):
        title = clean_text(entry.findtext("a:title", default="", namespaces=ns))
        published = entry.findtext("a:published", default="", namespaces=ns)
        year = int(published[:4]) if published[:4].isdigit() else None
        if year is not None and not (year_from <= year <= year_to):
            continue
        url_text = entry.findtext("a:id", default="", namespaces=ns)
        arxiv_id = url_text.rstrip("/").split("/")[-1] if url_text else None
        authors = [
            clean_text(author.findtext("a:name", default="", namespaces=ns))
            for author in entry.findall("a:author", ns)
        ]
        categories = [c.attrib.get("term", "") for c in entry.findall("a:category", ns)]
        papers.append(
            Paper(
                title=title,
                year=year,
                arxiv_id=arxiv_id,
                venue="arXiv:" + ",".join(c for c in categories if c),
                abstract=clean_text(entry.findtext("a:summary", default="", namespaces=ns)),
                authors=[a for a in authors if a],
                url=url_text or None,
                sources={"arXiv"},
            )
        )
    return papers


def search_crossref(topic: str, keywords: list[str], venues: list[str], year_from: int, year_to: int, max_results: int) -> list[Paper]:
    papers: list[Paper] = []
    per_query = max(5, min(20, max_results // 4))
    for query in make_search_queries(topic, keywords, venues)[:12]:
        params = {
            "query.bibliographic": query,
            "filter": f"from-pub-date:{year_from}-01-01,until-pub-date:{year_to}-12-31",
            "rows": str(per_query),
            "sort": "relevance",
            "order": "desc",
        }
        email = os.environ.get("CROSSREF_MAILTO") or os.environ.get("OPENALEX_MAILTO")
        if email:
            params["mailto"] = email
        url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
        data = http_json(url, headers={"User-Agent": user_agent()})
        for item in (data.get("message") or {}).get("items", []):
            title = clean_text((item.get("title") or [""])[0])
            if not title:
                continue
            year = crossref_year(item)
            if year is not None and not (year_from <= year <= year_to):
                continue
            container = clean_text((item.get("container-title") or [""])[0])
            authors = []
            for author in item.get("author", [])[:20]:
                name = clean_text(" ".join(x for x in [author.get("given"), author.get("family")] if x))
                if name:
                    authors.append(name)
            papers.append(
                Paper(
                    title=title,
                    year=year,
                    doi=norm_doi(item.get("DOI")),
                    venue=container or None,
                    abstract=clean_crossref_abstract(item.get("abstract")),
                    authors=authors,
                    citations=int(item.get("is-referenced-by-count") or 0),
                    url=item.get("URL"),
                    sources={"Crossref"},
                )
            )
        time.sleep(0.1)
    return dedupe(papers)


def user_agent() -> str:
    email = os.environ.get("CROSSREF_MAILTO") or os.environ.get("OPENALEX_MAILTO")
    suffix = f" (mailto:{email})" if email else ""
    return "research-paper-scout/1.1" + suffix


def crossref_year(item: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        parts = ((item.get(key) or {}).get("date-parts") or [])
        if parts and parts[0] and isinstance(parts[0][0], int):
            return parts[0][0]
    return None


def clean_crossref_abstract(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"<[^>]+>", " ", value)
    return clean_text(value)


def search_semantic_scholar(topic: str, keywords: list[str], venues: list[str], year_from: int, year_to: int, max_results: int) -> list[Paper]:
    headers = {}
    if os.environ.get("S2_API_KEY"):
        headers["x-api-key"] = os.environ["S2_API_KEY"]
    papers: list[Paper] = []
    per_query = max(5, min(20, max_results // 4))
    fields = "title,abstract,year,venue,publicationVenue,citationCount,referenceCount,influentialCitationCount,authors,externalIds,url,publicationTypes"
    query_limit = 12 if headers else 5
    for query in make_search_queries(topic, keywords, venues)[:query_limit]:
        params = {
            "query": query,
            "limit": str(per_query),
            "fields": fields,
            "year": f"{year_from}-{year_to}",
        }
        url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)
        data = http_json(url, headers=headers)
        for item in data.get("data", []):
            title = clean_text(item.get("title"))
            if not title:
                continue
            paper = Paper(title=title, sources={"Semantic Scholar"})
            merge_s2(paper, item)
            papers.append(paper)
        time.sleep(1 if not headers else 0.2)
    return dedupe(papers)


def search_dblp(topic: str, keywords: list[str], venues: list[str], year_from: int, year_to: int, max_results: int) -> list[Paper]:
    papers: list[Paper] = []
    per_query = max(5, min(20, max_results // 4))
    for query in make_search_queries(topic, keywords, venues)[:10]:
        params = {"q": query, "format": "json", "h": str(per_query)}
        url = "https://dblp.org/search/publ/api?" + urllib.parse.urlencode(params)
        data = http_json(url)
        hits = (((data.get("result") or {}).get("hits") or {}).get("hit") or [])
        if isinstance(hits, dict):
            hits = [hits]
        for hit in hits:
            info = hit.get("info") or {}
            title = clean_text(strip_trailing_period(info.get("title")))
            if not title:
                continue
            year = int(info.get("year")) if str(info.get("year") or "").isdigit() else None
            if year is not None and not (year_from <= year <= year_to):
                continue
            authors = dblp_authors(info.get("authors"))
            papers.append(
                Paper(
                    title=title,
                    year=year,
                    doi=norm_doi(info.get("doi")),
                    venue=clean_text(info.get("venue")) or None,
                    authors=authors,
                    url=info.get("ee") or info.get("url"),
                    sources={"DBLP"},
                )
            )
        time.sleep(0.1)
    return dedupe(papers)


def strip_trailing_period(value: str | None) -> str | None:
    return value[:-1] if value and value.endswith(".") else value


def dblp_authors(value: Any) -> list[str]:
    authors = ((value or {}).get("author") if isinstance(value, dict) else value) or []
    if isinstance(authors, (str, dict)):
        authors = [authors]
    result: list[str] = []
    for author in authors:
        if isinstance(author, dict):
            name = clean_text(author.get("text"))
        else:
            name = clean_text(str(author))
        if name:
            result.append(name)
    return result


def enrich_semantic_scholar(papers: list[Paper]) -> tuple[list[Paper], str | None]:
    headers = {}
    if os.environ.get("S2_API_KEY"):
        headers["x-api-key"] = os.environ["S2_API_KEY"]
    enriched: list[Paper] = []
    status_error = None
    for chunk in chunks(papers, 100):
        id_pairs: list[tuple[Paper, str]] = []
        for paper in chunk:
            if paper.doi:
                id_pairs.append((paper, "DOI:" + paper.doi))
            elif paper.arxiv_id:
                id_pairs.append((paper, "ARXIV:" + strip_arxiv_version(paper.arxiv_id)))
        if not id_pairs:
            enriched.extend(chunk)
            continue
        url = "https://api.semanticscholar.org/graph/v1/paper/batch?fields=" + urllib.parse.quote(S2_FIELDS)
        ids = [identifier for _, identifier in id_pairs]
        body = json.dumps({"ids": ids}).encode("utf-8")
        try:
            data = http_json(url, headers=headers, data=body)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            status_error = f"Semantic Scholar enrichment failed: {exc}"
            enriched.extend(chunk)
            continue
        enriched_ids = {id(paper) for paper, _ in id_pairs}
        for (paper, _), s2 in zip(id_pairs, data):
            if s2:
                merge_s2(paper, s2)
            enriched.append(paper)
        enriched.extend(paper for paper in chunk if id(paper) not in enriched_ids)
        time.sleep(1)
    return enriched, status_error


def strip_arxiv_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id)


def chunks(values: list[Paper], size: int) -> list[list[Paper]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def merge_s2(paper: Paper, data: dict[str, Any]) -> None:
    paper.sources.add("Semantic Scholar")
    paper.title = clean_text(data.get("title")) or paper.title
    paper.abstract = clean_text(data.get("abstract")) or paper.abstract
    paper.year = data.get("year") or paper.year
    publication_venue = data.get("publicationVenue") or {}
    paper.venue = clean_text(data.get("venue")) or clean_text(publication_venue.get("name")) or paper.venue
    paper.citations = max(paper.citations, int(data.get("citationCount") or 0))
    paper.references_count = max(paper.references_count, int(data.get("referenceCount") or 0))
    paper.influential_citations = max(paper.influential_citations, int(data.get("influentialCitationCount") or 0))
    paper.url = data.get("url") or paper.url
    paper.authors = [a.get("name") for a in data.get("authors", []) if a.get("name")] or paper.authors
    external = data.get("externalIds") or {}
    paper.doi = norm_doi(external.get("DOI")) or paper.doi
    paper.arxiv_id = external.get("ArXiv") or paper.arxiv_id
    references = data.get("references") or []
    paper.references = [
        {
            "title": ref.get("title"),
            "year": ref.get("year"),
            "doi": norm_doi((ref.get("externalIds") or {}).get("DOI")),
        }
        for ref in references[:30]
        if ref
    ]


def dedupe(papers: list[Paper]) -> list[Paper]:
    by_key: dict[str, Paper] = {}
    for paper in papers:
        key = "doi:" + paper.doi if paper.doi else "title:" + norm_title(paper.title)
        if key not in by_key:
            by_key[key] = paper
            continue
        existing = by_key[key]
        existing.sources.update(paper.sources)
        existing.citations = max(existing.citations, paper.citations)
        existing.references_count = max(existing.references_count, paper.references_count)
        existing.influential_citations = max(existing.influential_citations, paper.influential_citations)
        existing.abstract = existing.abstract or paper.abstract
        existing.doi = existing.doi or paper.doi
        existing.arxiv_id = existing.arxiv_id or paper.arxiv_id
        existing.venue = existing.venue or paper.venue
        existing.url = existing.url or paper.url
        existing.authors = existing.authors or paper.authors
        existing.references = existing.references or paper.references
    return list(by_key.values())


def score_papers(papers: list[Paper], topic: str, keywords: list[str], venues: list[str], year_from: int, year_to: int) -> None:
    venue_terms = [v.lower() for v in venues]
    span = max(year_to - year_from, 1)
    query_text = " ".join([topic] + keywords)
    anchors = domain_anchor_tokens(topic, keywords)
    for paper in papers:
        content = " ".join([paper.title, paper.abstract or ""])
        haystack = " ".join([content, paper.venue or ""]).lower()
        paper.content_similarity = cosine_similarity(query_text, content)
        paper.concept_coverage = concept_coverage(topic, keywords, content)
        paper.domain_focus = domain_focus_score(anchors, content)
        paper.method_focus = method_focus_score(topic, keywords, content)
        paper.relevance = min(
            1.0,
            (paper.content_similarity * 0.28)
            + (paper.concept_coverage * 0.18)
            + (paper.domain_focus * 0.22)
            + (paper.method_focus * 0.32),
        )
        paper.is_survey = any(term in haystack for term in SURVEY_TERMS)
        citation_score = min(1.0, math.log1p(max(paper.citations, 0)) / math.log(1001))
        recency = 0.0
        if paper.year:
            recency = max(0.0, min(1.0, (paper.year - year_from) / span))
        venue_name = (paper.venue or "").lower()
        requested_venue = requested_venue_match(venue_name, venue_terms)
        quality_venue = any(v in venue_name for v in QUALITY_VENUES)
        venue_score = (0.18 if requested_venue else 0.0) + (0.08 if quality_venue else 0.0)
        survey_score = 0.04 if paper.is_survey else 0.0
        exact_title_boost = exact_title_match_boost(paper.title, topic, keywords)
        paper.score = (
            (paper.relevance * 0.52)
            + (paper.method_focus * 0.22)
            + (citation_score * 0.06)
            + (recency * 0.05)
            + venue_score
            + survey_score
            + exact_title_boost
        )
        if anchors and paper.domain_focus == 0:
            paper.score *= 0.18
            paper.relevance *= 0.25
        if paper.method_focus == 0:
            paper.score *= 0.55


def requested_venue_match(venue_name: str, venue_terms: list[str]) -> bool:
    if any(v and v in venue_name for v in venue_terms):
        return True
    if "tvcg" in venue_terms and "transactions on visualization and computer graphics" in venue_name:
        return True
    if "ieee vr" in venue_terms and "virtual reality" in venue_name:
        return True
    if "tog" in venue_terms and "transactions on graphics" in venue_name:
        return True
    return False


def exact_title_match_boost(title: str, topic: str, keywords: list[str]) -> float:
    title_norm = norm_title(title)
    if not title_norm:
        return 0.0
    boost = 0.0
    topic_norm = norm_title(topic)
    if topic_norm and topic_norm in title_norm:
        boost = max(boost, 0.18)
    for keyword in keywords:
        keyword_norm = norm_title(keyword)
        if len(keyword_norm) >= 4 and keyword_norm in title_norm:
            boost = max(boost, 0.25 if len(keyword_norm.split()) <= 2 else 0.18)
    return boost


def domain_focus_score(anchors: list[str], text: str) -> float:
    if not anchors:
        return 0.0
    text_tokens = set(content_tokens(text))
    hits = sum(1 for token in anchors if token in text_tokens)
    phrase_bonus = 0.0
    lowered = text.lower()
    for phrase in (" ".join(anchors[:3]), " ".join(anchors[:2])):
        if phrase and phrase in lowered:
            phrase_bonus = max(phrase_bonus, 0.25)
    return min(1.0, hits / max(3, min(len(anchors), 6)) + phrase_bonus)


def method_focus_score(topic: str, keywords: list[str], text: str) -> float:
    concepts = [topic] + keywords
    normalized_text = norm_title(text)
    matched = 0
    considered = 0
    for concept in concepts:
        tokens = set(content_tokens(concept))
        if len(tokens) < 2 and not re.search(r"[A-Z].*[A-Z]|\d", concept):
            continue
        considered += 1
        normalized_concept = norm_title(concept)
        if normalized_concept and normalized_concept in normalized_text:
            matched += 1
            continue
        if tokens:
            coverage = len(tokens & set(content_tokens(text))) / len(tokens)
            if coverage >= 0.67:
                matched += 1
    if considered == 0:
        return 0.0
    return min(1.0, matched / min(6, considered))


def paper_to_row(paper: Paper) -> dict[str, Any]:
    return {
        "score": round(paper.score, 4),
        "relevance": round(paper.relevance, 4),
        "content_similarity": round(paper.content_similarity, 4),
        "concept_coverage": round(paper.concept_coverage, 4),
        "domain_focus": round(paper.domain_focus, 4),
        "method_focus": round(paper.method_focus, 4),
        "title": paper.title,
        "year": paper.year or "",
        "venue": paper.venue or "",
        "citations": paper.citations,
        "influential_citations": paper.influential_citations,
        "references_count": paper.references_count,
        "authors": "; ".join(paper.authors[:20]),
        "doi": paper.doi or "",
        "arxiv_id": paper.arxiv_id or "",
        "url": paper.url or "",
        "sources": "; ".join(sorted(paper.sources)),
        "is_survey": paper.is_survey,
        "abstract": paper.abstract or "",
    }


def write_csv(path: Path, papers: list[Paper]) -> None:
    rows = [paper_to_row(p) for p in papers]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else list(paper_to_row(Paper("")).keys()))
        writer.writeheader()
        writer.writerows(rows)


def bib_key(paper: Paper) -> str:
    first_author = "anon"
    if paper.authors:
        first_author = re.sub(r"[^A-Za-z0-9]+", "", paper.authors[0].split()[-1]).lower() or "anon"
    title_word = next((w.lower() for w in re.findall(r"[A-Za-z0-9]+", paper.title) if len(w) > 3), "paper")
    return f"{first_author}{paper.year or 'nd'}{title_word}"


def escape_bib(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def write_bib(path: Path, papers: list[Paper]) -> None:
    seen: set[str] = set()
    with path.open("w", encoding="utf-8") as handle:
        for paper in papers:
            key = bib_key(paper)
            original = key
            i = 2
            while key in seen:
                key = f"{original}{i}"
                i += 1
            seen.add(key)
            entry_type = "article" if paper.doi else "misc"
            fields = {
                "title": paper.title,
                "author": " and ".join(paper.authors),
                "year": str(paper.year or ""),
                "journal": paper.venue or "",
                "doi": paper.doi or "",
                "eprint": paper.arxiv_id or "",
                "url": paper.url or "",
            }
            handle.write(f"@{entry_type}{{{key},\n")
            for name, value in fields.items():
                if value:
                    handle.write(f"  {name} = {{{escape_bib(value)}}},\n")
            handle.write("}\n\n")


def sentence_for(paper: Paper, keywords: list[str]) -> str:
    text = (paper.abstract or "").strip()
    if text:
        return re.split(r"(?<=[.!?])\s+", text)[0][:280]
    matched = [k for k in keywords if k.lower() in (paper.title + " " + (paper.venue or "")).lower()]
    if matched:
        return "Matches " + ", ".join(matched[:4]) + "."
    return "Relevant by title/topic match and scholarly metadata."


def research_gaps(papers: list[Paper], keywords: list[str], year_to: int) -> list[str]:
    gaps: list[str] = []
    for keyword in keywords:
        matches = [p for p in papers if keyword.lower() in (p.title + " " + (p.abstract or "")).lower()]
        if len(matches) <= 1:
            gaps.append(f"Few strong matches for '{keyword}', suggesting a possible under-explored subtopic or wording mismatch.")
    recent_relevant = [p for p in papers if p.year == year_to and p.relevance >= 0.35 and p.citations <= 5]
    if recent_relevant:
        gaps.append("Several recent, relevant papers have low citation counts, so emerging directions may not yet be consolidated.")
    surveys = [p for p in papers if p.is_survey]
    recent_non_survey = [p for p in papers if p.year and p.year >= year_to - 1 and not p.is_survey]
    if surveys and len(recent_non_survey) < max(3, len(surveys)):
        gaps.append("Survey/review coverage appears stronger than very recent empirical coverage in the retrieved set.")
    venues = {}
    for paper in papers:
        venue = (paper.venue or "unknown").split(":")[0]
        venues[venue] = venues.get(venue, 0) + 1
    if len(venues) <= 3 and len(papers) >= 10:
        gaps.append("Results cluster in a small number of venues/sources; adjacent disciplines may need targeted searches.")
    return gaps[:8] or ["No clear automated gap signal found; inspect abstracts and references manually for finer-grained gaps."]


def prior_art_assessment(papers: list[Paper], topic: str, keywords: list[str]) -> dict[str, Any]:
    strong = [
        p
        for p in papers
        if p.relevance >= 0.34 and p.concept_coverage >= 0.25 and p.domain_focus >= 0.30 and p.method_focus >= 0.30
    ]
    moderate = [
        p
        for p in papers
        if p.relevance >= 0.24 and p.concept_coverage >= 0.18 and p.domain_focus >= 0.25 and p.method_focus >= 0.17
    ]
    adjacent = [p for p in papers if p.relevance >= 0.16 and p.domain_focus >= 0.20 and p.method_focus >= 0.10]
    survey_matches = [p for p in strong if p.is_survey]
    direct_strong = [
        p
        for p in strong
        if p.method_focus >= 0.45 and p.concept_coverage >= 0.35 and exact_title_match_boost(p.title, topic, keywords) >= 0.18
    ]
    if len(direct_strong) >= 3 or (len(direct_strong) >= 2 and len(strong) >= 5):
        verdict = "likely_done"
        confidence = "medium-high"
        answer = "Content-level matches suggest closely related prior work exists; treat the direction as already studied unless your exact task, method, data, domain, or evaluation is different."
    elif len(strong) >= 1 or len(moderate) >= 3 or len(adjacent) >= 6:
        verdict = "partially_done"
        confidence = "medium"
        answer = "Content-level matches show adjacent prior work, but the exact formulation may still be open depending on your task, method, domain, dataset, and evaluation."
    elif papers:
        verdict = "no_clear_prior_work_found"
        confidence = "low-medium"
        answer = "No clear close content-level prior match was found in the searched sources, though broader adjacent work exists."
    else:
        verdict = "no_clear_prior_work_found"
        confidence = "low"
        answer = "No candidate papers were found; this may reflect search/API coverage rather than true absence of prior work."
    already_covered = []
    if strong:
        already_covered.append(f"{len(strong)} retrieved papers have strong title/abstract content overlap with the proposed direction.")
    if moderate:
        already_covered.append(f"{len(moderate)} retrieved papers have moderate content overlap across the topic and keyword concepts.")
    if survey_matches:
        already_covered.append("Survey/review-style papers with strong content overlap indicate the area may already have organized literature.")
    if not already_covered:
        already_covered.append("The retrieved papers mostly appear adjacent rather than directly aligned at the content level.")
    novelty_angles = []
    keyword_coverage = {
        keyword: sum(1 for p in papers if keyword.lower() in (p.title + " " + (p.abstract or "")).lower())
        for keyword in keywords
    }
    sparse_keywords = [k for k, count in keyword_coverage.items() if count <= 1]
    if sparse_keywords:
        novelty_angles.append("Sparse keyword coverage may indicate room around: " + ", ".join(sparse_keywords[:5]) + ".")
    novelty_angles.append("Check whether your exact combination of task, method, data, domain, constraints, and evaluation differs from the closest papers.")
    novelty_angles.append("Read the closest papers' related-work and limitation sections before claiming novelty.")
    return {
        "verdict": verdict,
        "confidence": confidence,
        "answer": answer,
        "closest": [p for p in papers if p.domain_focus >= 0.20 and p.method_focus >= 0.30][: min(5, len(papers))],
        "already_covered": already_covered,
        "novelty_angles": novelty_angles[:6],
    }


def reliability_warnings(papers: list[Paper], api_status: list[str]) -> list[str]:
    warnings: list[str] = []
    top = papers[: min(10, len(papers))]
    if top and max(p.domain_focus for p in top) < 0.20:
        warnings.append(
            "Top-ranked candidates have weak domain-anchor coverage; closest-evidence ranking may be lexical rather than content-level."
        )
    if top and max(p.method_focus for p in top) < 0.10:
        warnings.append(
            "Top-ranked candidates have weak method-keyword coverage; they may share the domain but not the proposed technical formulation."
        )
    if not papers:
        warnings.append("No papers were retained after search and ranking; absence of results is not evidence of novelty.")
    failed_or_empty = [
        item
        for item in api_status
        if "failed" in item.lower() or " 0 candidates" in item.lower() or "429" in item
    ]
    if failed_or_empty:
        warnings.append("One or more search/enrichment sources failed or returned no candidates; use targeted manual search before citing the verdict.")
    return warnings


def write_conclusion_md(
    path: Path,
    papers: list[Paper],
    topic: str,
    keywords: list[str],
    api_status: list[str],
) -> None:
    gaps = research_gaps(papers, keywords, max((p.year or 0 for p in papers), default=0))
    assessment = prior_art_assessment(papers, topic, keywords)
    warnings = reliability_warnings(papers, api_status)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# Prior-Art Conclusion\n\n")
        if warnings:
            handle.write("## Reliability Warning\n\n")
            for warning in warnings:
                handle.write(f"- {warning}\n")
            handle.write("\n")
        handle.write("## Verdict\n\n")
        handle.write(f"- Research topic: {topic}\n")
        handle.write(f"- Verdict: `{assessment['verdict']}`\n")
        handle.write(f"- Confidence: {assessment['confidence']}\n")
        handle.write(f"- Direct answer: {assessment['answer']}\n")
        write_paper_section(handle, "Closest Evidence", assessment["closest"], keywords)
        handle.write("\n## What Seems Already Covered\n\n")
        for item in assessment["already_covered"]:
            handle.write(f"- {item}\n")
        handle.write("\n## What May Still Be Novel\n\n")
        for item in assessment["novelty_angles"]:
            handle.write(f"- {item}\n")
        handle.write("\n## Possible Research Gaps\n\n")
        for gap in gaps:
            handle.write(f"- {gap}\n")
        handle.write("\n## API Status\n\n")
        for item in api_status:
            handle.write(f"- {item}\n")


def write_paper_section(handle: Any, heading: str, papers: list[Paper], keywords: list[str]) -> None:
    handle.write(f"\n## {heading}\n\n")
    if not papers:
        handle.write("No papers found for this section.\n")
        return
    for i, paper in enumerate(papers, 1):
        authors = ", ".join(paper.authors[:3])
        if len(paper.authors) > 3:
            authors += " et al."
        link = paper.doi or paper.arxiv_id or paper.url or ""
        handle.write(
            f"{i}. **{paper.title}** ({paper.year or 'n.d.'}). {authors}. "
            f"{paper.venue or 'Unknown venue'}. Citations: {paper.citations}. "
            f"Score: {paper.score:.3f}; content similarity: {paper.content_similarity:.3f}; "
            f"concept coverage: {paper.concept_coverage:.3f}; domain focus: {paper.domain_focus:.3f}; "
            f"method focus: {paper.method_focus:.3f}. {link}\n"
        )
        handle.write(f"   - {sentence_for(paper, keywords)}\n")


def run(args: argparse.Namespace) -> int:
    keywords = split_csvish(args.keywords)
    venues = split_csvish(args.venues)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    api_status: list[str] = []
    candidates: list[Paper] = []
    openalex_n = max(args.max_results * 3, 50)
    arxiv_n = max(args.max_results, 25)
    try:
        openalex = search_openalex(args.research_topic, keywords, venues, args.year_from, args.year_to, openalex_n)
        candidates.extend(openalex)
        api_status.append(f"OpenAlex succeeded: {len(openalex)} candidates.")
    except Exception as exc:  # noqa: BLE001 - keep partial workflow alive.
        api_status.append(f"OpenAlex failed: {exc}")
    try:
        crossref = search_crossref(args.research_topic, keywords, venues, args.year_from, args.year_to, openalex_n)
        candidates.extend(crossref)
        api_status.append(f"Crossref succeeded: {len(crossref)} candidates.")
    except Exception as exc:  # noqa: BLE001 - keep partial workflow alive.
        api_status.append(f"Crossref failed: {exc}")
    try:
        dblp = search_dblp(args.research_topic, keywords, venues, args.year_from, args.year_to, openalex_n)
        candidates.extend(dblp)
        api_status.append(f"DBLP succeeded: {len(dblp)} candidates.")
    except Exception as exc:  # noqa: BLE001 - keep partial workflow alive.
        api_status.append(f"DBLP failed: {exc}")
    if os.environ.get("S2_API_KEY"):
        try:
            s2_search = search_semantic_scholar(args.research_topic, keywords, venues, args.year_from, args.year_to, openalex_n)
            candidates.extend(s2_search)
            api_status.append(f"Semantic Scholar search succeeded: {len(s2_search)} candidates.")
        except Exception as exc:  # noqa: BLE001 - keep partial workflow alive.
            api_status.append(f"Semantic Scholar search failed: {exc}")
    else:
        api_status.append("Semantic Scholar search skipped: S2_API_KEY is not set.")
    try:
        arxiv = search_arxiv(args.research_topic, keywords, args.year_from, args.year_to, arxiv_n)
        candidates.extend(arxiv)
        api_status.append(f"arXiv succeeded: {len(arxiv)} candidates.")
    except Exception as exc:  # noqa: BLE001 - keep partial workflow alive.
        api_status.append(f"arXiv failed: {exc}")
    candidates = dedupe(candidates)
    candidates, s2_error = enrich_semantic_scholar(candidates)
    api_status.append(s2_error or f"Semantic Scholar enrichment completed for {len(candidates)} deduplicated candidates.")
    candidates = dedupe(candidates)
    score_papers(candidates, args.research_topic, keywords, venues, args.year_from, args.year_to)
    papers = sorted(candidates, key=lambda p: p.score, reverse=True)[: args.max_results]
    csv_path = output_dir / "papers.csv"
    md_path = output_dir / "prior_art_conclusion.md"
    for stale_name in ("papers.bib", "papers.json", "summary.md"):
        stale_path = output_dir / stale_name
        if stale_path.exists():
            stale_path.unlink()
    write_csv(csv_path, papers)
    write_conclusion_md(md_path, papers, args.research_topic, keywords, api_status)
    assessment = prior_art_assessment(papers, args.research_topic, keywords)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "files": [str(csv_path), str(md_path)],
                "prior_art_verdict": assessment["verdict"],
                "confidence": assessment["confidence"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--intent",
        choices=["prior-art", "ranking"],
        default="prior-art",
        help="Use prior-art to answer whether the direction has been done; ranking keeps the classic paper-list focus.",
    )
    parser.add_argument("--research-topic", required=True)
    parser.add_argument("--keywords", required=True, help="Comma/semicolon separated keywords and synonyms.")
    parser.add_argument("--year-from", required=True, type=int)
    parser.add_argument("--year-to", required=True, type=int)
    parser.add_argument("--max-results", required=True, type=int)
    parser.add_argument("--venues", default="", help="Optional comma/semicolon separated venues.")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    if args.year_from > args.year_to:
        parser.error("--year-from must be <= --year-to")
    if args.max_results < 1:
        parser.error("--max-results must be >= 1")
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args(sys.argv[1:])))
