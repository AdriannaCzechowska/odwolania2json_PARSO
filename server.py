"""GUI: lokalny serwer FastAPI. Uruchom: python server.py  ->  http://localhost:8000"""
import hashlib
import json
import sys
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

import pymupdf  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402

from core import creator  # noqa: E402
from core.llm import USAGE  # noqa: E402
from core.pipeline import Extractor  # noqa: E402

app = FastAPI(title="Odwolania2JSON")
ex = Extractor()
UPLOADS = ROOT / ".cache" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/info")
def info():
    return {"model": ex.llm.model, "llm_available": ex.llm.available,
            "types": {n: t.raw.get("description", n) for n, t in ex.config.types.items()},
            "usage": USAGE.as_dict()}


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)):
    data = await file.read()
    doc_id = hashlib.sha256(data).hexdigest()[:16]
    path = UPLOADS / f"{doc_id}.pdf"
    path.write_bytes(data)
    try:
        res = ex.process(path, with_provenance=True)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)
    res["usage"] = USAGE.as_dict()
    res["filename"] = file.filename
    res["doc_id"] = doc_id
    return JSONResponse(json.loads(json.dumps(res, ensure_ascii=False, default=str)))


@app.get("/api/page/{doc_id}/{n}")
def page_image(doc_id: str, n: int, dpi: int = 110):
    """Strona PDF jako obraz PNG (podglad z podswietleniami rysowanymi w przegladarce)."""
    path = UPLOADS / f"{doc_id}.pdf"
    if not doc_id.isalnum() or not path.exists():
        raise HTTPException(404, "Nie znaleziono dokumentu")
    doc = pymupdf.open(path)
    if not 1 <= n <= doc.page_count:
        raise HTTPException(404, "Nie ma takiej strony")
    png = doc[n - 1].get_pixmap(dpi=min(max(dpi, 50), 200)).tobytes("png")
    doc.close()
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


# ---------------- kreator nowych typow dokumentow ----------------
def _reload():
    global ex
    ex = Extractor()


@app.get("/api/types")
def types():
    return creator.list_types(ex.config)


@app.post("/api/types/draft")
async def type_draft(name: str = Form(...), description: str = Form(""), example: str = Form(...),
                     files: list[UploadFile] = File(default=[])):
    try:
        example_obj = json.loads(example)
    except json.JSONDecodeError as e:
        return JSONResponse({"error": f"Przykładowy JSON jest niepoprawny: {e}"}, status_code=400)
    paths = []
    for f in files[:5]:
        data = await f.read()
        pth = UPLOADS / f"draft_{hashlib.sha256(data).hexdigest()[:12]}_{Path(f.filename or 'x.pdf').name}"
        pth.write_bytes(data)
        paths.append(pth)
    try:
        d = creator.draft(name.strip(), description.strip(), example_obj, paths, ex.config)
        tests = creator.test_draft(d, paths, ex.config, Extractor)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    d["test"] = tests
    d["sample_files"] = [p.name for p in paths]
    return JSONResponse(json.loads(json.dumps(d, ensure_ascii=False, default=str)))


@app.post("/api/types/retest")
def type_retest(d: dict = Body(...)):
    """Ponowny test po recznych poprawkach (slowa kluczowe, prompt, typy pol)."""
    paths = [UPLOADS / n for n in d.get("sample_files", []) if (UPLOADS / n).exists() and "/" not in n]
    try:
        d["test"] = creator.test_draft(d, paths, ex.config, Extractor)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=400)
    return JSONResponse(json.loads(json.dumps(d, ensure_ascii=False, default=str)))


@app.post("/api/types/save")
def type_save(d: dict = Body(...)):
    try:
        files = creator.save(d)
    except (ValueError, KeyError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    _reload()
    return {"saved": files, "types": creator.list_types(ex.config)}


@app.post("/api/types/{name}/enabled")
def type_enable(name: str, enabled: bool = Body(..., embed=True)):
    try:
        creator.set_enabled(name, enabled)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    _reload()
    return creator.list_types(ex.config)


@app.delete("/api/types/{name}")
def type_delete(name: str):
    try:
        archived = creator.archive(name)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    _reload()
    return {"archived": archived}


@app.get("/api/types/archive")
def type_archive_list():
    return creator.list_archived()


@app.post("/api/types/archive/{archive_id}/restore")
def type_restore(archive_id: str):
    try:
        names = creator.restore(archive_id)
    except (ValueError, StopIteration) as e:
        return JSONResponse({"error": str(e) or "Pusta pozycja archiwum"}, status_code=400)
    _reload()
    return {"restored": names}


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8000
    if "--no-browser" not in sys.argv:
        webbrowser.open(f"http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
