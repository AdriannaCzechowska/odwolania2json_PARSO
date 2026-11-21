"""Pipeline: PDF -> (OCR) -> klasyfikacja -> reguly -> LLM -> normalizacja -> walidacja."""
import copy
import hashlib
import time
from pathlib import Path

import jsonschema

from . import cache, paths, pdf
from .classify import classify
from .config import load_config
from .extractors import run_rules
from .llm import LLM, BudgetExceeded, LLMUnavailable
from .normalize import GROUNDED, NORMALIZERS, digit_runs, fix_place, grounded

PIPELINE_VERSION = "1"


def conform(value, schema):
    """Doprowadza dane do ksztaltu schematu: usuwa obce pola, dodaje brakujace (null/[])."""
    t = schema.get("type")
    types = t if isinstance(t, list) else [t]
    if "object" in types:
        src = value if isinstance(value, dict) else {}
        return {k: conform(src.get(k), sub) for k, sub in schema.get("properties", {}).items()}
    if "array" in types:
        if not isinstance(value, list):
            return []
        items = [conform(v, schema.get("items", {})) for v in value]
        return [i for i in items if i not in (None, {}) and not _all_null(i)]
    return value


def _iban_as_in_document(digits26, compact_src):
    """Rachunek w formie z dokumentu: 'PL' + 26 cyfr, jesli w dokumencie stoi z prefiksem PL (decyzja UZP)."""
    return "PL" + digits26 if ("PL" + digits26) in compact_src else digits26


def _restore_iban(value, runs):
    """Jesli model zwrocil niepelny rachunek (np. 24 cyfry), odtworz 26 cyfr z tekstu dokumentu."""
    d = "".join(ch for ch in str(value) if ch.isdigit())
    if 16 <= len(d) < 26:
        for run, _ in runs:
            if len(run) >= 26 and run[-26:].endswith(d):
                return run[-26:]
    return value


