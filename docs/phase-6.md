# Faza 6 — ceny i wycena operacji

Status: zaimplementowana i wdrożona; oczekuje odbioru manualnego.
Dzień odbioru technicznego: 2026-11-03. Następne fazy nie są rozpoczęte.

## Zachowanie w przeglądarce

Domyślnie wykres i tabela Podsumowania, Graczy oraz Skrytek pokazują wartość
operacji w Divine Orb. Przełącznik Quantity mode przywraca wybór przedmiotu
oraz dotychczasowe obliczenia ilościowe, włącznie z All. Zmiana ligi zachowuje
tryb ilość/wartość i historyczne/najnowsze; zeruje wybór przedmiotu i zoom.

Historyczne ceny są domyślne. Każdy podpisany ruch otrzymuje cenę obserwowaną
nie później niż jego wykonanie. Późniejsza zmiana kursu nie przeszacowuje
poprzednich ruchów. Tryb Current prices używa jednego, przypiętego zestawu
najnowszych dostępnych snapshotów kategorii danej ligi dla całej historii.
To najnowsze dostępne obserwacje, nie gwarancja wykonania transakcji po tej cenie.

Wycena historyczna jest saldem wycenionych operacji, a nie bieżącą wartością
przechowywanych przedmiotów. Przykład: dodanie 20 sztuk po 2 Divine i zabranie
5 po 3 daje saldo 25 Divine; według najnowszej ceny 3 daje 45 Divine. Saldo
historyczne może być ujemne mimo nieujemnej ilości przedmiotów.

Wykres, miniatury, filtry UTC, tooltip w dowolnym czasie, sumy i osobna seria
Korekty rekonstrukcji działają również w trybie wartości. Korekty korzystają
z tej samej ceny danego przedmiotu w czasie zdarzenia; pozostają oddzielone
od wkładu graczy. Kolory, zwijanie i format dat zachowują ustawienia klienta.
Oś wartości obsługuje także ułamkowe ilości Divine; tooltip nie wymusza całych
liczb. Tabele wartości i brakujących cen mają paginację w URL.

Brak ceny nie oznacza 0. Wycena ma pokrycie complete / partial / none i liczniki
operacji wycenionych, brakujących oraz estymowanych. Przy braku pokrycia wykres
jest pusty z wyjaśnieniem, a tabela pokazuje nieznane ceny. Przy częściowym
pokryciu rysowana jest wyłącznie znana część wartości, z jawnym oznaczeniem.
Prawdziwa cena 0 pozostaje poprawną, rozpoznaną ceną.

System settings zawiera Źródła cen: ręczny fetch, stan kolejki, informację
o świeżym cache, katalog kategorii, błędy kategorii oraz snapshoty z czasem
i pochodzeniem. Samo pobieranie odbywa się przez wspólnego workera; klient
nie łączy się z poe.ninja. Wejście na stronę inicjuje sprawdzenie cen, z deduplikacją
między użytkownikami i minimalnym interwałem odświeżania.

## Archiwalne ceny i granice danych

Zaimportowano 28 plików cache, osobno dla obu lig. Ich czas ceny jest nieznany:
nie jest wyprowadzany z mtime, czasu importu ani sparkline. Mają pochodzenie
legacy_undated i effective_at=NULL. Powtórny import nie tworzy duplikatów.

Takie ceny mogą być wykorzystane wyłącznie jako jawne estymacje w trybie
najnowszych dostępnych cen, gdy dana kategoria nie ma obserwowanego snapshotu.
Tryb historyczny nigdy po nie nie sięga i nie używa przyszłej ceny.

Podczas wdrożenia pobrano 46 obserwowanych snapshotów dla 23 kategorii i dwóch
lig, które poe.ninja nadal zwraca w katalogu ekonomii. Nie zmienia to lokalnej
archiwizacji lig ani nie uruchamia pobierania logów GGG. Dostępność cen jest
niezależna od dostępności historii gildii. Dla ligi usuniętej z ekonomii
pozostają ostatnie lokalne snapshoty i wyjaśniony brak dostępu do dostawcy.

