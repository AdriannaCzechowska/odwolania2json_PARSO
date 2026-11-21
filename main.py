"""CLI Odwolania2JSON.

  python main.py                                  # input/ -> output/ (struktura folderow zachowana)
  python main.py --input plik.pdf --output wynik.json
  python main.py --input folder --output folder_wynikow
"""
import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from core.pipeline import Extractor  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


_EX = None


def _init_worker(config_path):
    """Kazdy proces ma wlasny ekstraktor (PyMuPDF nie jest bezpieczny dla watkow)."""
    global _EX
    from core.config import load_config
    _EX = Extractor(load_config(config_path) if config_path else None)


def _process(pdf_path):
    try:
        res = _EX.process(pdf_path)
        return res["result"], res["type"] or "nieznany", "; ".join(res["trace"]["warnings"]), res["trace"]
    except Exception as e:  # jeden zly plik nie zatrzymuje reszty
        return {}, "BLAD", f"{type(e).__name__}: {e}", None


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="PDF (odwolanie KIO / pelnomocnictwo / przelew) -> JSON")
    ap.add_argument("--input", default=str(ROOT / "input"), help="plik PDF lub folder (domyslnie ./input)")
    ap.add_argument("--output", default=str(ROOT / "output"), help="plik JSON lub folder (domyslnie ./output)")
    ap.add_argument("--config", default=None, help="sciezka do configs/document_types.yaml")
    ap.add_argument("--trace", action="store_true", help="zapisz slad ekstrakcji do ./logs")
    ap.add_argument("--workers", type=int, default=4, help="ile dokumentow przetwarzac rownolegle (domyslnie 4)")
    args = ap.parse_args()

    from core.llm import LLM
    from core.config import load_config
    if not LLM((load_config(args.config) if args.config else load_config()).settings.get("llm", {})).available:
        print("UWAGA: brak MISTRAL_API_KEY w .env - dzialaja tylko reguly (bez LLM i OCR skanow).")

    src, dst = Path(args.input), Path(args.output)
    if src.is_file():
        jobs = [(src, dst if dst.suffix.lower() == ".json" else dst / (src.stem + ".json"))]
    else:
        pdfs = sorted(p for p in src.rglob("*") if p.suffix.lower() == ".pdf")
        jobs = [(p, dst / p.relative_to(src).with_suffix(".json")) for p in pdfs]
    if not jobs:
        print(f"Brak plikow PDF w {src}")
        return 1

    import time
    from concurrent.futures import ProcessPoolExecutor, as_completed
    t_start = time.time()
    counts = {}
    workers = max(1, min(args.workers, len(jobs)))
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(args.config,)) as pool:
        futures = {pool.submit(_process, str(p)): (p, o) for p, o in jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            pdf_path, out_path = futures[fut]
            data, kind, warn, trace = fut.result()
            write_json(out_path, data)
            if args.trace and trace:
                rel = out_path.relative_to(dst) if src.is_dir() else Path(out_path.name)
                write_json(ROOT / "logs" / rel.with_suffix(".trace.json"), trace)
            counts[kind] = counts.get(kind, 0) + 1
            print(f"[{i}/{len(jobs)}] {pdf_path.name} -> {kind}" + (f"  ({warn})" if warn else ""), flush=True)
    elapsed = time.time() - t_start
    print(f"Czas: {elapsed:.1f} s ({elapsed / len(jobs):.1f} s na dokument, {workers} rownolegle)")
    print("Podsumowanie:", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
