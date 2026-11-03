# Faza 6 — ceny, wycena operacji graczy i stanu skrytek

Status: zaimplementowana i wdrożona; oczekuje odbioru manualnego.
Dzień odbioru technicznego: 2026-11-03. Następne fazy nie są rozpoczęte.

## Zachowanie w przeglądarce

Domyślnie wykres i tabela Podsumowania, Graczy oraz Skrytek pokazują wartość
operacji w Divine Orb. Przełącznik Quantity mode przywraca wybór przedmiotu
oraz dotychczasowe obliczenia ilościowe, włącznie z All. Zmiana ligi zachowuje
tryb ilość/wartość i historyczne/najnowsze; zeruje wybór przedmiotu i zoom.

Historyczne ceny są domyślne. Każdy podpisany ruch otrzymuje kurs z najnowszego
dostępnego punktu datowanego nie później niż jego wykonanie. Późniejsza zmiana kursu nie przeszacowuje
poprzednich ruchów. Tryb Current prices używa jednego, przypiętego zestawu
najnowszych dostępnych snapshotów kategorii danej ligi dla całej historii.
To najnowsze dostępne obserwacje, nie gwarancja wykonania transakcji po tej cenie.

Modele wyceny są rozdzielone:

- Players: suma podpisanych operacji danego gracza × cena w czasie każdej
  operacji. Późniejszy kurs nie zmienia wkładu; saldo gracza może być ujemne.
- Stashes: odtworzony stan ilościowy każdego przedmiotu × cena w danej chwili.
  Worker tworzy punkty zarówno po operacjach, jak i po zmianach cen. Stan
  i jego wycena są nieujemne. Zmiana kursu może zmieniać wartość bez operacji.
- Summary: suma wartości stanu widocznych skrytek; nie suma wkładów graczy.

Przykład: Alice dodaje 20 sztuk po 2 Divine, Buyer zabiera 5 po 3 Divine.
Salda to +40 i −15; ich suma to 25 Divine. Stan skrytki to 15 sztuk, więc
jej wartość wynosi 45 Divine. Gdy cena wzrośnie do 4 bez nowej operacji,
skrytka ma wartość 60, a salda graczy nadal +40 i −15. W trybie najnowszych
cen stały kurs stosuje się do obu modeli; suma graczy wraz z korektami może
wtedy być równa wartości stanu. To nie jest wymuszona zgodność historyczna.

Korekty rekonstrukcji pozostają osobną serią techniczną w Players. W Stashes
są częścią odtworzenia zawartości, a nie dodatkowym graczem lub drugą wyceną.
Wszystkie wpisy ledgeru tej samej transakcji są stosowane atomowo; przejściowe
podwójne usunięcie nie tworzy ujemnego stanu. Równoczesna zmiana kursów jest
atomowa również dla sumy skrytek. Kurs z danego czasu stosuje się przed
operacjami z identycznym timestampem. Nie zmienia to surowych logów GGG.

Filtr gracza obowiązuje w Players, ale jest ignorowany dla wyceny stanu
Stashes/Summary, z wyraźną informacją w interfejsie. Pozostali gracze nadal
zmieniają stan skrytki. Filtry przedmiotu i skrytek pozostają aktywne.
Daty wyznaczają wyświetlany przedział; wcześniejsze operacje nadal budują
stan początkowy. Ignorowane zakładki są nadal wyłączane przez projekcję.
Tabela stanu pokazuje ilość, wartość początkową, wartość końcową oraz zmianę;
nie nazywa zmiany wartości dodaniem lub zabraniem. Braki cen dotyczą
przechowywanych pozycji na końcu przedziału, a nie dawnych operacji.

Wykres, miniatury, filtry UTC, tooltip w dowolnym czasie i sumy działają
w obu modelach. Kolory, zwijanie i format dat zachowują ustawienia klienta.
Oś wartości obsługuje ułamki Divine. Tabele i braki cen mają paginację w URL.

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

Korekta fazy 6: poe.ninja udostępnia także pełną dostępną historię dzienną
przedmiotu, niezależnie od overview i krótkiego sparkline. Worker pobiera ją
dla nazw występujących w logach danej ligi oraz walut odniesienia:

