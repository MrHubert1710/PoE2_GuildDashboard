# Faza 0 — kontrakty i punkty odniesienia

Status: faza 0 zakończona i zaakceptowana przez użytkownika.
Zweryfikowano 16 testów Pythona, 4 testy Chromium i publiczny adres przez Nginx.

Zakres: zamknięcie fundamentów i podgląd audytu w przeglądarce.
Bez SQLite, importera do bazy, tabeli transakcji, fetchera i workera z dalszych faz.

## Wynik danych referencyjnych

| Liga | Transakcje | Zakres UTC | Zweryfikowane pliki | Cache cen |
| --- | --- | --- | --- | --- |
| Runes of Aldur | 89 190 | 2026-05-29 21:40:59 – 2026-07-23 23:34:07 | 15 | 14 |
| Forbidden Rites | 15 344 | 2026-09-17 14:01:47 – 2026-10-22 19:55:05 | 15 | 14 |

Łącznie 104 534 transakcje i 30 plików danych. W audytowanych CSV nie znaleziono
brakujących/nadmiarowych pól, obcej ligi, niepoprawnych lub naiwnych dat,
nieznanych akcji ani identycznych/konfliktujących powtórzeń ID.
Brak wspólnych ID między tymi dwoma plikami nie dowodzi ich globalnej unikalności.

Raport audytu: `data/reference/phase0.json`, celowo poza Git. Zawiera SHA-256
wszystkich plików porównanych z manifestem importu i oryginałami starego projektu,
zakresy czasu, liczniki akcji/skrytek, przykłady added/removed/modified,
przykłady ilości × i współrzędnych zerowych oraz SHA-256 kodu referencyjnego.
Przykłady nie zawierają nazw kont; mają linię i hash całego rekordu do lokalnego
odnalezienia oryginału. Żaden plik źródłowy nie jest wykonywany ani zmieniany.

Z obecnego starego configu odczytywane są przez AST wyłącznie target stashes,
aliasy oraz zapis wyrażenia strefy czasu. Nie są importowane sesja ani ID gildii.
Zapisujemy pochodzenie: aktualny config starej aplikacji, bez potwierdzenia,
że obowiązywał historycznie dla każdej ligi. Stałe CEST/UTC+2 ze starego configu
nie oznacza automatycznie Europe/Warsaw z obsługą zmiany czasu.

Cache cen nie ma potwierdzonego czasu danych; mtime pliku nie jest traktowane
jako cena z tego dnia. Przypisanie ligi wynika z zastanego katalogu, nie pola
potwierdzającego ligę w odpowiedzi dostawcy. SHA zgodny z oryginałem potwierdza
zachowanie danych, nie ich kompletność ani dokładność wyceny.

## Przykłady do kolejnych faz

`tests/fixtures/reference-cases.json` jest syntetycznym zestawem bez danych kont.
Obejmuje duplikat identyczny, konflikt ID, złą ligę, datę błędną i bez strefy,
offset daty równoważny UTC, brak konta, nieznaną akcję, alias skrytki, mnożnik ×,
zerowe współrzędne oraz nieznany przedmiot. Audyt identyfikuje problemy struktury;
nie implementuje jeszcze normalizacji ilości, aliasów ani wyceny.

Przy portowaniu ilości/wyceny używać prawdziwych wskazanych zdarzeń i SHA
zachowanych danych wejściowych. Nie wymagać zgodności kwot dla innych cen lub algorytmu.
Golden wyniki obliczeń powstaną w odpowiedniej fazie na tych samych wejściach.

## Integracje

Weryfikacja dokumentacji: 2026-11-02. Wyniki i linki źródłowe są w
`backend/provider_findings.json`, a konsekwencje w `docs/architecture.md`.
Nie wykonano logowania, pobierania danych konta ani rejestracji klienta.
Nie potwierdzono uprawnień konkretnego konta ani produkcyjnego tokenu GGG.
Nie ma obietnicy OAuth dla historii gildii PoE2 ani wspieranego API katalogu
kategorii poe.ninja. Odczyt publikowanej listy będzie odrębnym adapterem.

## Odtworzenie i testy

```sh
cd /home/nginx-http/poe2guild
.venv/bin/python scripts/build-reference.py
.venv/bin/python -m unittest discover -s tests -v
npm --prefix frontend run build
npm --prefix frontend run test:browser
```

Testy przeglądarkowe używają oczyszczonego fixture
`tests/fixtures/browser-reference.json` i serwera testowego na porcie 19003,
który odwzorowuje prefiks Nginx. Nie wymagają dostępu do produkcyjnych danych.
Przed pierwszym uruchomieniem przygotuj Chromium z katalogu `frontend/`:
`npx playwright install chromium --only-shell`. Dodatkowo wykonano smoke test
wdrożonej strony z rzeczywistym snapshotem obu lig.

Pierwsze polecenie wymaga niezależnych archiwów w `data/` oraz starego projektu
w `../poe2-guild`; opcja `--source` zmienia jego ścieżkę. Generator zapisuje
snapshot atomowo dopiero po walidacji. Niezgodność danych kończy się błędem
bez nadpisania poprzedniego snapshotu. Nie pobiera żadnych danych z sieci.

API `/api/rework-readiness` odczytuje wyłącznie gotowy snapshot i publikuje
allowlistę podsumowań. Nie skanuje CSV na każde żądanie, nie wysyła próbek
zdarzeń, ustawień starego configu ani nazw kont. Brak/uszkodzenie snapshotu
daje 503 z jawnym komunikatem, bez lokalnych ścieżek.

Podgląd nie uruchamia ponownego audytu: przycisk odczytuje ostatni zapisany wynik.
Nie jest to przycisk pobierania historii, który powstanie w dalszej fazie.

## Odbiór manualny

1. Otwórz http://dyyyl.ovh/poe2guild/ i sprawdź oznaczenie Faza 0.
2. Sprawdź dwie karty lig, liczby transakcji, zakresy UTC i zgodność kopii.
3. Rozwiń sumy kontrolne; sprawdź historię i po 14 plików cen na ligę.
4. Sprawdź, że daty cen są opisane jako niepotwierdzone, a zgodność kopii nie
   jest przedstawiana jako dowód kompletności historii.
5. Przejrzyj statusy integracji i linki do dokumentacji.
6. Kliknij Odśwież podgląd; nie powinno być nawigacji ani fetchowania gry.
7. Sprawdź układ na wąskim ekranie i obsługę details/przycisku klawiaturą.

Po zakończeniu tej fazy praca zatrzymuje się. Faza 1 wymaga osobnego polecenia.
