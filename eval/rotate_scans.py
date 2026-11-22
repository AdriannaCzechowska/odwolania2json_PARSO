"""Kopia skanow UZP obroconych o zadany kat (test orientacji na prawdziwych skanach).

  python eval/rotate_scans.py --data ../hacknation-2026/dane --angle 180
  python eval/evaluate.py --data eval/_odpornosc_tmp/obrot_180 --split skany

Obraca tylko strone w PDF; wzorcowe JSON-y zostaja te same.
"""
import argparse
import shutil
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="folder 'dane' z repo UZP")
    ap.add_argument("--angle", type=int, default=180, choices=[90, 180, 270])
    args = ap.parse_args()
    src = Path(args.data) / "skany"
    out = ROOT / "eval" / "_odpornosc_tmp" / f"obrot_{args.angle}"
    shutil.rmtree(out, ignore_errors=True)
    n = 0
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        dst = out / "skany" / f.relative_to(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if f.suffix.lower() == ".pdf":
            doc = pymupdf.open(f)
            for page in doc:
                page.set_rotation((page.rotation + args.angle) % 360)
            doc.save(dst)
            n += 1
        else:
            shutil.copy2(f, dst)
    print(f"{n} PDF -> {out}")
    print(f"python eval/evaluate.py --data {out} --split skany")


if __name__ == "__main__":
    main()
