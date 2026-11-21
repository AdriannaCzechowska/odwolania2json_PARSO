"""Klient LLM (API zgodne z OpenAI): cache, licznik tokenow/kosztu, limit sesji, retry."""
import json
import os
import re
import threading
import time

from . import cache

_lock = threading.Lock()


class BudgetExceeded(RuntimeError):
    pass


class LLMUnavailable(RuntimeError):
    pass


class Usage:
    """Licznik aplikacyjny. NIE jest gwarancja limitu obciazenia u dostawcy."""

    def __init__(self):
        self.calls = 0
        self.cached = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0

    def as_dict(self):
        return {"calls": self.calls, "cached": self.cached, "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out, "cost_usd": round(self.cost_usd, 5)}


USAGE = Usage()


def repair_json(text: str):
    """Lokalna naprawa odpowiedzi: usuwa ```json, bierze pierwszy obiekt {...}."""
    if text is None:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    a, b = t.find("{"), t.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(t[a:b + 1])
        except json.JSONDecodeError:
            t2 = re.sub(r",\s*([}\]])", r"\1", t[a:b + 1])  # przecinki przed nawiasem
            try:
                return json.loads(t2)
            except json.JSONDecodeError:
                return None
    return None


class LLM:
    def __init__(self, settings: dict):
        self.s = settings
        self._client = None
        self._last = 0.0
        self.api_key = os.environ.get("MISTRAL_API_KEY") or os.environ.get("LLM_API_KEY")
        self.base_url = os.environ.get("LLM_BASE_URL") or settings.get("base_url")
        self.model = os.environ.get("LLM_MODEL") or settings.get("model")
        self.vision_model = os.environ.get("LLM_VISION_MODEL") or settings.get("vision_model") or self.model
        self.offline = os.environ.get("LLM_OFFLINE") == "1"   # tylko cache, zero wywolan

    @property
    def available(self) -> bool:
        return bool(self.api_key) and not self.offline

    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, max_retries=0,
                                  timeout=float(self.s.get("request_timeout_s", 60)))
        return self._client

    def _throttle(self):
        gap = float(os.environ.get("LLM_MIN_INTERVAL") or self.s.get("min_interval_s", 1.0))
        with _lock:
            wait = self._last + gap - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()

    def _call(self, model, messages, response_format, max_tokens):
        """Ponawia tylko bledy sieci / 429 / 5xx. Przy 429 czeka (Retry-After albo rosnaco do 60 s)."""
        from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
        attempts = int(self.s.get("max_retries", 8))
        net_attempts = int(self.s.get("max_network_retries", 2))   # zerwane polaczenie / timeout: krotko
        deadline = time.time() + float(self.s.get("max_call_seconds", 180))  # twardy limit na jedno zapytanie
        delay, net_fail = 5.0, 0
        for attempt in range(attempts):
            if time.time() > deadline:
                raise LLMUnavailable("przekroczono limit czasu zapytania")
            self._throttle()
            try:
                kwargs = dict(model=model, messages=messages, temperature=self.s.get("temperature", 0),
                              max_tokens=max_tokens)
                if response_format:
                    kwargs["response_format"] = response_format
                return self.client().chat.completions.create(**kwargs)
            except RateLimitError as e:
                if attempt == attempts - 1:
                    raise
                ra = None
                try:
                    ra = float(e.response.headers.get("retry-after"))
                except (TypeError, ValueError, AttributeError):
                    pass
                wait = min(ra if ra else delay, 30.0, max(0.0, deadline - time.time()))
                print(f"  [limit zapytan 429] czekam {wait:.0f} s (proba {attempt + 1}/{attempts})", flush=True)
                time.sleep(wait)
                delay = min(delay * 2, 60.0)
                continue
            except (APIConnectionError, APITimeoutError):
                net_fail += 1
                if net_fail > net_attempts or attempt == attempts - 1:
                    raise
            except APIStatusError as e:
                if e.status_code < 500 or attempt == attempts - 1:
                    raise
            time.sleep(delay)
            delay = min(delay * 2, 60.0)

    def chat(self, messages, schema=None, model=None, max_tokens=None, tag="extract"):
        model = model or self.model
        max_tokens = max_tokens or self.s.get("max_output_tokens", 1500)
        mode = self.s.get("structured_output", "json_schema") if schema is not None else None
        k = cache.key("llm", model, messages, schema, mode, max_tokens)
        hit = cache.get(k)
        if hit is not None:
            USAGE.cached += 1
            return hit
        if not self.available:
            raise LLMUnavailable("Brak klucza API lub tryb offline (LLM_OFFLINE=1)")
        if USAGE.cost_usd >= float(self.s.get("session_budget_usd", 1.0)):
            raise BudgetExceeded(f"Przekroczono limit sesji {self.s.get('session_budget_usd')} USD")

        rf = None
        if mode == "json_schema":
            rf = {"type": "json_schema", "json_schema": {"name": tag, "schema": schema, "strict": True}}
        elif mode == "json_object":
            rf = {"type": "json_object"}
        from openai import BadRequestError
        try:
            resp = self._call(model, messages, rf, max_tokens)
        except BadRequestError:
            if mode != "json_schema":
                raise
            resp = self._call(model, messages, {"type": "json_object"}, max_tokens)  # dostawca bez json_schema

        u = resp.usage
        tin, tout = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
        USAGE.calls += 1
        USAGE.tokens_in += tin
        USAGE.tokens_out += tout
        USAGE.cost_usd += (tin * self.s.get("price_in_per_mtok_usd", 0) + tout * self.s.get("price_out_per_mtok_usd", 0)) / 1e6
        content = resp.choices[0].message.content
        result = {"content": content, "tokens_in": tin, "tokens_out": tout,
                  "finish": resp.choices[0].finish_reason}
        cache.put(k, result)
        return result

    def extract_json(self, prompt: str, schema: dict, tag: str):
        system = "Jesteś precyzyjnym ekstraktorem danych z polskich dokumentów prawnych. Odpowiadasz wyłącznie poprawnym JSON zgodnym ze schematem."
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        res = self.chat(messages, schema=schema, tag=tag)
        data = repair_json(res["content"])
        if data is None and res.get("finish") == "length":
            res = self.chat(messages, schema=schema, tag=tag, max_tokens=self.s.get("max_output_tokens", 1500) * 2)
            data = repair_json(res["content"])
        return data, res

    def transcribe_image(self, png_b64: str):
        """OCR przez model z wizja: zwraca czysty tekst strony."""
        url = f"data:image/jpeg;base64,{png_b64}"
        img = {"type": "image_url", "image_url": url} if self.s.get("image_url_format", "string") == "string" \
            else {"type": "image_url", "image_url": {"url": url}}
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "Przepisz dokładnie cały tekst z tego skanu dokumentu, linia po linii, zachowując polskie znaki, liczby i układ. Jeśli obraz jest odwrócony, przepisz tekst w poprawnej kolejności. Zwróć tylko przepisany tekst, bez komentarzy."},
            img]}]
        res = self.chat(messages, model=self.vision_model, max_tokens=3000, tag="ocr")
        return res["content"] or ""
