"""Jedno testowe wywolanie API (ok. 100 tokenow): sprawdza klucz, endpoint UE i structured output."""
import os
import sys

from dotenv import load_dotenv

load_dotenv()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from openai import OpenAI  # noqa: E402

key = os.environ.get("MISTRAL_API_KEY")
if not key or key.startswith("wklej"):
    sys.exit("Brak klucza: skopiuj .env.example jako .env i wklej MISTRAL_API_KEY")
base = os.environ.get("LLM_BASE_URL", "https://api.eu.mistral.ai/v1")
model = os.environ.get("LLM_MODEL", "ministral-8b-2512")
client = OpenAI(api_key=key, base_url=base, max_retries=0)
schema = {"type": "object", "additionalProperties": False, "required": ["imie_nazwisko"],
          "properties": {"imie_nazwisko": {"type": ["string", "null"]}}}
r = client.chat.completions.create(
    model=model, temperature=0, max_tokens=60,
    messages=[{"role": "user", "content": "Podaj imię i nazwisko w mianowniku: 'udzielam pełnomocnictwa Patrycji Furman'."}],
    response_format={"type": "json_schema", "json_schema": {"name": "test", "schema": schema, "strict": True}},
)
print("Endpoint:", base, "| model:", model)
print("Odpowiedz:", r.choices[0].message.content)
print("Tokeny:", r.usage.prompt_tokens, "+", r.usage.completion_tokens, "-> OK")
