"""Odczyt PDF: warstwa tekstowa, wykrywanie stron-skanow, render obrazow do OCR."""
import base64
import re
from dataclasses import dataclass, field

import pymupdf


@dataclass
class Page:
    number: int          # 1-based
    text: str
    is_scan: bool
    source: str = "text"  # text | ocr


@dataclass
class Document:
    path: str
    pages: list = field(default_factory=list)
    total_pages: int = 0

    @property
    def text(self) -> str:
        return "\n".join(f"[strona {p.number}]\n{p.text}" for p in self.pages if p.text.strip())

    @property
    def plain(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def has_scans(self) -> bool:
        return any(p.is_scan for p in self.pages)


_WORD = re.compile(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{3,}")


def text_quality_ok(text: str, min_chars: int) -> bool:
    """Tekst uznany za wiarygodny: dosc znakow i dosc normalnych slow."""
    if len(text.strip()) < min_chars:
        return False
    if text.count("\ufffd") + text.count("(cid:") > 5:      # znaki zastepcze = zepsute fonty
        return False
    body = re.sub(r"[\s.\-_=*·:|]", "", text)            # bez spacji i znakow wypelniajacych (......)
    if body and sum(ch.isalnum() for ch in body) < 0.6 * len(body):  # glownie dziwne symbole = zepsuty tekst
        return False
    words = _WORD.findall(text)
    return len(words) >= 8


def load(path: str, max_pages: int = 4, min_chars: int = 60) -> Document:
    doc = pymupdf.open(path)
    out = Document(path=str(path), total_pages=doc.page_count)
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        text = page.get_text("text", sort=True)
        out.pages.append(Page(number=i + 1, text=text, is_scan=not text_quality_ok(text, min_chars)))
    doc.close()
    return out


def render_png_b64(path: str, page_number: int, dpi: int = 150, rotate: int = 0) -> str:
    doc = pymupdf.open(path)
    page = doc[page_number - 1]
    matrix = pymupdf.Matrix(dpi / 72, dpi / 72).prerotate(rotate)
    pix = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csGRAY)
    data = pix.tobytes("jpeg", jpg_quality=80)
    doc.close()
    return base64.b64encode(data).decode()
