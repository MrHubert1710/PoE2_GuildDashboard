# Faza 1 — SQLite i powtarzalny import

Status: faza 1 odebrana przez użytkownika na podstawie testów i walidacji.
Dalszy zakres: [phase-2.md](phase-2.md).

Obecny schemat 4 obejmuje migracje workera, ilości oraz rejestru plików danych; opis poniżej
dokumentuje pierwotny import. Dane historyczne pozostają zachowane.

## Wynik

- Niezależna baza `data/poe2guild.sqlite`, schemat 1 i dziennik WAL.
- 89 190 transakcji Runes of Aldur i 15 344 Forbidden Rites: łącznie 104 534.
- 30 zarejestrowanych plików wejściowych: historie i cache cen.
- Drugie wczytanie tego samego wejścia: 0 nowych rekordów, 104 534 duplikaty.
- Dane można odtworzyć z lokalnych kopii lub ze wskazanego starego projektu.
  Źródła nie są modyfikowane, a baza i pliki pozostają poza Git.

Podgląd w przeglądarce dodaje sekcję Baza danych i karty obu lig. To diagnostyka
fazy 1; nie jest listą wyboru ligi ani przeglądarką transakcji z fazy 2.
Przycisk odświeża wyłącznie status, nie importuje danych i nie wywołuje API gry.

## Schemat i pochodzenie danych

Migracje SQL są w `backend/migrations/`, z numerem, SHA-256 i wersją SQLite
`user_version`. Zastosowanych migracji nie należy edytować: dodaje się kolejne.
`init`/`migrate` weryfikują historię migracji. Odczyt HTTP nigdy nie tworzy ani
nie migruje bazy. Nieznana wersja schematu daje jawny stan niedostępności.

Schemat obejmuje źródła, ligi, zewnętrzne ID, przebiegi importu, transakcje,
pliki archiwalne i rewizje wejścia. Są również tabele na kursory, obserwacje
katalogów i zadania; nie ma jeszcze workera ani synchronizacji zewnętrznej.
Rewizja `raw_import` oznacza przyjęcie wejścia, nie wygenerowany raport analityczny.

Tożsamość transakcji: `(source_id, league_id, external_id)`.
`source-key` oznacza logiczną gildię/źródło, nie ścieżkę pliku. Używaj tej samej
wartości przy ponownym imporcie tej samej gildii. Zmiana klucza celowo tworzy
odrębne źródło. Domyślne `legacy-primary` nie potwierdza ID gildii w GGG;
`owner_reference` pozostaje nieustalone do późniejszego mapowania integracji.
Obecny import deklaruje grę PoE2 i platformę PC. ID lig są deterministyczne
z game/realm/nazwy i nie zmieniają się przy odtworzeniu bazy z tego samego wejścia.

Import zachowuje oryginalne wartości pól w `raw_json` i plik CSV z SHA-256.
Normalizacja `csv-v1`: usunięcie białych znaków na brzegach pól, data aware
przeliczona do UTC z mikrosekundami, całkowite nieujemne współrzędne oraz
walidacja added/removed/modified. Nie oblicza ilości przedmiotów, nie stosuje
aliasów skrytek i nie przelicza cen — to zakres dalszych faz.

Ustawienia starego projektu są przechowywane jako kandydat z jawnym,
niepotwierdzonym historycznie pochodzeniem. Ponowny import nie nadpisuje
ustawień istniejącej ligi. Zachowanie cache cen nie potwierdza daty
wyceny ani kompletności historii. Importowane ligi mają nieustalony status,
niepotwierdzoną kompletność i lokalną politykę archiwum bez fetchowania.

## Duplikaty, błędy i korekty

- To samo ID i te same znormalizowane pola: duplikat, bez dodatkowej transakcji.
  Równoważne daty z różnymi offsetami i różnice skrajnych spacji są równoważne.
- To samo ID i inne znormalizowane dane: konflikt, bez cichego nadpisania.
- Brak pól, obca liga, data bez strefy/błędna, nieznana akcja lub nieprawidłowe
  współrzędne: błędny rekord. Zero jest poprawną współrzędną.
- Konflikt lub błędny rekord wycofuje cały przebieg obejmujący obie ligi,
  łącznie z nowymi archiwami i rewizjami. Zachowany jest rejestr nieudanej próby
  oraz ograniczona do 100 lista przykładów kodów błędów i numerów wierszy.
- Zmieniony plik bez odpowiedniej aktualizacji manifestu jest odrzucany przed
  rozpoczęciem importu. Pliki są ponownie hashowane przed zatwierdzeniem.
- Korekty nie mają automatycznego trybu replace. Świadoma korekta wymaga
  poprawionego, zweryfikowanego wejścia i jawnego odtworzenia bazy. Stare
  wejście pozostaje w archiwum; należy odnotować zmianę poza danymi źródłowymi.

Idempotencja dotyczy transakcji i archiwów: kolejna próba ma osobny wpis audytu.
Nie tworzy nowej rewizji, jeśli nie zmieniły się dane ani pliki. Różna surowa
wersja CSV może być zachowana jako kolejne archiwum nawet wtedy, gdy wszystkie
zdarzenia są po normalizacji równoważne. Historia plików jest wersjonowana.

## Polecenia

