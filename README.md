# Odwołania2JSON

Aplikacja rozpoznaje typ dokumentu PDF (odwołanie do KIO, pełnomocnictwo, potwierdzenie przelewu) i zapisuje wyodrębnione dane jako JSON zgodny ze schematami UZP. Obsługuje PDF-y tekstowe i skany. Dokument spoza tych klas daje wynik `{}`.

## Uruchomienie (Windows)

Wymagany Python 3.13+ i dostęp do internetu.

1. Pobierz repozytorium i wejdź do folderu.
2. Skopiuj `.env.example` jako `.env` i wklej klucz API (klucz przekazujemy w formularzu zgłoszenia).
3. Umieść sprawy w folderze `input`, np. `input/sprawa1/*.pdf`.
4. Kliknij dwukrotnie **`start.bat`**. Przy pierwszym uruchomieniu zainstaluje biblioteki.
5. Wyniki pojawią się w folderze `output` z tą samą strukturą i nazwami plików (`input/sprawa1/x.pdf` → `output/sprawa1/x.json`).

Interfejs graficzny: **`start_gui.bat`** otwiera http://localhost:8000. Wczytujesz PDF i widzisz dokument obok wyodrębnionych danych.

### Uruchomienie ręczne (każdy system)

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py                    # input/ -> output/
python main.py --input plik.pdf --output wynik.json
python main.py --input folder --output folder_wynikow --trace   # + ślad ekstrakcji w logs/
python server.py                  # GUI na http://localhost:8000
```

## Model językowy

| | |
|---|---|
| Model | Ministral 3 8B (`ministral-8b-2512`), licencja Apache 2.0, otwarte wagi (możliwa instalacja lokalna) |
| Dostawca | Mistral AI (Francja), endpoint UE `https://api.eu.mistral.ai/v1` |
| Rozmiar | 8 mld parametrów: świadomie mały model, dużą część pracy wykonują reguły |

Dostawcę i model zmienia się w `configs/document_types.yaml` albo zmiennymi `LLM_BASE_URL`, `LLM_MODEL` (dowolne API zgodne z OpenAI).

## Jak to działa

```
PDF ─► PyMuPDF (warstwa tekstowa, 4 pierwsze strony)
     └► strona bez tekstu = skan ─► OCR modelem z wizją (obrót 180° przy nieczytelnym wyniku)
   ─► klasyfikacja regułowa (punktacja słów kluczowych z YAML) ─► brak klasy = {}
   ─► reguły deterministyczne (nagłówek miejscowość+data, BZP, TED, pola przelewu po etykietach)
   ─► LLM ze structured output (JSON Schema) dla pól semantycznych
   ─► scalenie (reguły mają pierwszeństwo) ─► normalizacja typów
   ─► weryfikacja: KRS/NIP/REGON/PESEL/rachunki/e-mail muszą występować w tekście (anty-halucynacja)
   ─► walidacja JSON Schema ─► output/*.json
```

- **Przelewy** są zwykle wyciągane w całości regułami, a LLM uruchamia się tylko wtedy, gdy brakuje wymaganych pól.
- **Cache** w SQLite (`.cache/`): ten sam dokument i prompt nie generują ponownego wywołania API.
- **Licznik tokenów i kosztu** jest w `core/llm.py`. Limit aplikacyjny to `session_budget_usd`.
- **Transparentność:** zakładka „Przebieg” w GUI i opcja `--trace` pokazują wynik klasyfikacji, użyte reguły, źródło każdej wartości, odrzucone wartości i ostrzeżenia.

## Dodanie nowej klasy dokumentów (bez programowania)

**W GUI (kreator):** przycisk **Typy dokumentów** → podajesz nazwę, przykładowy wynik JSON i 1-5 przykładowych PDF-ów → **Przygotuj typ**. System sam:
- tworzy schemat JSON z przykładu i odgaduje typy pól (data, kwota, NIP, KRS, rachunek, osoba, nazwa podmiotu),
- wybiera słowa rozpoznające typ (nagłówek i słowa wspólne dla przykładów, nieużywane przez inne klasy),
- **uczy się reguł z przykładu**: jeśli wartość z JSON stoi w PDF po etykiecie (np. „Data wystawienia: 2026-11-05”), zapamiętuje etykietę; takie pola działają bez modelu,
- generuje polecenie dla modelu i od razu testuje wszystko na przykładowych PDF-ach.

Po poprawkach (typy pól, słowa, prompt) klikasz **Zapisz i włącz typ**. Powstają 3 pliki (`schemas/`, `prompts/`, `configs/extra/`), a typ działa od razu w GUI i w CLI. Typy dodane konfiguracją można włączać i wyłączać w tym samym panelu.

Gotowe pliki do demonstracji: `demo/nowy_typ_faktura/` (3 faktury i `przyklad.json`).

**Ręcznie:** ten sam efekt dają trzy pliki napisane samodzielnie: schemat `schemas/<klasa>.schema.json`, prompt `prompts/<klasa>.txt` (z miejscem `{text}`) i `configs/extra/<klasa>.yaml` (słowa kluczowe, reguły `labels` / `regex` / `sentence_classifier`, typy pól, tryb LLM `always` / `fallback` / `never`). Przykład: `configs/extra/faktura.yaml` (wyłączony, `enabled: false`).

## Ewaluacja

```bash
python eval/evaluate.py --data ../hacknation-2026/dane --split dev        # przykłady 01-45
python eval/evaluate.py --data ../hacknation-2026/dane --split val        # przykłady 46-60
python eval/evaluate.py --data ../hacknation-2026/dane --split all --offline   # bez API
```

Raportuje precision, recall i F1 per typ i per pole, z przykładami błędów. To przybliżenie zasad organizatora (listy dopasowywane po treści, nazwy i tytuły z progiem 80%), a nie oficjalny evaluator.

## Struktura

```
main.py            CLI
server.py          GUI (FastAPI) + static/index.html
core/              pdf, klasyfikacja, ekstraktory, llm, normalizacja, pipeline, cache
configs/           klasy dokumentów (YAML), configs/extra/ = dodatkowe klasy
schemas/ prompts/  schematy JSON i prompty per klasa
eval/              evaluator F1
```
