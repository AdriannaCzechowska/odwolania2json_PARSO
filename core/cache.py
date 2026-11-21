"""Prosty cache klucz-wartosc w SQLite (tekst PDF, OCR, odpowiedzi LLM)."""
import hashlib
import json
import sqlite3
import threading
from pathlib import Path

from .config import ROOT

_lock = threading.Lock()
_conn = None


def _db():
    global _conn
    if _conn is None:
        path = ROOT / ".cache" / "cache.sqlite"
        path.parent.mkdir(exist_ok=True)
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    return _conn


def key(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else json.dumps(p, sort_keys=True, ensure_ascii=False).encode())
        h.update(b"\x00")
    return h.hexdigest()


def get(k: str):
    with _lock:
        row = _db().execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return json.loads(row[0]) if row else None


def put(k: str, value) -> None:
    with _lock:
        _db().execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(value, ensure_ascii=False)))
        _db().commit()
