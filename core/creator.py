"""Kreator nowej klasy dokumentow: z przykladowego JSON i kilku PDF-ow tworzy schemat, prompt i konfiguracje.

Wynik to te same trzy pliki, ktore mozna napisac recznie (schemas/, prompts/, configs/extra/), wiec
klasa dodana w kreatorze dziala identycznie w CLI i w GUI.
"""
import copy
import re
from collections import Counter
from pathlib import Path

import yaml

from . import pdf
from .classify import compact
from .config import ROOT, DocType

SLUG = re.compile(r"^[a-z][a-z0-9_]{1,40}$")

# typ pola zgadywany z nazwy klucza (kolejnosc ma znaczenie)
KEY_HINTS = [
    (r"pesel", "pesel"), (r"\bnip\b|_nip|nip_", "nip"), (r"\bkrs\b|_krs|krs_", "krs"), (r"regon", "regon"),
    (r"rachun|iban|konto", "iban"), (r"mail", "email"), (r"data|dzien|termin", "date"),
    (r"kwota|suma|wartosc|brutto|netto|cena|oplata", "amount"),
    (r"imie|nazwisk|osoba|podpis", "person"), (r"nazwa|firma|podmiot", "org_name"),
]
TYPE_HINTS = {
    "date": "data w formacie YYYY-MM-DD", "amount": "liczba, bez waluty", "nip": "10 cyfr, bez kresek",
    "krs": "10 cyfr", "regon": "9 lub 14 cyfr", "pesel": "11 cyfr", "iban": "numer rachunku jak w dokumencie",
    "email": "adres e-mail", "person": "imię i nazwisko w mianowniku, bez tytułów",
    "org_name": "pełna nazwa jak w dokumencie, bez adresu", "int": "liczba całkowita", "text": "tekst jak w dokumencie",
}
STOP = set("""oraz przez które który która ktore ktory ktora jako jest będzie zgodnie także takze dnia roku
tego tych tym oraz lub albo jeżeli jezeli wraz także niniejszym strona stron które według wedlug pozycja razem
zł pln data numer kwota nazwa adres""".split())


def _guess_kind(key: str, value) -> str:
    k = key.lower()
    for pat, kind in KEY_HINTS:
        if re.search(pat, k):
            return kind
    if isinstance(value, bool):
        return "text"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "amount"
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return "date"
    return "text"


def schema_from_example(example):
    """JSON Schema z przykladu: wszystkie pola wymagane, wartosci moga byc null, brak dodatkowych pol."""
    if isinstance(example, dict):
        return {"type": "object", "additionalProperties": False, "required": list(example),
                "properties": {k: schema_from_example(v) for k, v in example.items()}}
    if isinstance(example, list):
        merged = {}
        for item in example:
            if isinstance(item, dict):
                for k, v in item.items():
                    merged.setdefault(k, v)
        item_schema = schema_from_example(merged) if merged else {"type": ["string", "null"]}
        return {"type": "array", "items": item_schema}
    if isinstance(example, bool):
        return {"type": ["boolean", "null"]}
    if isinstance(example, int):
        return {"type": ["integer", "null"]}
    if isinstance(example, float):
        return {"type": ["number", "null"]}
    return {"type": ["string", "null"]}


def fields_from_example(example, path=""):
    """Sciezki lisci ('a.b', 'lista[].c') z odgadnietym typem."""
    out = {}
    if isinstance(example, dict):
        for k, v in example.items():
            p = f"{path}.{k}" if path else k
            if isinstance(v, (dict, list)):
                out.update(fields_from_example(v, p))
            else:
                out[p] = _guess_kind(k, v)
    elif isinstance(example, list):
        merged = {}
        for item in example:
            if isinstance(item, dict):
                for k, v in item.items():
                    merged.setdefault(k, v)
        out.update(fields_from_example(merged, path + "[]"))
    return out


def _words(text):
    return set(w for w in re.findall(r"[a-ząćęłńóśźż]{5,}", text.lower()) if w not in STOP)


