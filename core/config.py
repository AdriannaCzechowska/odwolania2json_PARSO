"""Ladowanie konfiguracji klas dokumentow (YAML + schematy + prompty)."""
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class DocType:
    name: str
    raw: dict
    schema: dict
    prompt: str
    fields: dict = field(default_factory=dict)

    @property
    def llm_mode(self) -> str:
        return self.raw.get("llm", "always")


@dataclass
class Config:
    settings: dict
    types: dict
    dictionaries: dict


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path) if path else ROOT / "configs" / "document_types.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    all_types = dict(raw.get("document_types") or {})
    # dodatkowe klasy: kazdy plik configs/extra/*.yaml z sekcja document_types (enabled: false = wylaczona)
    for extra in sorted((path.parent / "extra").glob("*.yaml")):
        all_types.update((yaml.safe_load(extra.read_text(encoding="utf-8")) or {}).get("document_types") or {})
    types = {}
    for name, t in all_types.items():
        if t.get("enabled", True) is False:
            continue
        schema = json.loads((ROOT / t["schema"]).read_text(encoding="utf-8"))
        prompt = (ROOT / t["prompt"]).read_text(encoding="utf-8") if t.get("prompt") else ""
        types[name] = DocType(name=name, raw=t, schema=schema, prompt=prompt, fields=t.get("fields") or {})
    dicts = {k: {int(i) if str(i).isdigit() else i: v for i, v in d.items()}
             for k, d in (raw.get("dictionaries") or {}).items()}
    return Config(settings=raw.get("settings") or {}, types=types, dictionaries=dicts)


def skeleton(schema: dict):
    """Pusty obiekt zgodny ze schematem: null dla wartosci, [] dla list."""
    t = schema.get("type")
    if t == "object" or (isinstance(t, list) and "object" in t):
        return {k: skeleton(v) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        return []
    return None
