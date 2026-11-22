"""Transparentnosc: skad pochodzi kazda wartosc (regula / model), gdzie jest w PDF i jak bardzo jej ufamy."""
import re

import pymupdf

from .normalize import MONTHS, digits, fold

_MONTH_GEN = {v: k for k, v in MONTHS.items() if k.endswith(("a", "ia"))}  # 3 -> "marca"


def _leaves(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, f"{path}[{i}]")
    else:
        yield path, obj


def generic(path: str) -> str:
    return re.sub(r"\[\d+\]", "[]", path)


def variants(kind: str, value) -> list[str]:
    """Rozne zapisy tej samej wartosci, jakie moga wystapic w dokumencie."""
    s = str(value)
    out = [s]
    if kind == "date":
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            y, mo, d = int(m[1]), int(m[2]), int(m[3])
            out += [f"{d:02d}.{mo:02d}.{y}", f"{d}.{mo:02d}.{y}", f"{d:02d}-{mo:02d}-{y}", f"{d:02d}/{mo:02d}/{y}"]
            if mo in _MONTH_GEN:
                out += [f"{d} {_MONTH_GEN[mo]} {y}", f"{d:02d} {_MONTH_GEN[mo]} {y}"]
    elif kind == "iban":
        d = digits(s)
        grouped = d[:2] + " " + " ".join(d[i:i + 4] for i in range(2, len(d), 4))
        out += ["PL" + d, "PL" + grouped, grouped, d]
    elif kind in ("nip", "regon", "krs", "pesel"):
        d = digits(s)
        out += [d, d.lstrip("0")]
        if len(d) == 10:
            out += [f"{d[:3]}-{d[3:6]}-{d[6:8]}-{d[8:]}", f"{d[:3]}-{d[3:5]}-{d[5:7]}-{d[7:]}", f"{d[:3]} {d[3:6]} {d[6:8]} {d[8:]}"]
    elif kind == "amount":
        try:
            v = float(s)
            out += [f"{v:,.2f}".replace(",", " ").replace(".", ","), f"{v:.2f}".replace(".", ","), f"{v:.2f}"]
        except ValueError:
            pass
    else:
        words = s.split()
        if len(words) > 4:          # dlugi tekst: szukamy poczatku (bywa zlamany na kilka linii)
            out += [" ".join(words[:4]), " ".join(words[:2])]
    seen, res = set(), []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            res.append(v)
    return res


def provenance(pdf_path, doc, result, dt, rule_values, fill_applied, derived, rule_trace=()):
    """Lista: pole, wartosc, zrodlo, strona, prostokaty (w punktach PDF), pewnosc."""
    out, pages = [], []
    try:
        pdoc = pymupdf.open(pdf_path)
    except Exception:
        pdoc = None
    if pdoc is not None:
        for i, p in enumerate(doc.pages):
            pages.append({"n": p.number, "width": pdoc[i].rect.width, "height": pdoc[i].rect.height,
                          "scan": p.is_scan})
    text_folded = fold(doc.plain)
    # zdanie/linia, z ktorej regula wziela wartosc (np. kod czynnosci) - do podswietlenia
    evidence = {}
    for t in rule_trace:
        if t.get("match") and t.get("field"):
            evidence.setdefault(t["field"], t["match"])
        if t.get("rule") == "header_city_date":
            for f in [x for x in dt.fields if x.endswith((".data", ".miejscowosc"))]:
                evidence.setdefault(f, t["match"])
    for d in dt.raw.get("derive") or []:
        if d["source"] in evidence:
            evidence.setdefault(d["target"], evidence[d["source"]])
    rule_fields = set(rule_values) | set(fill_applied)
    enums = _enum_values(dt.schema)
    for path, value in _leaves(result):
        if value is None:
            continue
        g = generic(path)
        kind = dt.fields.get(g, "text")
        if g in derived:
            source = "derived"
        elif g in rule_fields:
            source = "rule"
        else:
            source = "llm"
        page_no, rects = None, []
        if pdoc is not None and not isinstance(value, bool):
            for p in doc.pages:
                if p.is_scan:
                    continue
                page = pdoc[p.number - 1]
                for var in (variants(kind, value) if kind not in ("int01", "int") else []):
                    hits = page.search_for(var)
                    if hits:
                        page_no, rects = p.number, [[round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)] for r in hits[:4]]
                        break
                if rects:
                    break
            if not rects and g in evidence:      # wartosc nie wystepuje doslownie - pokaz zdanie zrodlowe
                snippet = " ".join(re.sub(r"\s+", " ", evidence[g]).split()[:5])
                for p in doc.pages:
                    if p.is_scan:
                        continue
                    hits = pdoc[p.number - 1].search_for(snippet)
                    if hits:
                        page_no, rects = p.number, [[round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)] for r in hits[:2]]
                        break
        found = bool(rects) or any(fold(v) in text_folded for v in variants(kind, value) if len(str(v)) > 2)
        if source in ("rule", "derived"):
            confidence = "high"
        elif kind in ("int01", "int") or value in enums:
            confidence = "medium"          # decyzja modelu (np. wartosc ze slownika), nie da sie wskazac w tekscie
        else:
            confidence = "medium" if found else "low"
        out.append({"path": path, "value": value, "source": source, "page": page_no, "rects": rects,
                    "found": found, "confidence": confidence})
    if pdoc is not None:
        pdoc.close()
    return {"fields": out, "pages": pages}


def _enum_values(schema) -> set:
    """Wartosci slownikowe ze schematu (np. osoba_prawna): model je wybiera, w tekscie ich nie ma."""
    out = set()
    if isinstance(schema, dict):
        out |= {v for v in schema.get("enum", []) if isinstance(v, str)}
        for v in schema.values():
            out |= _enum_values(v)
    elif isinstance(schema, list):
        for v in schema:
            out |= _enum_values(v)
    return out
