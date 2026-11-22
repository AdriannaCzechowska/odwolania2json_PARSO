"""Diagnostyka orientacji: dla kazdej strony skanu zapisuje odczyt prosty i odwrocony (z cache, bez API).

  python eval/orient_pairs.py --data ../hacknation-2026/dane
Wynik: logs/orient_pairs.jsonl
"""
import argparse
import json
import os
import sys
from pathlib import Path

os.environ["LLM_OFFLINE"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from core import pdf  # noqa: E402
from core.config import load_config  # noqa: E402
from core.llm import LLM  # noqa: E402
from core.orient import detect_rotation, repetition, specificity  # noqa: E402


def main():
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    args = ap.parse_args()
    cfg = load_config()
    llm = LLM(cfg.settings.get("llm", {}))
    dpi = cfg.settings.get("pdf", {}).get("ocr_dpi", 200)
    out = ROOT / "logs" / "orient_pairs.jsonl"
    out.parent.mkdir(exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        for f in sorted((Path(args.data) / "skany").rglob("*.pdf")):
            doc = pymupdf.open(f)
            for i, page in enumerate(doc):
                if len(page.get_text().strip()) >= 60:
                    continue
                pix = page.get_pixmap(dpi=100, colorspace=pymupdf.csGRAY)
                g = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
                angle, sure, cands = detect_rotation(g)
                rec = {"file": str(f.relative_to(args.data)), "page": i + 1, "detect": angle, "sure": sure}
                for a in (0, 180):
                    try:
                        t = llm.transcribe_image(pdf.render_png_b64(str(f), i + 1, dpi, (360 - a) % 360))
                    except Exception:
                        t = None
                    rec[f"t{a}"] = t
                    if t:
                        rec[f"rep{a}"] = round(repetition(t), 3)
                        rec[f"spec{a}"] = specificity(t)
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
    print(f"{n} stron -> {out}")


if __name__ == "__main__":
    main()