Nowe obserwacje nie pokrywają historycznych operacji tych archiwów. Dlatego
na istniejących danych domyślny tryb historyczny wykazuje brak pokrycia;
przełączenie na najnowsze ceny pokazuje wycenę dostępną do ręcznej weryfikacji.
To ograniczenie danych wejściowych, nie zastępcze wycenianie historii ceną z dziś.

## Adapter i katalog

Źródło kontraktu: [publiczna dokumentacja ekonomii poe.ninja](https://poe.ninja/docs/api),
zweryfikowana 2026-11-03. Rozdzielone formaty exchange i PoE 2 stash item.
Katalog pochodzi z tabel PoE 2 w publikowanej dokumentacji, ponieważ nie ma
udokumentowanego osobnego endpointu kategorii. Izolowany parser rozpoznaje
konkretne sekcje/feed i grę; nie ma listy kategorii w kodzie aplikacji.
Podczas wdrożenia wykryto 14 kategorii exchange oraz 9 stash item.

Parser waliduje wynik. Pusty/zmieniony dokument nie usuwa katalogu. Poprawny
nowy katalog dezaktywuje usunięte kategorie, zachowując snapshoty; nieznany
format feedu jest raportowany, a poprzednie ceny pozostają dostępne. Dane
niepowiązane z ekonomią nie są pobierane.

Transport ma trwały cache HTTP, ETag / If-None-Match / 304, respektuje
Cache-Control i Retry-After oraz identyfikuje aplikację i kontakt w User-Agent.
Minimalny interwał feedów i listy lig ekonomii: 1 h; dokumentacji: 24 h.
Przy błędach cache zapisuje cooldown, co zapobiega ponawianiu przez każdą kartę.
Ręczny fetch nie omija cache dostawcy. Żądania są sekwencyjne w workerze.

Normalizacja łączy exchange lines z metadanymi items po ID. primaryValue jest
przeliczane do Divine z jawnym core.primary/core.rates; nieznana waluta odrzuca
snapshot. Waluta bazowa ma wartość 1; brakująca linia nie usuwa jej z indeksu.
Identyfikatory i warianty nie zależą od kategorii wybranej w interfejsie.
Dopasowanie nazw: NFKC, wielkość liter, odstępy, apostrof. Nazwy przedmiotów
nie są tłumaczone. Niejednoznaczne nazwy i warianty pozostają bez ceny;
nie wybieramy arbitralnie jednego unikalnego przedmiotu o wspólnej nazwie.

## SQLite i odtwarzalność

Migracja 006, schemat 6:

- price_http_cache — cache transportu, ETag, terminy i kody błędów.
- price_catalogs / price_categories — wersje katalogu i aktywność kategorii.
- price_snapshots / price_quotes — niezmienne payloady, SHA-256, liga, źródło,
  czas pierwszej obserwacji, pewny/nieznany czas ceny, waluta i warianty.
- price_aliases — jawne aliasy nazw osobno dla każdej ligi.
- valuation_runs / valuation_lines — wersja algorytmu valuation-v1, przypięta
  projekcja ilościowa, rewizja cen, tryb i cena/snapshot użyte dla każdego ruchu.

Identyczny payload kategorii i pochodzenia nie tworzy duplikatu snapshotu;
zachowuje czas pierwszej obserwacji. Kolejne sprawdzenia HTTP są w cache
transportu. Rewizja cen obejmuje snapshoty i aliasy ligi. Publikacja wyceny
sprawdza rewizję cen i projekcji oraz lease workera; stara odpowiedź nie może
nadpisać wyniku. Odczyt i tooltip są przypięte do tej samej rewizji cen.

Ceny jednostkowe przechowujemy w stałej precyzji 10^-12 Divine, jako tekstowe
liczby całkowite. Mnożenie przez ilości i sumowanie wykonuje Python na liczbach
całkowitych; konwersja do liczby wykresu następuje dopiero w odpowiedzi API.
Surowe logi, korekty ilościowe i historyczne pliki cen pozostają niezmienione.

Odtwarzanie historii przez database.py rebuild zachowuje obserwacje cen,
quotes, aliasy i katalog. Odmawia utraty ligi posiadającej ceny, jeśli nie ma
jej w odtwarzanym pakiecie. Projekcje ilościowe i wyceny są odtwarzalnymi
wynikami; potrzebne jest ich ponowne wyliczenie. Pełna kopia SQLite zachowuje
również stare projekcje i wyceny.

## Polecenia operatora

Po migracji, jako konto aplikacji:

```sh
.venv/bin/python scripts/prices.py import-legacy
.venv/bin/python scripts/prices.py refresh
.venv/bin/python scripts/prices.py value
```

Pierwsze polecenie kopiuje zweryfikowane ceny z lokalnych cache do SQLite,
zachowując ich niepewny czas; kolejne zlecają workerowi pobranie i wycenę.
Istniejące JSON-y pozostają niezmienne i służą do weryfikacji źródeł.

Jawny alias ceny (nie wybiera nieznanego wariantu):

```sh
.venv/bin/python scripts/prices.py alias --league '<league-id>' \
  --source-name 'Nazwa z historii' --target-name 'Nazwa w katalogu cen'
```

Alias unieważnia wycenę tej ligi i zgłasza przeliczenie; nie zmienia nazwy
w surowej historii ani konfiguracji skrytek. Brak połączenia z poe.ninja
nie uniemożliwia korzystania z zaimportowanych cen offline.

## API

- GET /api/leagues/<id>/prices — snapshoty, katalog i rewizja cen.
- GET /api/leagues/<id>/valuations?mode=historical|latest&view=summary|players|stashes
  — tabele wartości, pokrycie, brakujące ceny i źródła wyceny; wspólne filtry.
- GET /api/leagues/<id>/quantity-series?mode=value&pricing=historical|latest
  — istniejący kontrakt wykresu, z jednostką divine_orb i metadanymi pricing.
  Cena dla kursora jest przypięta parametrem price_revision; niezgodna daje 409.
- POST /api/leagues/<id>/refresh z kind=prices lub kind=valuations — wspólne,
  trwałe zadania. Odczyt raportu nie wykonuje zapytań do dostawcy.

Parametry chart_mode, chart_pricing, valuation_page i unpriced_page są w URL.
Filtry pozostają jednoznacznymi granicami UTC; konfiguracja przeglądarki
zmienia jedynie prezentację.

## Weryfikacja techniczna

- 182 testy backendu, 90 testów Chromium i 16 testów tłumaczeń: zaliczone.
- Po dopracowaniu osi ułamkowych: ponownie zaliczone 22 testy wykresów
  i wyceny, kontrola typów oraz build produkcyjny.
- Publiczne HTTPS API obu lig: wartości końcowe tabel i wykresów są zgodne;
  historyczny brak datowanych cen pozostaje jawnym brakiem pokrycia.
- Zachowano 104 534 surowe transakcje i konfigurację lig/gildii bez zmian.
  Sumy SHA-256 wszystkich 56 istniejących plików cen pozostały identyczne.
- SQLite: integralność poprawna, brak naruszeń kluczy obcych, schemat 6.

## Odbiór manualny

1. Odświeżyć stronę: domyślnie Value mode i ceny historyczne. Na dotychczasowych
   archiwach sprawdzić jawny brak historycznych cen i listę przedmiotów bez wyceny.
2. Włączyć Current prices: pojawiają się tabela i interaktywny wykres wartości
   w Divine. Przełączyć Summary / Players / Stashes, filtry i ligę.
3. Sprawdzić zoom obiema miniaturami, tooltip między operacjami, sumę serii
   oraz oddzielne Korekty rekonstrukcji. Reload zachowuje tryb wyceny w URL.
4. Włączyć Quantity mode: wracają ilości, wybór przedmiotu i All; projekcja
   ilościowa nie jest przebudowywana wskutek zmiany sposobu wyceny.
5. Po zalogowaniu sprawdzić System settings → Źródła cen, katalog, snapshoty
   i informację o świeżym cache przy ponownym Fetch prices. Preferencje
   przeglądarki nadal są lokalne. Przełączyć PL/EN i szerokość mobilną.

Po odbiorze zatrzymujemy się. Kolejna faza to 7 — katalog lig / synchronizacja
GGG według dostępnego dostępu. Analiza logów na żywo 7C wymaga zakończenia 7B.
Symulacja stasha pozostaje opcjonalnym etapem 9.
