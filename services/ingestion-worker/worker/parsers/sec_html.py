"""SEC filing HTML normalizer and section extractor.

This parser targets modern EDGAR HTML filings, strips noisy tags/TOC text, and
extracts the MVP sections used by retrieval: Item 1, Item 1A, Item 7, Item 7A,
and Item 8. PDF parsing is intentionally out of scope for the hackathon MVP.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, Tag

from ..models import FilingRef, NormalizedDocument, NormalizedSection


SECTION_DEFS = {
    "item_1": {
        "item_label": "Item 1",
        "title": "Business",
        "pattern": re.compile(r"^\s*item\s+1\.?\s*(business)?\s*$", re.IGNORECASE),
    },
    "item_1a": {
        "item_label": "Item 1A",
        "title": "Risk Factors",
        "pattern": re.compile(r"^\s*item\s+1a\.?\s*(risk\s+factors)?\s*$", re.IGNORECASE),
    },
    "item_7": {
        "item_label": "Item 7",
        "title": "Management's Discussion and Analysis",
        "pattern": re.compile(
            r"^\s*item\s+7\.?\s*(management.{0,80}discussion.{0,80}analysis)?\s*$",
            re.IGNORECASE,
        ),
    },
    "item_7a": {
        "item_label": "Item 7A",
        "title": "Quantitative Disclosures About Market Risk",
        "pattern": re.compile(
            r"^\s*item\s+7a\.?\s*(quantitative.{0,80}market\s+risk)?\s*$",
            re.IGNORECASE,
        ),
    },
    "item_8": {
        "item_label": "Item 8",
        "title": "Financial Statements",
        "pattern": re.compile(
            r"^\s*item\s+8\.?\s*(financial\s+statements.{0,80})?\s*$",
            re.IGNORECASE,
        ),
    },
}

BLOCK_TAGS = [
    "a",
    "b",
    "div",
    "font",
    "h1",
    "h2",
    "h3",
    "h4",
    "p",
    "span",
    "strong",
    "table",
]


def parse_sec_html(html: str, filing: FilingRef) -> NormalizedDocument:
    sections = extract_sections(html)
    return NormalizedDocument(
        document_id=_stable_document_id(filing),
        ticker=filing.ticker,
        cik=filing.cik,
        company_name=filing.company_name,
        filing_type=filing.filing_type,
        accession_number=filing.accession_number,
        filed_at=filing.filed_at,
        fiscal_period=filing.fiscal_period or filing.filed_at[:4],
        source_url=filing.source_url or "",
        sections=sections,
    )


def _stable_document_id(filing: FilingRef) -> str:
    # Accession numbers are globally unique per SEC filing, so hashing on
    # ticker + accession number keeps document_id stable across ingestion
    # reruns (upsert_document keys on this id to avoid duplicate rows).
    key = f"{filing.ticker}:{filing.accession_number}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def extract_sections(html: str) -> list[NormalizedSection]:
    soup = BeautifulSoup(html, "lxml")
    _clean_soup(soup)
    body = soup.body or soup
    blocks = [tag for tag in body.find_all(BLOCK_TAGS) if _is_visible_tag(tag)]
    starts = _find_section_starts(blocks)
    sections: dict[str, NormalizedSection] = {}

    for pos, section_id in starts:
        next_pos = _next_section_pos(starts, pos)
        content_blocks = blocks[pos + 1 : next_pos]
        section = _build_section(section_id, content_blocks)
        current = sections.get(section_id)
        if current is None or section.word_count > current.word_count:
            sections[section_id] = section

    return [sections[key] for key in SECTION_DEFS if key in sections]


def normalize_text(text: str) -> str:
    text = re.sub(r"\bTable\s+of\s+Contents\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_soup(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for tag in list(soup.find_all()):
        if ":" in tag.name:
            tag.unwrap()


def _find_section_starts(blocks: list[Tag]) -> list[tuple[int, str]]:
    starts: list[tuple[int, str]] = []
    for index, block in enumerate(blocks):
        text = normalize_text(block.get_text(" ", strip=True))
        if len(text) > 220:
            continue
        for section_id, spec in SECTION_DEFS.items():
            if spec["pattern"].match(text):
                starts.append((index, section_id))
                break
    return starts


def _next_section_pos(starts: list[tuple[int, str]], pos: int) -> int:
    for candidate_pos, _section_id in starts:
        if candidate_pos > pos:
            return candidate_pos
    return 10**9


def _build_section(section_id: str, blocks: Iterable[Tag]) -> NormalizedSection:
    spec = SECTION_DEFS[section_id]
    paragraphs: list[str] = []
    tables: list[str] = []

    for block in blocks:
        block_tables = [block] if block.name == "table" else list(block.find_all("table"))
        for table in block_tables:
            table_text = _table_to_markdown(table)
            if table_text:
                tables.append(table_text)
            table.decompose()

        text = normalize_text(block.get_text(" ", strip=True))
        if text and not _looks_like_toc_line(text):
            paragraphs.append(text)

    body = "\n\n".join(_dedupe_preserve_order(paragraphs))
    return NormalizedSection(
        section_id=section_id,
        item_label=str(spec["item_label"]),
        title=str(spec["title"]),
        text=body,
        tables=_dedupe_preserve_order(tables),
        word_count=len(body.split()),
    )


def _table_to_markdown(table: Tag) -> str:
    rows: list[str] = []
    for tr in table.find_all("tr"):
        cells = [
            normalize_text(cell.get_text(" ", strip=True))
            for cell in tr.find_all(["th", "td"])
        ]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _looks_like_toc_line(text: str) -> bool:
    lowered = text.lower()
    if lowered == "table of contents":
        return True
    return bool(re.match(r"^item\s+\d+[a-z]?\s+.{0,80}\s+\d{1,4}$", lowered))


def _is_visible_tag(tag: Tag) -> bool:
    return bool(normalize_text(tag.get_text(" ", strip=True)))


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
