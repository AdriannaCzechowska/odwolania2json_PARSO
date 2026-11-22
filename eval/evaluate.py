"""Przyblizony evaluator F1 na danych treningowych UZP (to NIE jest oficjalny algorytm jury).

  python eval/evaluate.py --data ../hacknation-2026/dane [--split dev|val|all|skany|negatywne] [--offline]

Zasady (wg doprecyzowan organizatora): listy dopasowywane po tresci, dlugie stringi
(nazwy, tytuly) z progiem podobienstwa 80%, pola null-null pomijane.
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FUZZY_KEYS = {"nazwa", "tytul", "imie_nazwisko"}
IBAN_KEYS = {"z_rachunku", "na_rachunek"}   # UZP: brak "PL" w czesci wzorcow to blad wzorcow -> porownujemy cyfry
FUZZY_THRESHOLD = 80


def leaf_eq(key, g, p):
    if isinstance(g, (int, float)) and isinstance(p, (int, float)) and not isinstance(g, bool):
        return abs(float(g) - float(p)) < 0.005
    gs, ps = str(g).strip(), str(p).strip()
    if key in IBAN_KEYS:
        return "".join(c for c in gs if c.isdigit()) == "".join(c for c in ps if c.isdigit())
    if key in FUZZY_KEYS:
        return fuzz.ratio(gs.lower(), ps.lower()) >= FUZZY_THRESHOLD
    return gs == ps


def leaves(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for v in obj:
            yield from leaves(v, path + "[]")
    elif obj is not None:
        yield path, obj


def compare(g, p, path, stats):
    if isinstance(g, dict) or isinstance(p, dict):
        g, p = g if isinstance(g, dict) else {}, p if isinstance(p, dict) else {}
        for k in set(g) | set(p):
            compare(g.get(k), p.get(k), f"{path}.{k}" if path else k, stats)
        return
    if isinstance(g, list) or isinstance(p, list):
        g, p = g if isinstance(g, list) else [], p if isinstance(p, list) else []
        remaining = list(range(len(p)))
        for gi in g:
            best, best_s = None, -1
            for j in remaining:
                s = similarity(gi, p[j])
                if s > best_s:
                    best, best_s = j, s
            if best is not None and best_s > 0:
                remaining.remove(best)
                compare(gi, p[best], path + "[]", stats)
            else:
                for lp, _ in leaves(gi, path + "[]"):
                    stats["fn"][lp] += 1
        for j in remaining:
            for lp, _ in leaves(p[j], path + "[]"):
                stats["fp"][lp] += 1
        return
    key = path.split(".")[-1].rstrip("[]")
    if g is None and p is None:
        return
    if g is None:
        stats["fp"][path] += 1
    elif p is None:
        stats["fn"][path] += 1
    elif leaf_eq(key, g, p):
        stats["tp"][path] += 1
    else:
        stats["fp"][path] += 1
        stats["fn"][path] += 1
        stats["examples"][path].append((g, p))


def similarity(a, b):
    la, lb = dict(leaves(a)), dict(leaves(b))
    if not la:
        return 0
    return sum(1 for k, v in la.items() if k in lb and leaf_eq(k.split(".")[-1], v, lb[k])) / len(la)


def f1(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def build_index(data: Path, split: str):
    """Lista (pdf, gold_json lub {}, oczekiwany_typ)."""
    items = []
    name2type = {"odwolanie": "odwolanie", "pelnomocnictwo": "pelnomocnictwo",
                 "przelew": "przelew", "potwierdzenie_przelewu": "przelew"}
    for case in sorted(data.glob("przyklad_*")):
        n = int(case.name.split("_")[1])
        if split == "dev" and n > 45 or split == "val" and n <= 45 or split in ("skany", "negatywne"):
            continue
        jsons = {j.stem: j for j in case.glob("*.json")}
        for pdf_path in sorted(case.glob("*.pdf")):
            t = name2type.get(pdf_path.stem)
            gold_file = jsons.get(pdf_path.stem) or (jsons.get("przelew") if t == "przelew" else None)
            if t and gold_file:
                items.append((pdf_path, json.loads(gold_file.read_text(encoding="utf-8")), t))
            else:
                items.append((pdf_path, {}, None))           # negatyw wlozony do sprawy
    if split in ("all", "skany"):
        for folder, t in (("odwolania", "odwolanie"), ("pelnomocnictwa", "pelnomocnictwo"), ("potwierdzenia", "przelew")):
            for pdf_path in sorted((data / "skany" / folder).glob("*/*.pdf")):
                items.append((pdf_path, json.loads(pdf_path.with_suffix(".json").read_text(encoding="utf-8")), t))
    if split in ("all", "negatywne"):
        for pdf_path in sorted((data / "negatywne").glob("*.pdf")):
            items.append((pdf_path, {}, None))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="folder 'dane' z repo UZP")
    ap.add_argument("--split", default="dev", choices=["dev", "val", "all", "skany", "negatywne"])
    ap.add_argument("--offline", action="store_true", help="bez wywolan LLM (tylko reguly + cache)")
    ap.add_argument("--only", default=None, help="tylko typ: odwolanie|pelnomocnictwo|przelew")
    ap.add_argument("--show", type=int, default=3, help="ile przykladow bledow na pole")
    args = ap.parse_args()
    if args.offline:
        os.environ["LLM_OFFLINE"] = "1"
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from core.llm import USAGE
    from core.pipeline import Extractor

    ex = Extractor()
    print(f"Model: {ex.llm.model} (skany: {ex.llm.vision_model})", flush=True)
    items = build_index(Path(args.data), args.split)
    if args.only:
        items = [i for i in items if i[2] == args.only]
    per_type = defaultdict(lambda: {"tp": Counter(), "fp": Counter(), "fn": Counter(), "examples": defaultdict(list)})
    cls_ok, cls_bad = 0, []
    import time
    for i, (pdf_path, gold, t) in enumerate(items, 1):
        t0 = time.time()
        res = ex.process(pdf_path)
        print(f"[{i}/{len(items)}] {pdf_path.parent.name}/{pdf_path.name} -> {res['type']} ({time.time() - t0:.1f} s)", flush=True)
        if res["type"] == t:
            cls_ok += 1
        else:
            cls_bad.append((str(pdf_path.relative_to(args.data)), t, res["type"], res["trace"]["classification"]["scores"]))
        stats = per_type[t or "negatyw"]
        if gold == {} or res["result"] == {}:
            if gold != res["result"]:
                for lp, _ in leaves(gold):
                    stats["fn"][lp] += 1
                for lp, _ in leaves(res["result"]):
                    stats["fp"][lp] += 1
            continue
        compare(gold, res["result"], "", stats)

    print(f"\nKlasyfikacja: {cls_ok}/{len(items)} poprawnie")
    for f, t, got, sc in cls_bad:
        print(f"  BLAD {f}: oczekiwano {t}, jest {got}  {sc}")
    TP = FP = FN = 0
    for t, s in per_type.items():
        tp, fp, fn = sum(s["tp"].values()), sum(s["fp"].values()), sum(s["fn"].values())
        TP, FP, FN = TP + tp, FP + fp, FN + fn
        p, r, f = f1(tp, fp, fn)
        print(f"\n== {t}: P={p:.3f} R={r:.3f} F1={f:.3f}  (tp={tp} fp={fp} fn={fn})")
        fields = set(s["tp"]) | set(s["fp"]) | set(s["fn"])
        rows = sorted(fields, key=lambda k: -(s["fp"][k] + s["fn"][k]))
        for k in rows:
            errs = s["fp"][k] + s["fn"][k]
            if errs:
                print(f"   {k:55s} tp={s['tp'][k]:3d} fp={s['fp'][k]:3d} fn={s['fn'][k]:3d}")
                for g, pv in s["examples"][k][: args.show]:
                    print(f"        oczekiwano: {g!r}\n        jest:       {pv!r}")
    p, r, f = f1(TP, FP, FN)
    print(f"\n### LACZNIE (przyblizenie): P={p:.3f} R={r:.3f} F1={f:.3f} | LLM: {USAGE.as_dict()}")


if __name__ == "__main__":
    main()