- exchange/current/details?league=…&type=…&id=<detailsId> — pairs[].history
  zawiera timestamp i absolutny rate. Wybierana jest para z Divine, bez
  odwracania kursu ani mnożenia przez dzisiejszą cenę. Divine ma wartość 1.
- stash/current/item/history?league=…&type=…&id=<numeric id> — daysAgo/value.
  Datą odniesienia jest X-League-EndAt zakończonej ligi, a przy jego braku
  Date odpowiedzi HTTP. Ta kotwica jest przechowywana razem z odpowiedzią
  w cache i zachowywana po 304; późniejszy odczyt nie przesuwa historii.
  Wartość jest w core.primary. Przeliczenie innej waluty wymaga kursu
  historycznego z tego samego dnia; brak kursu nie uruchamia wyceny z dziś.

Przykład zweryfikowany na wykresie źródłowym: Perfect Chaos Orb, Runes of
Aldur, 2026-07-26: 6.11 Divine. Endpoint zwrócił 157 dziennych próbek od
2026-05-30 do 2026-11-02. To dzienna rozdzielczość dostawcy, a nie kurs
każdej pojedynczej transakcji w ciągu dnia. Punkt obowiązuje od oznaczonego
czasu UTC do następnego dostępnego punktu; przed pierwszym punktem cena
pozostaje nieznana. Nie interpolujemy ani nie cofamy późniejszego kursu.

Archiwalne, niedatowane ceny nie tworzą konfliktu z ceną datowaną nawet
przy zmianie nazwy kategorii (np. currency → Currency). Pozostają wyłącznie
rezerwowym źródłem najnowszej estymacji, gdy żadna datowana cena nie pasuje.

Surowa odpowiedź historii i kotwica dat są zapisane w niezmiennym snapshocie
history_daily. Poszczególne kursy mają własne price_quotes.effective_at oraz
klucz przedmiot+timestamp. Braki dni jednego przedmiotu nie usuwają cen innych
przedmiotów kategorii. Nowy overview nadal ma pierwszeństwo w najnowszej wycenie,
gdy jest nowszy niż ostatni punkt dzienny. Rozpoznawanie wariantów pozostaje
konserwatywne. Dostępność historii konkretnego przedmiotu zależy od dostawcy;
nie oznacza pełnego pokrycia wszystkich nazw z logów gildii.

