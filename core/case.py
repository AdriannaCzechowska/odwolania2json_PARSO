"""Sprawa = kilka dokumentow (odwolanie, pelnomocnictwo, przelew). Sprawdzenia spojnosci miedzy nimi
definiuje configs/case_checks.yaml. Wynik sluzy czlowiekowi w GUI i nie zmienia plikow JSON."""
import re
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from . import paths

ROOT = Path(__file__).resolve().parent.parent
CHECKS_FILE = ROOT / "configs" / "case_checks.yaml"


def load_checks(path=CHECKS_FILE):
    if not Path(path).exists():
        return []
    return (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("checks") or []


def _values(docs, spec):
    doc_type, field = spec.split(":", 1)
    out = []
    for d in docs:
        if d.get("type") == doc_type:
            out += [v for _, _, v in paths.iter_values(d.get("result") or {}, field) if v not in (None, "")]
    return doc_type, out


def _norm(s):
    return " ".join(str(s).lower().split())


def _alnum(s):
    return re.sub(r"[^0-9a-ząćęłńóśźż]", "", str(s).lower())


def _match(op, a, b):
    if op == "same_person":
        return fuzz.token_sort_ratio(_norm(a), _norm(b)) >= 90
    if op == "same_number":
        da, db = re.sub(r"\D", "", str(a)), re.sub(r"\D", "", str(b))
        return bool(da) and da == db
    if op == "same_name":
        return fuzz.token_set_ratio(_norm(a), _norm(b)) >= 85
    if op == "contained":
        na = _alnum(a)
        return len(na) >= 3 and na in _alnum(b)
    raise ValueError(f"nieznana operacja sprawdzenia: {op}")


def _per_doc(docs, spec):
    doc_type, field = spec.split(":", 1)
    out = []
    for i, d in enumerate(docs):
        if d.get("type") == doc_type:
            vals = [v for _, _, v in paths.iter_values(d.get("result") or {}, field) if v not in (None, "")]
            name = d.get("filename") or "dokument"
            if sum(1 for x in docs if x.get("filename") == name) > 1:
                name += f" (plik nr {i + 1})"
            out.append((name, vals))
    return out


def run_checks(docs, checks=None):
    """docs: [{"type": ..., "result": {...}, "filename": ...}]. Zwraca liste {name, status, left, right, detail}.
    status: ok | blad | brak (brak dokumentu albo wartosci).
    Kazdy dokument po obu stronach musi pasowac do drugiej strony: gdy wczytano np. dwa pelnomocnictwa
    z roznych spraw, to niepasujace zostanie wskazane z nazwy pliku."""
    out = []
    present = {d.get("type") for d in docs}
    for c in checks if checks is not None else load_checks():
        lt, left = _values(docs, c["left"])
        rt, right = _values(docs, c["right"])
        item = {"name": c["name"], "left": left, "right": right, "left_type": lt, "right_type": rt}
        missing = [t for t in (lt, rt) if t not in present]
        if missing:
            item.update(status="brak", detail="Brak dokumentu: " + ", ".join(sorted(set(missing))))
            out.append(item)
            continue
        if not left or not right:
            item.update(status="brak", detail="Brak wartości do porównania")
            out.append(item)
            continue
        bad = []
        for fname, vals in _per_doc(docs, c["left"]):
            if vals and not any(_match(c["op"], a, b) for a in vals for b in right):
                bad.append(fname)
        for fname, vals in _per_doc(docs, c["right"]):
            if vals and not any(_match(c["op"], a, b) for a in left for b in vals):
                bad.append(fname)
        if not any(_match(c["op"], a, b) for a in left for b in right):
            item.update(status="blad", detail="Niezgodne, sprawdź dokumenty")
        elif bad:
            item.update(status="blad", detail="Niezgodne: " + ", ".join(dict.fromkeys(bad)) +
                        "; sprawdź, czy wszystkie dokumenty są z tej samej sprawy")
        else:
            item.update(status="ok", detail="Zgodne")
        out.append(item)
    return out
