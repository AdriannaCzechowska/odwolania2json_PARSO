"""Klasyfikacja regulowa: punktacja slow kluczowych z YAML."""
import re

_WS = re.compile(r"\s+")


def compact(text: str) -> str:
    """Male litery bez bialych znakow - lapie tez 'P E Ł N O M O C N I C T W O'."""
    return _WS.sub("", text.lower())


def score_type(ctext: str, rules: dict, head_len: int = 1500) -> tuple[float, list]:
    head = ctext[:head_len]
    score, hits = 0.0, []
    for kw, w in (rules.get("title") or {}).items():
        if compact(kw) in head:
            score += w
            hits.append(f"+{w} naglowek:{kw}")
    for kw, w in (rules.get("keywords") or {}).items():
        if compact(kw) in ctext:
            score += w
            hits.append(f"+{w} {kw}")
    for kw, w in (rules.get("negative") or {}).items():   # tylko naglowek: tresc moze cytowac wyroki itp.
        if compact(kw) in head:
            score -= w
            hits.append(f"-{w} {kw}")
    return score, hits


def classify(text: str, config) -> dict:
    settings = config.settings.get("classification", {})
    ctext = compact(text[: settings.get("scan_chars", 4000)])
    scores = {}
    for name, t in config.types.items():
        scores[name] = score_type(ctext, t.raw.get("classify") or {})
    best = max(scores, key=lambda n: scores[n][0]) if scores else None
    best_score = scores[best][0] if best else 0
    threshold = (config.types[best].raw.get("classify") or {}).get("min_score", settings.get("min_score", 3)) if best else 0
    label = best if best and best_score >= threshold else None
    return {
        "label": label,
        "scores": {n: s for n, (s, _) in scores.items()},
        "hits": scores[best][1] if best else [],
    }
