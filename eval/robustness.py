"""Test odpornosci: jak wynik zmienia sie, gdy dokumenty sa gorszymi skanami.

Bierze PDF-y z danych treningowych UZP, robi z nich symulowane skany (obrazy bez warstwy tekstowej)
w kilku wariantach i liczy F1 tym samym przyblizonym evaluatorem co eval/evaluate.py.

  python eval/robustness.py --data ..\\uzp\\dane --cases 5
Wynik: tabela w konsoli i w eval/robustness_wyniki.md
"""
import argparse
import io
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VARIANTS = {
    "oryginal": "PDF z warstwą tekstową (punkt odniesienia)",
    "skan_czysty": "skan 200 dpi, bez zakłóceń",
    "skan_180": "skan do góry nogami",
    "skan_90": "skan obrócony o 90°",
    "skan_krzywy": "skan przekrzywiony o 3°",
    "skan_szum": "szum, rozmycie, niski kontrast, mocna kompresja JPEG",
    "skan_niska_rozdz": "skan 100 dpi",
}


def _degrade(img, variant, rnd):
    from PIL import Image, ImageEnhance, ImageFilter
    if variant == "skan_180":
        img = img.rotate(180, expand=True)
    elif variant == "skan_90":
        img = img.rotate(90, expand=True)
    elif variant == "skan_krzywy":
        img = img.rotate(3, expand=True, fillcolor=255, resample=Image.BICUBIC)
    elif variant == "skan_szum":
        import numpy as np
        img = ImageEnhance.Contrast(img).enhance(0.65).filter(ImageFilter.GaussianBlur(0.9))
        arr = np.asarray(img, dtype=np.int16)
        noise = np.random.default_rng(rnd.randint(0, 10**6)).normal(0, 22, arr.shape)
        img = Image.fromarray(np.clip(arr + noise, 0, 255).astype("uint8"), "L")
    return img


def make_scan(src, dst, variant, seed=0):
    """Kazda strona -> obraz (bez tekstu) -> nowy PDF."""
    from PIL import Image
    rnd = random.Random(seed)
    dpi = 100 if variant == "skan_niska_rozdz" else 200
    quality = 35 if variant == "skan_szum" else 80
    doc, out = pymupdf.open(src), pymupdf.open()
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        img = _degrade(img, variant, rnd)
        buf = io.BytesIO()
        img.convert("L").save(buf, "JPEG", quality=quality)
        w, h = img.size
        pg = out.new_page(width=w * 72 / dpi, height=h * 72 / dpi)
        pg.insert_image(pg.rect, stream=buf.getvalue())
    out.save(dst)
    doc.close()
    out.close()


_EX = None


def _init():
    global _EX
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from core.pipeline import Extractor
    _EX = Extractor()


def _run(path):
    t0 = time.time()
    try:
        r = _EX.process(path)
        return r["type"], r["result"], time.time() - t0, r["trace"]["warnings"]
    except Exception as e:
        return None, {}, time.time() - t0, [f"{type(e).__name__}: {e}"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="folder 'dane' z repo UZP")
    ap.add_argument("--cases", type=int, default=5, help="ile spraw (z przykładów 46-60, każda = 3 dokumenty)")
    ap.add_argument("--variants", default=",".join(VARIANTS), help="lista wariantów oddzielona przecinkami")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    from eval.evaluate import compare, f1

    data = Path(args.data)
    cases = [data / f"przyklad_{n:02d}" for n in range(46, 61)][: args.cases]
    docs = []
    for c in cases:
        for stem, t in (("odwolanie", "odwolanie"), ("pelnomocnictwo", "pelnomocnictwo"),
                        ("potwierdzenie_przelewu", "przelew"), ("przelew", "przelew")):
            pdf = c / f"{stem}.pdf"
            gold = c / f"{'przelew' if t == 'przelew' else stem}.json"
            if pdf.exists() and gold.exists():
                docs.append((pdf, json.loads(gold.read_text(encoding="utf-8")), t))

    variants = [v for v in args.variants.split(",") if v in VARIANTS]
    tmp = ROOT / "eval" / "_odpornosc_tmp"
    jobs = []
    for v in variants:
        (tmp / v).mkdir(parents=True, exist_ok=True)
        for i, (pdf, gold, t) in enumerate(docs):
            if v == "oryginal":
                path = pdf
            else:
                path = tmp / v / f"{pdf.parent.name}_{pdf.name}"
                if not path.exists():
                    make_scan(pdf, path, v, seed=i)
            jobs.append((v, str(path), gold, t))
    print(f"{len(docs)} dokumentów x {len(variants)} wariantów = {len(jobs)} przebiegów")

    stats = {v: {"tp": Counter(), "fp": Counter(), "fn": Counter(), "examples": defaultdict(list)} for v in variants}
    per_type = defaultdict(lambda: {"tp": Counter(), "fp": Counter(), "fn": Counter(), "examples": defaultdict(list)})
    cls_ok, times = Counter(), defaultdict(list)
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init) as pool:
        futs = {pool.submit(_run, path): (v, path, gold, t) for v, path, gold, t in jobs}
        for k, fut in enumerate(as_completed(futs), 1):
            v, path, gold, t = futs[fut]
            got_type, result, secs, warns = fut.result()
            times[v].append(secs)
            cls_ok[v] += got_type == t
            if result:
                compare(gold, result, "", stats[v])
                compare(gold, result, "", per_type[(v, t)])
            else:
                from eval.evaluate import leaves
                for lp, _ in leaves(gold):
                    stats[v]["fn"][lp] += 1
                    per_type[(v, t)]["fn"][lp] += 1
            print(f"[{k}/{len(jobs)}] {v:17s} {Path(path).name} -> {got_type} ({secs:.1f} s)" + (f" {warns[:1]}" if warns else ""), flush=True)

    def score(s):
        return f1(sum(s["tp"].values()), sum(s["fp"].values()), sum(s["fn"].values()))[2]

    n = len(docs)
    lines = ["| Wariant | Opis | Klasyfikacja | F1 łącznie | Odwołania | Pełnomocnictwa | Przelewy | Czas / dok. |",
             "|---|---|---|---|---|---|---|---|"]
    for v in variants:
        cols = [f"{score(per_type[(v, t)]):.3f}" if (v, t) in per_type else "-" for t in ("odwolanie", "pelnomocnictwo", "przelew")]
        avg = sum(times[v]) / max(1, len(times[v]))
        lines.append(f"| {v} | {VARIANTS[v]} | {cls_ok[v]}/{n} | **{score(stats[v]):.3f}** | " + " | ".join(cols) + f" | {avg:.1f} s |")
    table = "\n".join(lines)
    from core.config import load_config
    model = os.environ.get("LLM_MODEL") or load_config().settings["llm"]["model"]
    md = (f"# Test odporności na gorsze skany\n\nModel: `{model}`. Dane: {len(cases)} spraw z przykładów 46-60 "
          f"({n} dokumentów), każdy przetworzony w {len(variants)} wariantach. Skany są symulowane: strony "
          f"zamienione na obrazy bez warstwy tekstowej i celowo zepsute. F1 liczone przybliżonym evaluatorem "
          f"(`eval/evaluate.py`).\n\n{table}\n")
    (ROOT / "eval" / "robustness_wyniki.md").write_text(md, encoding="utf-8")
    print("\n" + table + "\n\nZapisano: eval/robustness_wyniki.md")


if __name__ == "__main__":
    main()
