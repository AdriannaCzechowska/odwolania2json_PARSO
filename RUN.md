# PARSO - Odwołania2JSON

## Komenda uruchamiająca

Z katalogu `/opt/solution`:

```bash
bash run.sh
```

- Przetwarza wszystkie pliki PDF z `/opt/solution/input` (także w podfolderach).
- Wynik zapisuje do `/opt/solution/output` z tą samą strukturą i nazwą pliku: `input/sprawa1/x.pdf` → `output/sprawa1/x.json`.
- Dokument spoza obsługiwanych klas (odwołanie do KIO, pełnomocnictwo, potwierdzenie przelewu) daje plik z `{}`.
- Nie wymaga interakcji i kończy się sama. Nie korzysta z usług działających w tle.
- Środowisko (`.venv`) i biblioteki są zainstalowane wcześniej (`setup_vm.sh`), więc komenda niczego nie pobiera.

## Usługi zewnętrzne

- **Mistral AI API, region UE** (`https://api.eu.mistral.ai/v1`), model `ministral-8b-2512` (open source, licencja Apache 2.0).
- Służy do ekstrakcji pól semantycznych i do odczytu skanów (model z obsługą obrazu). Reguły, klasyfikacja, normalizacja i walidacja działają lokalnie.
- Klucz API: zmienna `MISTRAL_API_KEY` w pliku `/opt/solution/.env`.

## Interfejs graficzny (opcjonalnie)

`http://<adres-serwera>:8000` - wgranie PDF, podgląd dokumentu z zaznaczonymi polami, JSON do pobrania, kreator nowych typów dokumentów (na serwerze w trybie demonstracyjnym, bez zapisu).

Szczegóły: `README.md`.