```sh
cd /home/nginx-http/poe2guild
.venv/bin/python scripts/database.py init
.venv/bin/python scripts/database.py migrate
.venv/bin/python scripts/database.py import
.venv/bin/python scripts/database.py status
.venv/bin/python scripts/database.py verify
```

Wymagany jest poprawny manifest `data/import-manifest.json` i archiwa z fazy 0.
`import` inicjalizuje/migruje schemat, importuje w jednej transakcji, następnie
wykonuje `integrity_check` i `foreign_key_check`. Ponowny import tworzy nowy
wpis audytu. Weryfikacja jest powiązana z ostatnim ukończonym importem;
podgląd nie przedstawia starej kontroli jako aktualnej dla nowego importu.

Niezależna kopia ze starego katalogu:

```sh
.venv/bin/python scripts/database.py import --legacy-source ../poe2-guild
```

To polecenie tworzy własny bundle w `data/source-imports/<hash>/`, zawierający
historie, ceny oraz wyłącznie dozwolone ustawienia starego
configu. Nie importuje poświadczeń i nie uruchamia kodu źródłowej aplikacji.
Identyczne wejście wykorzystuje ten sam bundle. Po utworzeniu bundle baza
nie zależy od istnienia starego katalogu. Lokalne źródłowe kopie nie są usuwane.

Pełne odtworzenie jest operacją offline:

```sh
./poe2guild stop
.venv/bin/python scripts/database.py rebuild --legacy-source ../poe2-guild
./poe2guild start
```

Można też użyć `rebuild` bez `--legacy-source`, aby odtworzyć z obecnych kopii.
`--database` wskazuje inny plik bazy; bundle wejściowe muszą znajdować się w jego
katalogu danych. `--archives` wskazuje katalog bundle. Nie odtwarzaj bazy
przy działających zewnętrznych programach zapisujących SQLite.

Odtworzenie sprawdza zapisane PID-y usług, buduje nowy plik w tym samym
systemie plików, importuje i weryfikuje go, zamyka WAL i dopiero potem wykonuje
atomową podmianę. Błąd przygotowania/importu/podmiany zachowuje dotychczasowe
dane. Wymagany jest zapas miejsca na drugą bazę. Kontrola PID jest konserwatywna:
niepoprawny lub ponownie użyty PID trzeba wyjaśnić; narzędzie nie zabija procesu.

Wszystkie polecenia zapisujące korzystają z jednej blokady konserwacji przy bazie.
Przyszły worker musi używać tego samego protokołu. Odczyty API nie blokują
zwykłego importu: WAL pozwala im widzieć poprzedni zatwierdzony stan.

## API i testy

`GET /api/database-status` otwiera bazę read-only i odczytuje spójny snapshot.
Pokazuje liczby, zakresy dat, rejestr plików, wynik ostatniego importu i kontrolę
integralności. Porównanie z audytem sprawdza liczby, daty UTC i SHA źródłowego CSV.
Brak audytu daje stan bez porównania, nie fałszywą zgodność.
Brak bazy/nieobsługiwany schemat daje 503. Endpoint nie ujawnia kont, surowych
zdarzeń, ustawień, poświadczeń ani ścieżek systemowych i nie udostępnia importu.

Testy obejmują migracje i ich sumy, foreign keys, WAL, współbieżny odczyt,
powtórny import, zakres źródło/liga, zachowanie surowych pól, konflikty,
błędne dane, odtworzenie i awarię podmiany, blokadę konserwacji oraz API.
Testy Chromium korzystają z osobnych fixture, nie z produkcyjnej bazy.
Weryfikacja implementacji: 35 testów Pythona oraz 7 testów Chromium.
Dodatkowo odbiór wdrożenia obejmuje rzeczywiste odtworzenie i ponowny import
obu lig oraz sprawdzenie publicznej strony z produkcyjną bazą.

## Odbiór manualny

1. Otwórz http://dyyyl.ovh/poe2guild/ i sprawdź oznaczenie Faza 1.
2. Sekcja Baza danych: 104 534 transakcje, schemat 1, WAL i Integralność OK.
3. Karty lig: 15 344 i 89 190 rekordów oraz Zgodna z audytem.
4. Rozwiń Ostatni import: po sprawdzonym powtórnym imporcie zobaczysz 0
   dodanych, 104 534 pominięte duplikaty i 0 błędów/konfliktów.
5. Sprawdź niepotwierdzoną kompletność i nieustalony status lig — aplikacja
   nie utożsamia zarchiwizowanego wejścia z pełną historią ligi.
6. Odśwież podgląd i sprawdź układ mobilny. Dawny audyt nadal jest dostępny niżej.

Po odbiorze praca zatrzymuje się. Przejście do fazy 2 wymaga osobnego polecenia.

## Aktualny rejestr danych

Migracja 004 ogranicza `archive_files` do `history` i `price_cache`, zachowując
identyfikatory oraz sumy kontrolne tych wpisów. Nie zmienia transakcji,
ustawień lig ani projekcji ilościowych. Import i audyt obejmują historie CSV
oraz źródłowy cache cen. Aktualne dane obu lig to 104 534 transakcje i 30
zarejestrowanych plików wejściowych. Schemat SQLite: 4.

Weryfikacja po uporządkowaniu zakresu: 160 testów backendu, 86 scenariuszy
Chromium i 16 testów tłumaczeń. Potwierdzono identyczne transakcje, ustawienia
oraz sumy kontrolne wszystkich kopii cen przed i po zmianie.
