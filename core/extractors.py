"""Ekstraktory deterministyczne. Wybierane w YAML po nazwie (rejestr EXTRACTORS)."""
import re

from .normalize import NORMALIZERS, MONTHS, parse_date

_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
_CITY_DATE = re.compile(
    rf"^\s*([A-ZĄĆĘŁŃÓŚŹŻ][A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż\-]+(?:[ \-][A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż\-]+){{0,2}})"
    rf"\s*,?\s*(?:dnia|dn\.|z\s+dnia)?\s*"
    rf"(\d{{1,2}}\s*(?:[.\-/]\s*\d{{1,2}}\s*[.\-/]|\s+(?:{_MONTH_RE})\s+)\s*20\d\d)",
    re.M,
)
_SEPARATOR = re.compile(r"^[\s\-=_*·.]{5,}$")


def header_city_date(doc, rule, trace):
    """Linia 'Miejscowosc, dnia DD miesiaca RRRR' z pierwszej strony."""
    text = doc.pages[0].text if doc.pages else ""
    out = {}
    for m in _CITY_DATE.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        if re.search(r"\d{2}-\d{3}\s*$", text[line_start:m.start()]):
            continue  # kod pocztowy przed nazwa - to adres
        city = m.group(1).strip()
        if city.lower() in ("dnia", "data", "warszawa dnia"):
            continue
        out[rule["fields"]["city"]] = city
        out[rule["fields"]["date"]] = parse_date(m.group(2))
        trace.append({"rule": "header_city_date", "match": m.group(0).strip(), "page": 1})
        break
    return out


def regex(doc, rule, trace):
    text = doc.plain
    norm = NORMALIZERS.get(rule.get("type", "text"), lambda v: v)
    for pat in rule["patterns"]:
        m = re.search(pat, text, re.I)
        if m:
            val = norm(m.group(1))
            if val is not None:
                trace.append({"rule": "regex", "field": rule["field"], "match": m.group(0)[:120]})
                return {rule["field"]: val}
    return {}


def _norm_label(s):
    return re.sub(r"\s+", " ", s.strip().lower())


def labels(doc, rule, trace):
    """Pola oznaczone etykieta: wartosc w tej samej linii albo w nastepnych."""
    lines = [ln.rstrip() for ln in doc.plain.splitlines()]
    all_labels = []
    for field, spec in rule["fields"].items():
        all_labels += [(_norm_label(lb), field) for lb in spec["labels"]]
    all_labels += [(_norm_label(lb), None) for lb in rule.get("stop_labels", [])]
    all_labels.sort(key=lambda x: -len(x[0]))

    def match_label(line):
        """Etykieta = poczatek linii + koniec linii / ':' / kropki / 2+ spacje / linia wersalikami."""
        raw = line.strip()
        low = _norm_label(raw)
        for lb, field in all_labels:
            if not low.startswith(lb):
                continue
            m = re.match(r"\s+".join(map(re.escape, lb.split())), raw, re.I)
            rest = raw[m.end():] if m else ""
            if rest == "" or re.match(r"^\s*[:.·|]", rest) or re.match(r"^\s{2,}", rest) \
                    or (rule.get("loose") and field is not None) \
                    or (raw[:len(lb)].isupper() and not rest[:1].isalpha()):
                return lb, field
        return None, None

    out, rank = {}, {}
    for i, line in enumerate(lines):
        lb, field = match_label(line)
        if not field:
            continue
        r = [_norm_label(x) for x in rule["fields"][field]["labels"]].index(lb)
        if field in out and rank[field] <= r:
            continue
        spec = rule["fields"][field]
        kind = spec["type"]
        m = re.match(r"\s+".join(map(re.escape, lb.split())), line.strip(), re.I)
        value = re.sub(r"^[\s.:·\-–|]+", "", line.strip()[m.end():]).strip()
        following = []
        for nxt in lines[i + 1:i + 6]:
            if not nxt.strip() or _SEPARATOR.match(nxt) or match_label(nxt)[0]:
                break
            following.append(nxt.strip())
        if kind == "multiline":
            parts = ([value] if value else []) + following
            raw = " ".join(parts) if parts else None
        elif kind == "iban":
            cand = " ".join([value] + following[:2])
            m = re.search(r"(?:PL)?\s*(\d{2}(?:\s?\d{4}){6})", cand.replace("\xa0", " "))
            raw = m.group(1) if m else None
        elif kind == "ref":
            cand = value or (following[0] if following else "")
            m = re.search(r"[A-Z0-9][A-Z0-9/\-]{5,}", cand)
            raw = m.group(0) if m else None
        else:
            raw = value or (following[0] if following else None)
        val = NORMALIZERS.get(kind, lambda v: v)(raw) if raw else None
        if val is not None:
            out[field], rank[field] = val, r
            trace.append({"rule": "labels", "field": field, "label": lb, "line": i + 1})
    return out


def sentence_classifier(doc, rule, trace):
    """Zdanie wg wzorca (np. 'Zamawiajacy w dniu ...') -> kod z listy slow kluczowych + data z tego zdania.
    Bierze pierwsze zdanie, dla ktorego pasuje jakikolwiek kod (kolejnosc kodow = priorytet)."""
    text = re.sub(r"\s+", " ", doc.plain)
    for m in re.finditer(rule["sentence"], text):  # bez re.I: koniec zdania = kropka + WIELKA litera
        sent = m.group(0)
        for code, pattern in rule["codes"]:
            if re.search(pattern, sent, re.I):
                out = {rule["code_field"]: code}
                if rule.get("date_field"):
                    out[rule["date_field"]] = parse_date(sent)
                trace.append({"rule": "sentence_classifier", "field": rule["code_field"], "code": code,
                              "match": sent[:160]})
                return out
    return {}


EXTRACTORS = {"sentence_classifier": sentence_classifier, "header_city_date": header_city_date, "regex": regex, "labels": labels}


def run_rules(doc, doctype, trace):
    """Zwraca (wartosci nadrzedne nad LLM, wartosci tylko do uzupelnienia pustych pol)."""
    values, fill = {}, {}
    for rule in doctype.raw.get("rules") or []:
        fn = EXTRACTORS.get(rule["extractor"])
        if fn is None:
            raise ValueError(f"Nieznany ekstraktor: {rule['extractor']}")
        target = fill if rule.get("fill_only") else values
        for k, v in fn(doc, rule, trace).items():
            if v is not None and k not in target:
                target[k] = v
    return values, fill