Źródła sprawdzone 2026-11-03: [wykres Perfect Chaos Orb](https://poe.ninja/poe2/economy/runesofaldur/currency/perfect-chaos-orb)
i publiczne żądania ekonomii używane przez ten wykres oraz wykres stash.
Historia ekonomii nie jest opisana w tabeli endpointów overview; adapter
jest odseparowany i zachowuje poprzednie dane przy zmianie formatu.

Wdrożony backfill obu lig: Forbidden Rites — 299 historii i 16 230 dziennych
kursów (2026-09-04–2026-11-02); Runes of Aldur — 346 historii i 46 651 kursów
(2026-05-29–2026-11-02). Dla 13 żądań historii Runes of Aldur dostawca zwrócił
błąd transportu/HTTP; szczegóły przedmiotów są widoczne w źródłach cen.
Poprawne dane zostały opublikowane, brakujące nie są zastępowane ceną z dziś.

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
Historia dzienna ma osobny cache 24 h; aktualne overview nadal odświeża się
nie częściej niż raz na godzinę. Nie pobieramy całego katalogu przedmiotów:
historia dotyczy nazw obecnych w logach ligi i walut odniesienia.
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

Migracje 006–008, schemat 8:

- price_http_cache — cache transportu, ETag, terminy i kody błędów.
- price_catalogs / price_categories — wersje katalogu i aktywność kategorii.
- price_snapshots / price_quotes — niezmienne payloady, SHA-256, liga, źródło,
  czas pierwszej obserwacji, pewny/nieznany czas ceny, waluta i warianty.
- price_aliases — jawne aliasy nazw osobno dla każdej ligi.
- valuation_runs / valuation_lines — wersja algorytmu valuation-v3, przypięta
  projekcja ilościowa, rewizja cen, tryb i cena/snapshot użyte dla każdego ruchu.
- inventory_value_points — materializowane przez workera ilości i wartości
  pozycji po atomowych operacjach i zmianach cen; własne daty, przyczyny braku
  oraz FK do konkretnego źródła ceny. CHECK(quantity>=0); brak ukrytego
  przycinania ujemnych wartości. Niespójna projekcja zatrzymuje publikację.
  Odczyty filtrują gotowe punkty, zamiast wyceniać całą historię przy każdym GET.

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

Uzupełnienie historii bez kasowania cache i cen:

```sh
.venv/bin/python scripts/prices.py backfill
```

Polecenie omija wyłącznie lokalny znacznik świeżości zadania. Respektuje cache
HTTP, ETag i cooldown dostawcy, a worker publikuje wynik atomowo. Normalny fetch
cen również aktualizuje historię; backfill służy do pierwszego uzupełnienia.

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

- Po rozdzieleniu modeli: 193 testy backendu, 91 testów
  w Chromium oraz 16 testów tłumaczeń: zaliczone. Kontrola typów i build
  produkcyjny również zaliczone. Testy obejmują daty i kursy historyczne,
  kotwicę daysAgo po 304, izolację przedmiotów i pierwszeństwo nowszego overview.
- Publiczne HTTPS API obu lig: wartości końcowe tabel i wykresów są zgodne;
  historyczne punkty są używane według daty; nieznane ceny pozostają jawne.
- Zachowano 104 534 surowe transakcje i konfigurację lig/gildii bez zmian.
  Sumy SHA-256 wszystkich 56 istniejących plików cen pozostały identyczne.
- SQLite: integralność poprawna, brak naruszeń kluczy obcych, schemat 8.

## Poprawka precyzji tooltipa

Wykres wartości rezerwuje 88 px na oś Y, a ilościowy 65 px. Stare ręczne
przeliczanie kursora zakładało zawsze 65 px, więc tooltip pobierał stan
z przesuniętego czasu. Na krótkich spadkach był to już stan po odbiciu.
Czas kursora wyznacza teraz transformacja narysowanej osi ECharts
(convertFromPixel); containPixel wyklucza marginesy osi z obszaru tooltipa.
Odczyt nadal dotyczy dowolnego czasu, również pomiędzy snapshotami.

Odtworzony przypadek: Runes of Aldur, JohnnyKremowka, 2026-07-09
14:00:20–14:00:24 UTC: −6134.14223069. API zwraca właściwy stan;
regresja obejmuje trafienie w krótki spadek w trybie wartości i ilości,
zmianę szerokości okna oraz opuszczenie obszaru danych. Zaliczone 22 testy
wykresów oraz build produkcyjny z kontrolą typów. Na wdrożonym wykresie
zweryfikowano tooltip −6134.14223069 w 14:00:22 UTC.

## Odbiór manualny

1. Odświeżyć stronę: domyślnie Value mode i ceny historyczne. Sprawdzić wykres
   i tabelę oparte na pobranej historii dziennej oraz listę pozostałych braków cen.
2. Włączyć Current prices: pojawiają się tabela i interaktywny wykres wartości
   w Divine. Przełączyć Summary / Players / Stashes, filtry i ligę.
3. Sprawdzić zoom obiema miniaturami, tooltip między operacjami, sumę serii
   oraz oddzielne Korekty rekonstrukcji w Players. Sprawdzić, że zmiana ceny
   bez operacji zmienia Stashes, ale nie Players. Filtr gracza nie może
   zmieniać stanu skrytek. Reload zachowuje tryb wyceny w URL.
4. Włączyć Quantity mode: wracają ilości, wybór przedmiotu i All; projekcja
   ilościowa nie jest przebudowywana wskutek zmiany sposobu wyceny.
5. Po zalogowaniu sprawdzić System settings → Źródła cen, katalog, snapshoty
   i informację o świeżym cache przy ponownym Fetch prices. Preferencje
   przeglądarki nadal są lokalne. Przełączyć PL/EN i szerokość mobilną.

Po odbiorze zatrzymujemy się. Kolejna faza to 7 — katalog lig / synchronizacja
GGG według dostępnego dostępu. Analiza logów na żywo 7C wymaga zakończenia 7B.
Symulacja stasha pozostaje opcjonalnym etapem 9.
