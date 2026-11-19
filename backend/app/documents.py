"""Tender / procurement document analysis (PDF via pypdf, DOCX via python-docx).

Every extracted field carries the page reference it came from. Fields not found are None —
missing clauses are never fabricated. Scanned PDFs (little or no extractable text) are flagged
for manual review.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import datetime

from bs4 import BeautifulSoup

MIN_CHARS_PER_PAGE = 40


class DocumentError(Exception):
    pass


@dataclass
class ExtractedField:
    value: str
    page_reference: str | None
    excerpt: str


@dataclass
class DocumentAnalysis:
    file_name: str
    file_type: str
    pages: list[tuple[str | None, str]]
    needs_manual_review: bool
    review_reason: str | None
    fields: dict[str, ExtractedField | None] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n\n".join(t for _, t in self.pages)


def extract_pdf(data: bytes) -> list[tuple[str | None, str]]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise DocumentError("PDF is encrypted") from exc
        return [(f"p.{i + 1}", (page.extract_text() or "").strip()) for i, page in enumerate(reader.pages)]
    except PdfReadError as exc:
        raise DocumentError(f"Unreadable PDF: {exc}") from exc


def extract_docx(data: bytes) -> list[tuple[str | None, str]]:
    import docx

    try:
        d = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise DocumentError(f"Unreadable DOCX: {exc}") from exc
    # DOCX has no fixed pages; reference paragraphs/sections instead.
    chunks: list[tuple[str | None, str]] = []
    buf: list[str] = []
    start = 1
    for i, p in enumerate(d.paragraphs, start=1):
        if p.text.strip():
            buf.append(p.text.strip())
        if len(buf) >= 25:
            chunks.append((f"para.{start}-{i}", "\n".join(buf)))
            buf, start = [], i + 1
    if buf:
        chunks.append((f"para.{start}-{len(d.paragraphs)}", "\n".join(buf)))
    for ti, table in enumerate(d.tables, start=1):
        rows = [" | ".join(c.text.strip() for c in row.cells) for row in table.rows]
        chunks.append((f"table.{ti}", "\n".join(rows)))
    return chunks


def extract_html(data: bytes) -> tuple[str | None, str]:
    soup = BeautifulSoup(data, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else None
    for tag in soup(["script", "style", "noscript", "template", "nav", "footer", "header"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = re.sub(r"\n\s*\n+", "\n\n", main.get_text("\n"))
    text = re.sub(r"[ \t]+", " ", text)
    return title, text.strip()


DATE_PAT = r"(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9},?\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})"

FIELD_PATTERNS: dict[str, list[str]] = {
    "tender_title": [r"(?:name of (?:the )?work|tender title|title of (?:the )?(?:tender|work|project)|subject)\s*[:\-]\s*(.{5,200})"],
    "buyer": [r"(?:issued by|organi[sz]ation(?: name)?|tender inviting authority|department|buyer|purchaser|procuring entity)\s*[:\-]\s*(.{3,150})"],
    "publication_date": [r"(?:publish(?:ed|ing)? date|date of (?:publication|issue)|tender (?:issue|publish) date)\s*[:\-]?\s*" + DATE_PAT],
    "submission_deadline": [r"(?:(?:bid|tender) (?:submission )?(?:end|closing|due) date|last date (?:and time )?(?:for|of) (?:submission|receipt)|submission deadline|bid end date)\s*(?:&\s*time)?\s*[:\-]?\s*" + DATE_PAT],
    "project_scope": [r"(?:scope of (?:the )?work|scope of services|project scope|brief description)\s*[:\-]?\s*(.{10,600})"],
    "budget": [r"(?:estimated (?:cost|value)|tender value|project (?:cost|budget)|budget)\s*[:\-]?\s*((?:Rs\.?|INR|₹|USD|\$)\s?[\d,]+(?:\.\d+)?\s*(?:lakhs?|crores?)?)"],
    "emd": [r"(?:EMD|earnest money(?: deposit)?|bid security)(?: amount)?\s*(?:\(.*?\))?\s*[:\-]?\s*((?:Rs\.?|INR|₹)\s?[\d,]+(?:\.\d+)?\s*(?:lakhs?|crores?)?|nil|exempted?)"],
    "turnover_requirement": [r"([^.\n]*\bturnover\b[^.\n]*)"],
    "experience_requirement": [r"([^.\n]*\b(?:similar (?:work|projects?)|experience of|years? of experience|prior experience)\b[^.\n]*)"],
    "gst_requirement": [r"([^.\n]*\b(?:GSTIN|GST registration|GST number)\b[^.\n]*)"],
    "legal_entity_restrictions": [r"([^.\n]*\b(?:registered (?:company|firm)|companies act|proprietor\w*|partnership firm|LLP)\b[^.\n]*)"],
    "consortium_rules": [r"([^.\n]*\b(?:consortium|joint venture)\b[^.\n]*)"],
    "subcontracting_rules": [r"([^.\n]*\bsub-?contract\w*\b[^.\n]*)"],
    "contact_information": [r"((?:contact|email|e-mail|phone|tel)\s*[:\-]\s*[^\n]{5,150})"],
}


def extract_fields(pages: list[tuple[str | None, str]]) -> dict[str, ExtractedField | None]:
    out: dict[str, ExtractedField | None] = {}
    for name, pats in FIELD_PATTERNS.items():
        found = None
        for page_ref, text in pages:
            for pat in pats:
                m = re.search(pat, text, re.I)
                if m:
                    value = re.sub(r"\s+", " ", m.group(1)).strip(" :-")
                    s, e = max(0, m.start() - 60), min(len(text), m.end() + 60)
                    found = ExtractedField(value[:600], page_ref, re.sub(r"\s+", " ", text[s:e]).strip())
                    break
            if found:
                break
        out[name] = found
    return out


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = re.sub(r"(\d)(st|nd|rd|th)", r"\1", s.strip()).replace(",", "")
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def analyse_document(file_name: str, data: bytes) -> DocumentAnalysis:
    lower = file_name.lower()
    if lower.endswith(".pdf") or data[:5] == b"%PDF-":
        pages, ftype = extract_pdf(data), "pdf"
    elif lower.endswith(".docx"):
        pages, ftype = extract_docx(data), "docx"
    else:
        raise DocumentError("Unsupported file type; upload a PDF or DOCX")

    total = sum(len(t) for _, t in pages)
    low_text_pages = sum(1 for _, t in pages if len(t) < MIN_CHARS_PER_PAGE)
    needs_review, reason = False, None
    if not pages or total < MIN_CHARS_PER_PAGE:
        needs_review, reason = True, "No extractable text — the document appears to be scanned. Manual review required."
    elif ftype == "pdf" and low_text_pages / len(pages) > 0.5:
        needs_review, reason = True, f"{low_text_pages} of {len(pages)} pages have little extractable text (possibly scanned). Manual review required."
    analysis = DocumentAnalysis(file_name, ftype, pages, needs_review, reason)
    analysis.fields = extract_fields(pages) if total else {k: None for k in FIELD_PATTERNS}
    return analysis
