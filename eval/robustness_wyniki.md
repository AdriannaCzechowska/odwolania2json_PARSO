# Test odporności na gorsze skany

Model: `ministral-3b-2512`. Dane: 5 spraw z przykładów 46-60 (15 dokumentów), każdy przetworzony w 3 wariantach. Skany są symulowane: strony zamienione na obrazy bez warstwy tekstowej i celowo zepsute. F1 liczone przybliżonym evaluatorem (`eval/evaluate.py`).

| Wariant | Opis | Klasyfikacja | F1 łącznie | Odwołania | Pełnomocnictwa | Przelewy | Czas / dok. |
|---|---|---|---|---|---|---|---|
| skan_czysty | skan 200 dpi, bez zakłóceń | 15/15 | **0.961** | 0.931 | 0.991 | 1.000 | 3.0 s |
| skan_180 | skan do góry nogami | 15/15 | **0.941** | 0.896 | 0.991 | 1.000 | 10.9 s |
| skan_90 | skan obrócony o 90° | 15/15 | **0.948** | 0.915 | 0.983 | 1.000 | 10.7 s |
