# Odwołania2JSON

Aplikacja rozpoznaje typ dokumentu PDF (odwołanie do KIO, pełnomocnictwo, potwierdzenie przelewu) i zapisuje wyodrębnione dane jako JSON zgodny ze schematami UZP. Obsługuje PDF-y tekstowe i skany. Dokument spoza tych klas daje wynik `{}`.

## Uruchomienie (Linux / Ubuntu)

Wymagany Python 3.13+ i dostęp do internetu.

```bash
git clone https://github.com/AdriannaCzechowska/odwolania2json_PARSO.git
cd odwolania2json_PARSO
cp .env.example .env          # wpisz klucz API (albo: export MISTRAL_API_KEY=...)
bash run.sh                   # input/ -> output/, przy pierwszym uruchomieniu instaluje biblioteki
bash run.sh --input plik.pdf --output wynik.json
bash run.sh --input /sciezka/dane --output /sciezka/wyniki
bash run_gui.sh               # GUI na http://localhost:8000
```

Na serwerze oceny (`/opt/solution`) instalację robi `bash setup_vm.sh` (z `--gui` dodatkowo uruchamia GUI na porcie 8000 jako usługę), a komenda oceny jest w `RUN.md`. Kod działa też na Pythonie 3.12. Program nie wymaga GPU ani Tesseracta (OCR wykonuje model przez API).

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
.venv\Scripts\activate            # Linux: source .venv/bin/activate
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

## Sprawa: kilka dokumentów naraz (GUI)

Przycisk **Sprawa** w GUI przyjmuje naraz dokumenty jednej sprawy (odwołanie, pełnomocnictwo, potwierdzenie przelewu). Każdy dokument dostaje swój JSON, a program sprawdza zgodność danych między dokumentami, np.:

- czy pełnomocnik z odwołania jest wymieniony w pełnomocnictwie,
- czy mocodawca w pełnomocnictwie to odwołujący (NIP i nazwa),
- czy tytuł przelewu wskazuje numer postępowania z odwołania.

Sprawdzenia są opisane w `configs/case_checks.yaml` (pole z lewej, pole z prawej, rodzaj porównania). Nowe sprawdzenie dopisuje się w tym pliku, bez zmian w kodzie. Na wzorcach UZP wszystkie 60 spraw przechodzi wszystkie sprawdzenia. Widok nie zmienia plików JSON oddawanych do oceny.

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

Wynik na wszystkich danych treningowych UZP (`--split all`: 60 spraw, 30 skanów, 12 dokumentów spoza klas; 226 plików), model `ministral-8b-2512`:

| Typ | F1 |
|---|---|
| odwołanie | 0.974 |
| pełnomocnictwo | 0.998 |
| potwierdzenie przelewu | 0.998 |
| dokumenty spoza klas (`{}`) | 1.000 |
| **łącznie** | **0.983** |

Klasyfikacja: 226/226. Większość różnic w odwołaniach to konsorcja: zgodnie z odpowiedzią organizatora zwracamy wszystkich członków konsorcjum (lider pierwszy), a wzorce w repozytorium zawierają tylko lidera.

## Test odporności na gorsze skany

```bash
python eval/robustness.py --data ../hacknation-2026/dane --cases 5
```

Skrypt zamienia dokumenty z danych treningowych w symulowane skany (obrazy bez warstwy tekstowej) w kilku wariantach: czysty skan, do góry nogami, obrót o 90°, przekrzywienie o 3°, szum z rozmyciem i kompresją, niska rozdzielczość. Dla każdego wariantu liczy klasyfikację, F1 i czas na dokument, a tabelę zapisuje w `eval/robustness_wyniki.md`.

Wyniki (5 spraw walidacyjnych 46-50, 15 dokumentów na wariant, model `ministral-8b-2512`, pomiar sprzed ostatecznej wersji wykrywania orientacji opisanej niżej):

| Wariant | Klasyfikacja | F1 |
|---|---|---|
| oryginalny PDF tekstowy | 15/15 | 0.982 |
| skan czysty | 15/15 | 0.961 |
| skan do góry nogami | 15/15 | 0.941 |
| skan obrócony o 90° | 15/15 | 0.948 |
| skan przekrzywiony o 3° | 15/15 | 0.935 |
| skan z szumem i rozmyciem | 15/15 | 0.963 |
| skan w niskiej rozdzielczości | 15/15 | 0.941 |

Test wykrył, że przy odwróconej stronie model nie zwraca bełkotu, tylko płynny, zmyślony tekst (F1 0.537). Rozwiązanie (`core/orient.py`, `core/pipeline.py`):

1. Z obrazu prostujemy stronę i ustalamy, czy linie tekstu biegną poziomo czy pionowo.
2. Model czytający skan dostaje polecenie: jeśli tekst jest odwrócony albo obrócony bokiem, ma niczego nie przepisywać i odpowiedzieć słowem `OBROCONY`. Wtedy program obraca obraz i czyta ponownie.
3. Strony jednego skanu są zwykle obrócone tak samo, więc przy niepewnej stronie najpierw próbujemy orientacji poprzedniej strony.
4. Próbowaliśmy też wybierać między dwoma odczytami po liczbie konkretów (daty, numery) i po liczbie powtórzeń. Oba kryteria zawiodły na prawdziwych skanach, bo zmyślony tekst też zawiera daty i numery, a dobry odczyt czasem się powtarza.

Sprawdzenie na prawdziwych skanach UZP (`dane/skany`, 30 dokumentów) i na tych samych skanach odwróconych o 180° (`python eval/rotate_scans.py --data <dane> --angle 180`):

| Skany UZP | F1 |
|---|---|
| proste | 0.957 |
| odwrócone o 180° | 0.952 |

Pieczątka wpływu ("WPŁYNĘŁO dnia ... L.dz.") nie jest brana za miejscowość i datę pisma. Nazwy firm i osób są dociągane do brzmienia z dokumentu: forma prawna (np. "Sp. z o.o." albo pełna "spółka z ograniczoną odpowiedzialnością") i kolejność imienia i nazwiska, tylko gdy dany wariant występuje w tekście.

Model 3B (`ministral-3b-2512`) dał na całym zbiorze F1 0.976 wobec 0.983 dla 8B, a na pełnomocnictwach 0.952 wobec 0.998, więc zostaliśmy przy 8B.

## Struktura

```
main.py            CLI
server.py          GUI (FastAPI) + static/index.html
core/              pdf, klasyfikacja, ekstraktory, llm, normalizacja, pipeline, cache
configs/           klasy dokumentów (YAML), configs/extra/ = dodatkowe klasy
schemas/ prompts/  schematy JSON i prompty per klasa
eval/              evaluator F1
```