def _fill_missing(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            if _all_null(dst[k]):
                dst[k] = v
            else:
                _fill_missing(dst[k], v)
        elif dst.get(k) is None and v is not None and k in ("przez-pelnomocnika",):
            dst[k] = v


def _all_null(v):
    if isinstance(v, dict):
        return all(_all_null(x) for x in v.values())
    if isinstance(v, list):
        return all(_all_null(x) for x in v)
    return v is None


class Extractor:
    def __init__(self, config=None):
        self.config = config or load_config()
        self.llm = LLM(self.config.settings.get("llm", {}))

    # ---------- OCR ----------
    def _ocr(self, doc, trace):
        ps = self.config.settings.get("pdf", {})
        for page in doc.pages:
            if not page.is_scan:
                continue
            if not self.llm.available:
                trace["warnings"].append(f"strona {page.number}: skan, brak LLM do OCR")
                continue
            best = ""
            for rotate in ps.get("ocr_rotations", [0, 180, 90, 270]):
                img = pdf.render_png_b64(doc.path, page.number, ps.get("ocr_dpi", 150), rotate)
                text = self.llm.transcribe_image(img)
                if pdf.text_quality_ok(text, ps.get("min_chars_per_page", 60)):
                    best = text
                    trace["ocr"].append({"page": page.number, "rotate": rotate, "chars": len(text)})
                    break
                best = best or text
            page.text, page.source = best, "ocr"

    # ---------- glowna funkcja ----------
    def process(self, path: str | Path, with_provenance: bool = False) -> dict:
        t0 = time.time()
        path = str(path)
        sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        trace = {"file": Path(path).name, "sha256": sha, "pipeline": PIPELINE_VERSION,
                 "warnings": [], "ocr": [], "rules": [], "llm": None, "dropped": [], "validation": []}
        ps = self.config.settings.get("pdf", {})
        doc = pdf.load(path, ps.get("max_pages", 4), ps.get("min_chars_per_page", 60))
        trace["pages"] = doc.total_pages
        trace["scan_pages"] = [p.number for p in doc.pages if p.is_scan]
        if doc.has_scans:
            try:
                self._ocr(doc, trace)
            except Exception as e:  # OCR nie moze zatrzymac przetwarzania
                trace["warnings"].append(f"OCR: {type(e).__name__}: {str(e)[:200]}")

        cls = classify(doc.plain, self.config)
        trace["classification"] = cls
        if cls["label"] is None:
            trace["seconds"] = round(time.time() - t0, 2)
            return {"type": None, "result": copy.deepcopy(self.config.settings.get("unknown_output", {})),
                    "trace": trace, "text": doc.text}

        dt = self.config.types[cls["label"]]
        rule_values, fill_values = run_rules(doc, dt, trace["rules"])

        # --- LLM ---
        llm_data = None
        need_llm = dt.llm_mode == "always" or (
            dt.llm_mode == "fallback" and any((rule_values.get(f) if rule_values.get(f) is not None else fill_values.get(f)) is None
                                          for f in dt.raw.get("required", [])))
        if need_llm:
            prompt = dt.prompt.replace("{text}", doc.text)
            try:
                llm_data, res = self.llm.extract_json(prompt, dt.schema, dt.name)
                trace["llm"] = {"model": self.llm.model, "tokens_in": res.get("tokens_in"),
                                "tokens_out": res.get("tokens_out"), "parsed": llm_data is not None}
            except (LLMUnavailable, BudgetExceeded) as e:
                trace["warnings"].append(f"LLM pominiety: {e}")
            except Exception as e:  # blad API nie moze zatrzymac calego folderu
                trace["warnings"].append(f"LLM blad: {type(e).__name__}: {str(e)[:200]}")

        result = conform(llm_data or {}, dt.schema)
        for field, value in rule_values.items():     # reguly maja pierwszenstwo
            paths.set_first(result, field, value)
        fill_applied = []
        for field, value in fill_values.items():     # reguly "fill_only": tylko puste pola
            if paths.get(result, field) is None:
                paths.set_first(result, field, value)
                fill_applied.append(field)
        result = conform(result, dt.schema)

        opts = dt.raw.get("options", {})
        if opts.get("consortium") == "leader":
            for key in opts.get("consortium_lists", []):
                items = result.get(key)
                if isinstance(items, list) and len(items) > 1:
                    leader = items[0]
                    for other in items[1:]:      # puste pola lidera uzupelnij danymi z reszty (np. pelnomocnik)
                        _fill_missing(leader, other)
                    trace["dropped"].append({"field": key, "value": len(items) - 1, "reason": "konsorcjum: tylko lider"})
                    result[key] = [leader]
        # wspolne pola konsorcjum (np. pelnomocnik) kopiowane do czlonkow, ktorzy ich nie maja
        for key, fields in (opts.get("shared_fields") or {}).items():
            items = result.get(key) if isinstance(result.get(key), list) else []
            for f in fields:
                donor = next((it.get(f) for it in items if not _all_null(it.get(f))), None)
                if donor is None:
                    continue
                for it in items:
                    if _all_null(it.get(f)):
                        it[f] = copy.deepcopy(donor)

        self._normalize(result, dt, doc, trace)
        self._postprocess(result, dt, rule_values, trace)
        for d in dt.raw.get("derive") or []:
            mapping = self.config.dictionaries.get(d["map"], {})
            src = paths.get(result, d["source"])
            paths.set_first(result, d["target"], mapping.get(src) if src is not None else None)

        try:
            jsonschema.validate(result, dt.schema)
        except jsonschema.ValidationError as e:
            trace["validation"].append(f"{'/'.join(map(str, e.absolute_path))}: {e.message}")
        out = {"type": dt.name, "result": result, "trace": trace, "text": doc.text}
        if with_provenance:
            from .locate import provenance
            derived = {d["target"] for d in dt.raw.get("derive") or []}
            # pole pochodne od wartosci z reguly tez jest "z reguly"
            derived_rule = {d["target"] for d in dt.raw.get("derive") or [] if d["source"] in rule_values}
            out["provenance"] = provenance(path, doc, result, dt, rule_values, fill_applied,
                                           derived - derived_rule, trace["rules"])
            for f in out["provenance"]["fields"]:
                if f["path"] in derived_rule or any(f["path"] == t for t in derived_rule):
                    f["source"], f["confidence"] = "rule", "high"
        trace["seconds"] = round(time.time() - t0, 2)
        return out

    def _normalize(self, result, dt, doc, trace):
        runs = digit_runs(doc.plain)
        src_lower = doc.plain.lower()
        compact_src = "".join(doc.plain.split()).upper()
        for field, kind in dt.fields.items():
            norm = NORMALIZERS.get(kind)
            if not norm:
                continue
            for container, key, value in paths.iter_values(result, field):
                if kind == "iban" and value is not None:
                    value = _restore_iban(value, runs)   # model czasem ucina cyfry kontrolne po "PL"
                new = norm(value) if value is not None else None
                if kind == "place" and new is not None:
                    new = fix_place(new, doc.plain)
                if kind == "iban" and new is not None and dt.raw.get("options", {}).get("iban_prefix", True):
                    new = _iban_as_in_document(new, compact_src)
                if kind in GROUNDED and new is not None and not grounded(kind, new, runs, src_lower):
                    trace["dropped"].append({"field": field, "value": new, "reason": "brak w tekscie"})
                    new = None
                container[key] = new

    def _postprocess(self, result, dt, rule_values, trace):
        """Ogolne reguly porzadkowe z sekcji 'postprocess' w YAML."""
        pp = dt.raw.get("postprocess") or {}
        # pola wiarygodne tylko z reguly (np. data z naglowka): brak dopasowania = null
        for field in pp.get("rule_only", []):
            if field not in rule_values:
                for container, key, value in paths.iter_values(result, field):
                    if value is not None:
                        trace["dropped"].append({"field": field, "value": value, "reason": "tylko z reguly"})
                    container[key] = None
        # usuwanie duplikatow na listach (ten sam podmiot zwrocony kilka razy)
        for lst, keys in (pp.get("dedupe") or {}).items():
            items, seen, out = result.get(lst) or [], set(), []
            for it in items:
                sig = tuple((str(it.get(k) or "")).lower() for k in keys)
                if any(sig) and sig in seen:
                    trace["dropped"].append({"field": lst, "value": sig, "reason": "duplikat"})
                    continue
                seen.add(sig)
                out.append(it)
            result[lst] = out
        # pole ma sens tylko przy kilku elementach listy (np. prowadzacy_postepowanie)
        for rule in pp.get("null_if_single", []):
            items = result.get(rule["list"]) or []
            if len(items) <= 1:
                for it in items:
                    it[rule["field"]] = None