def keywords_from_samples(texts, other_types):
    """Naglowek (pierwsza wspolna linia) + slowa obecne we wszystkich probkach, a nieuzywane przez inne klasy."""
    taken = set()
    for t in other_types.values():
        cl = t.raw.get("classify") or {}
        for group in ("title", "keywords"):
            taken |= {compact(k) for k in (cl.get(group) or {})}
    # naglowek: pierwsze slowo pierwszej sensownej linii, wspolne dla probek
    firsts = Counter()
    for t in texts:
        for line in t.splitlines():
            ws = re.findall(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{4,}", line)
            if ws:
                firsts[ws[0].lower()] += 1
                break
    title = {}
    if firsts:
        word, n = firsts.most_common(1)[0]
        if n == len(texts) and compact(word) not in taken:
            title[word] = 6
    common = set.intersection(*(_words(t) for t in texts)) if texts else set()
    freq = Counter(w for t in texts for w in re.findall(r"[a-ząćęłńóśźż]{5,}", t.lower()) if w in common)
    keywords = {}
    for w, _ in freq.most_common(40):
        if compact(w) in taken or w in title:
            continue
        keywords[w] = 2
        if len(keywords) == 8:
            break
    return title, keywords


def _example_value(example, path):
    node = example
    for part in path.split("."):
        lst = part.endswith("[]")
        key = part[:-2] if lst else part
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
        if lst:
            node = next((x for x in node if isinstance(x, dict)), None) if isinstance(node, list) else None
    return node


LABEL_KINDS = {"date": "date", "amount": "amount", "iban": "iban", "nip": "nip", "krs": "krs", "regon": "regon",
               "pesel": "pesel", "text": "text", "org_name": "text", "person": "text"}


def learn_label_rules(example, fields, texts):
    """Uczenie regul z przykladu: jesli wartosc z JSON stoi w PDF po etykiecie ('Data wystawienia: ...'),
    zapamietaj te etykiete. Takie pola dzialaja potem bez modelu i sa w GUI oznaczone jako 'regula'."""
    from .locate import variants
    learned = {}
    for path, kind in fields.items():
        value = _example_value(example, path)
        if value is None or kind not in LABEL_KINDS or (isinstance(value, str) and len(value) > 80):
            continue
        for text in texts:
            for line in text.splitlines():
                for var in variants(kind, value):
                    i = line.find(str(var))
                    if i <= 0:
                        continue
                    label = line[:i].strip(" \t:.-|")
                    if 3 <= len(label) <= 40 and re.search(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{3}", label) \
                            and not re.search(r"\d{3}", label):
                        learned[path] = {"type": LABEL_KINDS[kind], "labels": [label]}
                    break
                if path in learned:
                    break
            if path in learned:
                break
    # loose: etykieta wyuczona z przykladu moze stac tuz przed wartoscia, bez dwukropka
    return [{"extractor": "labels", "loose": True, "fields": learned}] if learned else []


def build_prompt(description, fields):
    lines = [f"Dokument: {description}. Wyodrębnij dane do JSON.", "", "Zasady pól:"]
    for path, kind in fields.items():
        lines.append(f"- {path}: {TYPE_HINTS.get(kind, 'tekst')}.")
    lines += ["", "Brak informacji = null. Nie wymyślaj danych. Zwróć wyłącznie JSON.", "", "TEKST DOKUMENTU:", "{text}"]
    return "\n".join(lines)


def draft(name, description, example, pdf_paths, config):
    """Szkic nowej klasy (nic nie zapisuje na dysku)."""
    if not SLUG.match(name or ""):
        raise ValueError("Nazwa: małe litery, cyfry i _, np. faktura albo wezwanie_kio")
    if name in config.types and not (ROOT / "configs" / "extra" / f"{name}.yaml").exists():
        raise ValueError(f"Typ '{name}' jest wbudowany, wybierz inną nazwę")
    if not isinstance(example, dict) or not example:
        raise ValueError("Przykładowy JSON musi być obiektem z co najmniej jednym polem")
    texts = []
    for p in pdf_paths:
        d = pdf.load(p, 3)
        texts.append(d.plain)
    others = {n: t for n, t in config.types.items() if n != name}
    title, keywords = keywords_from_samples([t for t in texts if t.strip()], others) if texts else ({}, {})
    fields = fields_from_example(example)
    rules = learn_label_rules(example, fields, texts)
    return {
        "name": name, "description": description or name,
        "schema": schema_from_example(example), "fields": fields,
        "classify": {"title": title, "keywords": keywords, "negative": {}, "min_score": 6},
        "prompt": build_prompt(description or name, fields), "llm": "always", "rules": rules,
    }


def as_doctype(d):
    raw = {"description": d["description"], "llm": d.get("llm", "always"), "classify": d["classify"],
           "rules": d.get("rules") or [], "fields": d["fields"]}
    return DocType(name=d["name"], raw=raw, schema=d["schema"], prompt=d["prompt"], fields=d["fields"])


def test_draft(d, pdf_paths, config, extractor_cls):
    """Uruchamia pelny pipeline z nowa klasa (w pamieci) na przykladowych PDF-ach."""
    cfg = copy.copy(config)
    cfg.types = dict(config.types)
    cfg.types[d["name"]] = as_doctype(d)
    ex = extractor_cls(cfg)
    results = []
    for p in pdf_paths:
        r = ex.process(p)
        results.append({"file": Path(p).name, "type": r["type"],
                        "scores": r["trace"]["classification"]["scores"], "result": r["result"],
                        "warnings": r["trace"]["warnings"]})
    return results


def save(d):
    """Zapisuje klase jako 3 pliki - tak samo, jak gdyby napisal je czlowiek."""
    name = d["name"]
    if not SLUG.match(name):
        raise ValueError("Niepoprawna nazwa typu")
    import json
    (ROOT / "schemas" / f"{name}.schema.json").write_text(
        json.dumps(d["schema"], ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "prompts" / f"{name}.txt").write_text(d["prompt"], encoding="utf-8")
    cfg = {"document_types": {name: {
        "enabled": True, "description": d["description"],
        "schema": f"schemas/{name}.schema.json", "prompt": f"prompts/{name}.txt",
        "llm": d.get("llm", "always"), "classify": d["classify"], "rules": d.get("rules") or [], "fields": d["fields"],
        "created_by": "kreator GUI"}}}
    path = ROOT / "configs" / "extra" / f"{name}.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text("# Klasa utworzona w kreatorze GUI. Mozna ja edytowac recznie.\n"
                    + yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return [f"schemas/{name}.schema.json", f"prompts/{name}.txt", f"configs/extra/{name}.yaml"]


def list_types(config):
    out = []
    extra_dir = ROOT / "configs" / "extra"
    extra = {}
    for f in sorted(extra_dir.glob("*.yaml")):
        for n, t in ((yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("document_types") or {}).items():
            extra[n] = (f, t.get("enabled", True), t.get("description", n))
    for n, t in config.types.items():
        if n not in extra:
            out.append({"name": n, "description": t.raw.get("description", n), "builtin": True, "enabled": True})
    for n, (f, en, desc) in extra.items():
        out.append({"name": n, "description": desc, "builtin": False, "enabled": bool(en), "file": f.name})
    return out


def set_enabled(name, enabled):
    f = ROOT / "configs" / "extra" / f"{name}.yaml"
    if not SLUG.match(name):
        raise ValueError("Niepoprawna nazwa")
    if not f.exists():
        for g in (ROOT / "configs" / "extra").glob("*.yaml"):
            if name in ((yaml.safe_load(g.read_text(encoding="utf-8")) or {}).get("document_types") or {}):
                f = g
                break
        else:
            raise ValueError("Nie znaleziono typu w configs/extra")
    text = f.read_text(encoding="utf-8")
    new, n = re.subn(r"(?m)^(\s*enabled:\s*)(true|false)", rf"\g<1>{'true' if enabled else 'false'}", text, count=1)
    f.write_text(new if n else text, encoding="utf-8")


# --- usuwanie do archiwum i przywracanie (nic nie jest kasowane na zawsze) ---
ARCHIVE = ROOT / "configs" / "archiwum"


def _extra_file(name):
    for g in (ROOT / "configs" / "extra").glob("*.yaml"):
        types = (yaml.safe_load(g.read_text(encoding="utf-8")) or {}).get("document_types") or {}
        if name in types:
            return g, types[name]
    raise ValueError("Można usuwać tylko typy dodane konfiguracją (configs/extra)")


def archive(name):
    """Przenosi YAML, schemat i prompt typu do configs/archiwum/<nazwa>_<data>/."""
    import datetime
    import shutil
    if not SLUG.match(name):
        raise ValueError("Niepoprawna nazwa")
    cfg_file, t = _extra_file(name)
    dest = ARCHIVE / f"{name}_{datetime.datetime.now():%Y%m%d_%H%M%S}"
    dest.mkdir(parents=True)
    for rel in (t.get("schema"), t.get("prompt")):
        if rel and (ROOT / rel).exists():
            shutil.move(str(ROOT / rel), str(dest / Path(rel).name))
    shutil.move(str(cfg_file), str(dest / cfg_file.name))
    return dest.name


def list_archived():
    out = []
    for d in sorted(ARCHIVE.glob("*/"), reverse=True):
        for y in d.glob("*.yaml"):
            types = (yaml.safe_load(y.read_text(encoding="utf-8")) or {}).get("document_types") or {}
            for n, t in types.items():
                out.append({"id": d.name, "name": n, "description": t.get("description", n)})
    return out


def restore(archive_id):
    import shutil
    if not re.fullmatch(r"[a-z0-9_]+", archive_id):
        raise ValueError("Niepoprawny identyfikator archiwum")
    src = ARCHIVE / archive_id
    if not src.is_dir():
        raise ValueError("Nie ma takiej pozycji w archiwum")
    y = next(src.glob("*.yaml"))
    types = (yaml.safe_load(y.read_text(encoding="utf-8")) or {}).get("document_types") or {}
    for n, t in types.items():
        if (ROOT / "configs" / "extra" / y.name).exists():
            raise ValueError(f"Typ '{n}' już istnieje - usuń go najpierw")
        for rel in (t.get("schema"), t.get("prompt")):
            if rel and (src / Path(rel).name).exists():
                shutil.move(str(src / Path(rel).name), str(ROOT / rel))
    shutil.move(str(y), str(ROOT / "configs" / "extra" / y.name))
    src.rmdir() if not any(src.iterdir()) else None
    return list(types)


# --- edycja istniejacego typu (dodawanie / usuwanie pol) ---
def load_for_edit(name, config):
    """Konfiguracja typu dodanego konfiguracja w formacie szkicu kreatora."""
    _extra_file(name)                       # tylko typy z configs/extra
    t = config.types.get(name)
    if t is None:
        raise ValueError("Typ jest wyłączony - włącz go, żeby edytować")
    raw = t.raw
    return {"name": name, "description": raw.get("description", name), "schema": copy.deepcopy(t.schema),
            "fields": dict(t.fields), "classify": copy.deepcopy(raw.get("classify") or {}),
            "prompt": t.prompt, "llm": raw.get("llm", "always"), "rules": copy.deepcopy(raw.get("rules") or []),
            "editing": True, "sample_files": []}


def _schema_node(schema, parts, create):
    """Zwraca schemat obiektu-rodzica dla sciezki ['a','b[]','c'] (tworzy brakujace obiekty)."""
    node = schema
    for part in parts:
        lst = part.endswith("[]")
        key = part[:-2] if lst else part
        props = node.setdefault("properties", {})
        if key not in props:
            if not create:
                return None
            props[key] = ({"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                      "required": [], "properties": {}}}
                          if lst else {"type": "object", "additionalProperties": False, "required": [], "properties": {}})
            node.setdefault("required", []).append(key)
        node = props[key]["items"] if lst else props[key]
    return node


JSON_TYPE = {"int": ["integer", "null"], "amount": ["number", "null"]}


def add_field(d, path, kind):
    path = path.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]*(\[\])?(\.[a-z][a-z0-9_]*(\[\])?)*", path) or path.endswith("[]"):
        raise ValueError("Ścieżka pola: małe litery, cyfry i _, kropka dla zagnieżdżenia, np. termin_platnosci albo nabywca.adres")
    if path in d["fields"]:
        raise ValueError(f"Pole '{path}' już istnieje")
    parts = path.split(".")
    parent = _schema_node(d["schema"], parts[:-1], create=True)
    leaf = parts[-1]
    parent.setdefault("properties", {})[leaf] = {"type": JSON_TYPE.get(kind, ["string", "null"])}
    req = parent.setdefault("required", [])
    if leaf not in req:
        req.append(leaf)
    d["fields"][path] = kind
    line = f"- {path}: {TYPE_HINTS.get(kind, 'tekst')}."
    marker = "\n\nBrak informacji"
    d["prompt"] = d["prompt"].replace(marker, "\n" + line + marker, 1) if marker in d["prompt"] else d["prompt"] + "\n" + line
    return d


def remove_field(d, path):
    if path not in d["fields"]:
        raise ValueError(f"Nie ma pola '{path}'")
    parts = path.split(".")
    parent = _schema_node(d["schema"], parts[:-1], create=False)
    if parent is not None:
        parent.get("properties", {}).pop(parts[-1], None)
        if parts[-1] in parent.get("required", []):
            parent["required"].remove(parts[-1])
    d["fields"].pop(path)
    d["prompt"] = "\n".join(l for l in d["prompt"].splitlines() if not l.startswith(f"- {path}:"))
    for r in d.get("rules") or []:
        (r.get("fields") or {}).pop(path, None)
    d["rules"] = [r for r in d.get("rules") or [] if r.get("fields") or r.get("extractor") != "labels"]
    return d


def archive_copy(name):
    """Kopia aktualnej wersji typu do archiwum przed nadpisaniem (wersjonowanie)."""
    import datetime
    import shutil
    try:
        cfg_file, t = _extra_file(name)
    except ValueError:
        return None
    dest = ARCHIVE / f"{name}_{datetime.datetime.now():%Y%m%d_%H%M%S}_poprzednia_wersja"
    dest.mkdir(parents=True)
    for rel in (t.get("schema"), t.get("prompt")):
        if rel and (ROOT / rel).exists():
            shutil.copy2(str(ROOT / rel), str(dest / Path(rel).name))
    shutil.copy2(str(cfg_file), str(dest / cfg_file.name))
    return dest.name
