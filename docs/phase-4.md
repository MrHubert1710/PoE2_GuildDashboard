# Faza 4 — wyliczone ruchy i analiza ilościowa

Status: odebrana przez użytkownika poleceniem przejścia do fazy 4b.
Faza 3 została odebrana poleceniem przejścia dalej. Faza 5 nie jest rozpoczęta.
Układ i nawigację zmienia [faza 4b](phase-4b.md); poniżej opis reguł i wyników fazy 4.

## Rezultat w przeglądarce

W Historii źródłowa Akcja GGG i opis przedmiotu pozostają zachowane. Obok są:

- Zmiana ilości: np. +5 / −3, bez zgadywania brakującej wartości.
- Wyliczona akcja: Dodano / Usunięto / Bez zmiany ilości / Nieustalona.
- Zamiana przedmiotu: dwa osobne ruchy z nazwami przedmiotów, oznaczone
  jako wywnioskowane; nie sumujemy różnych przedmiotów w jedną deltę.
- Podstawa obliczenia: poprzednia/następna ilość, powód i sposób ustalenia.

Panel Analiza ilościowa ma widoki Podsumowanie, Gracze, Skrytki i Odtworzony
stan. Sumy są grupowane po przedmiocie; gracze i skrytki dodają odpowiedni
wymiar grupowania. Pokazujemy dodane/zabrane sztuki, bilans oraz osobno
liczbę sztuk wywnioskowanych, już wliczonych do sumy. Nieustalone ruchy
nie są traktowane jako zero ani doliczane do sum.

Filtry historii konta, listy zakładek, przedmiotu i dni UTC działają również na sumy.
Filtr zakładek jest domyślnie zwinięty; kliknięcie rozwija listę niezależnych
checkboxów. Lista pozostaje otwarta przy zaznaczaniu wielu nazw, a Escape
lub kliknięcie poza filtrem zamyka ją i zachowuje wybór. Wybrane nazwy tworzą sumę
zbiorów (OR). Brak wyboru oraz przycisk Wszystkie skrytki oznaczają brak
ograniczenia. Wybór zatwierdza Zastosuj filtry; formularz można edytować bez
zmiany bieżącego wyniku. Lista jest zachowywana po reloadzie i Back/Forward.
URL/API używa powtarzanego parametru, np. stash=Main&stash=Special.
Pojedynczy stash jest nadal obsługiwany. Zmianę listy checkboxów sprawdzono
również na publicznej stronie: dwie nazwy, zgodne sumy historii/analizy,
reload i układ mobilny PL/EN. Nazwy z przecinkami nie są dzielone;
API deduplikuje nazwy i aliasy, akceptuje do 100 parametrów po 200 znaków.
Obliczenia zawsze odtwarzają całą historię przed zastosowaniem filtrów:
zmiana gracza/dnia nie kasuje poprzedniego stanu stosu. Stan końcowy obejmuje
całą zapisaną historię i respektuje filtr zakładki/przedmiotu; nie ograniczamy
go datą ani graczem. Jest to opisane przy tym widoku. Nie jest to kompletny
inwentarz gildii: brak transakcji oznacza 0 według przyjętego modelu; błędy
lub konflikty danych nadal mogą powodować nieznany stan.

Widok i strona analizy są w URL jako analysis / analysis_page. Zmiana języka
nie przelicza danych. Daty w tabeli i analizie mają strefę wybraną dla ligi;
filtry nadal opisują całe dni UTC. Strefa nie zmienia kolejności zdarzeń.

## Izolacja lig i ustawienia gildii

Każda liga ma własną historię, projekcje, ruchy i stan. Wspólne pliki SQLite
zawierają oddzielne zbiory powiązane przez league_id; nie ma globalnego stanu
skrytek ani procesu resetującego stan innej ligi. Obliczenie ligi rozpoczyna
nowe, lokalne odtwarzanie wyłącznie jej zdarzeń. Nazwa zakładki wspólna dla
dwóch lig nigdy nie łączy ich stanów lub bilansów.

Każda liga i każde pole zaczynają od 0. Brak transakcji oznacza 0, również
w archiwach bez potwierdzonego pokrycia logów. Jest to przyjęta reguła
obliczeń, niezależna od history_complete. Znacznik kompletności nadal opisuje
pokrycie źródła; nie warunkuje już zerowego stanu początkowego.

Wspólna może być konfiguracja nazw, aliasów, wyboru zakładek i strefy czasu:

1. Domyślne ustawienia gildii dziedziczone przez ligi tego samego źródła.
2. Jawne nadpisanie ustawień konkretnej ligi.
3. Możliwość przywrócenia dziedziczenia.

Gildia jest obecnie rozpoznawana przez jedno logiczne sources.id powiązane
z danymi ligi. source-key w importerze od fazy 1 oznacza logiczną gildię/źródło.
Dla ligi powiązanej z kilkoma niezależnymi źródłami nie zgadujemy wspólnej gildii:
można nadal zapisać lokalne ustawienia ligi. Przyszły katalog lig bez danych
będzie wymagał jawnego powiązania z gildią przy integracji źródła.

Domyślnie wszystkie zapisane zakładki są uwzględniane, a strefą jest UTC.
Zastana konfiguracja starej aplikacji pozostaje zachowana jako pochodzenie,
ale nie jest automatycznie promowana do zatwierdzonych ustawień archiwów.
W formularzu można wybrać Domyślne ustawienia gildii i zapisać wspólny wybór
znaczących zakładek. Nazwa nieobecna w konkretnej lidze jest dozwolona i nie
jest błędem; będzie stosowana tam, gdzie występuje. Pusta lista wyklucza
wszystkie zakładki; null oznacza wszystkie, również przyszłe.

Alias jest jawną regułą tożsamości zakładki w obrębie źródła i ligi. Dwie surowe
nazwy z tym samym aliasem współdzielą odtwarzane współrzędne tej ligi. Łańcuchy
i cykle aliasów są odrzucane. Nazwy surowe nadal są w źródłowej tabeli.
Zapis ustawień jest chroniony hashami przed nadpisaniem zmian innej karty.

## Pola tekstowe w stylu VS Code

Gracz i Przedmiot mają przyciski wewnątrz pola:

- Aa — uwzględnianie wielkości liter.
- Podkreślone ab — dopasowanie całych słów lub fraz, z granicami Unicode \w.
- .* — interpretacja wpisu jako wyrażenia regularnego.

Każdy tryb jest niezależny dla każdego pola i ma widoczny stan oraz etykietę
aria-pressed. Domyślnie wszystkie są wyłączone: wyszukiwanie dosłownego
fragmentu, ignorujące wielkość liter. Zmiany zatwierdza Zastosuj filtry.
Całe słowa i Aa działają również bez regexów; znaki regex pozostają wtedy
literalne. Ustawienia są zachowane w URL/reload/Back/Forward i czyszczone
przez Wyczyść filtry. Na telefonie pola tekstowe zajmują pełną szerokość.

Flagi URL/API: account_regex, account_case, account_word oraz odpowiedniki
item_regex, item_case, item_word. Przyjmują 0/1; wyłączone są pomijane w URL.
Regex wpisuje się bez separatorów /…/ i flag JavaScript po separatorze.
Backend stosuje regex.VERSION0, domyślnie z pełnym Unicode case-foldingiem;
Aa wyłącza domyślne ignorowanie wielkości liter. Literalne wyszukiwanie bez
całych słów nadal korzysta z dotychczasowego instr/casefold w SQLite.

Historia filtruje źródłowy opis przedmiotu (może zawierać prefiks ilości),
a analiza — znormalizowane nazwy przedmiotów/ruchów, tak jak w zwykłym trybie.
Przy ^/$ należy uwzględnić tę różnicę. Filtry analizy są stosowane po odtworzeniu
całej historii; widok stanu końcowego nadal nie przyjmuje filtra gracza ani dat.

Błędny wzorzec daje 400 invalid_account_regex / invalid_item_regex. Limit
czasu dopasowania daje 400 regex_timeout i czytelny komunikat, bez zwracania
częściowych wyników ani mylenia problemu z awarią SQLite. Wzorce mają limit
200 znaków, pojedyncze dopasowanie 25 ms, a wspólny budżet pracy dopasowań
obu pól wynosi 0,5 s na żądanie. Wyniki dla powtarzających się tekstów są
cache'owane wyłącznie w obrębie żądania, do 4096 wpisów na pole.

Zależność regex==2026.9.29 jest zapisana w required.txt. Obsługa limitu czasu
i Unicode pochodzi z [dokumentacji autora biblioteki](https://pypi.org/project/regex/).
Testy obejmują wzorce, błędy, kosztowne dopasowania, Unicode, niezależność
trybów, filtrowanie analiz i stanu, klawiaturę, URL i mobilny układ pól.
Publiczny smoke test przez nginx potwierdził połączenie Aa + całe słowa +
regex na rzeczywistych danych, zgodne liczniki historii/analizy, reload,
komunikat błędnego wzorca oraz układ desktop/mobile bez błędów JavaScript.

## Reguły algorytmu quantities-v3

- Parser obsługuje liczbę i x / × oraz zastany zapis Ă—; bez prefiksu ilość
  wynosi 1. Nazwa zaczynająca się od liczby, np. 7 League Boots, pozostaje
  nazwą. Niepoprawne, ujemne, ułamkowe lub przekraczające 10^9 ilości są
  nierozpoznane. Zero jest poprawnym stanem.
- Odtwarzanie jest rozdzielone przez ligę, źródło, kanoniczną zakładkę i x/y.
- Kolejność: czas UTC i numeryczne zewnętrzne ID jako legacy tie-breaker.
  Kilka wpisów z tym samym czasem/współrzędnymi bez jednoznacznej kolejności
  numerycznych ID daje ambiguous_order i nieznany stan, zamiast zgadywania.
- Added oznacza jawny ruch +q. Pierwszy Added: 10 daje stan 10 od zera.
- Źródłowy Removed oznacza całkowite opróżnienie slotu: ilość po operacji
  zawsze wynosi 0, a slot nie ma przedmiotu. Ruch −q zachowuje ilość ze źródła.
  Reguła dotyczy źródłowego Removed; ujemna delta Modified pozostawia nowy stos.
- Modified opisuje stan po zdarzeniu. Ten sam przedmiot, znana poprzednia
  ilość 20, nowa 15: delta −5 / Removed. Równe ilości: delta 0 / unchanged.
- Pierwszy Modified: 20 daje deltę +20 i Added, od początkowego zera.
  Modified: 0 daje deltę 0. Brak zdarzeń pozostawia stan 0.
  Po błędzie lub konflikcie stan może stać się nieznany; następny Modified
  ustala wtedy nowy stan bez wyliczania nieznanej zmiany.
- Inny przedmiot w zajętych współrzędnych: inferred −stary / +nowy. Nie jest
  to twierdzenie, że użytkownik aktualnego wpisu na pewno wykonał pominiętą
  operację usunięcia; w podsumowaniach te ruchy są jawnie wywnioskowane.
- Removed przy innej znanej ilości lub innym przedmiocie daje ostrzeżenie
  removed_state_conflict, ale nadal opróżnia slot i ustala 0. Nie przenosi
  nieznanego stanu na późniejsze dodania. Niepoprawna ilość w Removed daje
  ostrzeżenie invalid_quantity bez wyliczonego ruchu, ale slot także jest pusty.
- Niejednoznaczna kolejność nadal nie pozwala określić stanu po całej grupie.

Nie wszystkie luki są wykrywalne z logów. quantity_before / quantity_after
mogą być null niezależnie od znanej delty. Rozróżniamy pewność source, derived,
inferred, unknown i excluded. Błędy/niepewność są danymi projekcji, a nie
powodem nadpisania źródłowej akcji.

## Model danych i odtwarzalność

Migracja 003 podnosi schemat do 3 i dodaje:

- quantity_runs — liga, rewizja wejścia, hash ustawień i założenia o początku,
  wersja algorytmu, czas, liczby zdarzeń nieustalonych/wywnioskowanych/wykluczonych.
- event_quantities — interpretacja każdego zdarzenia, ilość przed/po, delta,
  akcja zastępcza, powód i pewność.
- quantity_movements — zero lub wiele ruchów powiązanych ze zdarzeniem.
- quantity_state — ostatni odtworzony stan odwiedzonych współrzędnych.
- guild_quantity_defaults — konfiguracja dziedziczona przez ligi gildii;
  nadpisanie ligi jest w jej settings_json.quantity_settings.

Złożone klucze obce uniemożliwiają przypięcie zdarzenia innej ligi do projekcji,
również przy błędzie bezpośredniego zapisu SQL. quantity_movements dziedziczy
powiązanie przez event_quantities. Poza wyborem i aliasami nie ma wspólnego
stanu przedmiotów pomiędzy ligami.

Źródłowe transactions, raw_json, akcje i opisy nie są modyfikowane. raw_json
odwzorowuje obecny rekord CSV; to nie zapis oryginalnej odpowiedzi HTTP GGG.
Fetcher przyszłej fazy integracji nadal musi zachowywać oryginalne odpowiedzi
API, aby spełnić wymaganie audytu 1:1. Faza 4 nie implementuje fetchera.

Identyfikator projekcji wynika z ligi, rewizji wejścia, ustawień/założenia
początkowego i wersji algorytmu. Poprzednie projekcje pozostają w bazie.
Zmiana ustawień, kompletności historii lub wejścia powoduje stale; nie
podpinamy poprzednich wyników do nowej rewizji. Zgodny istniejący wynik jest
wykorzystywany ponownie. Baza może rosnąć wraz z kolejnymi wariantami ustawień;
nie dodano automatycznego usuwania starszych projekcji.

## Worker, API i spójność

Job kind=quantities jest lokalnym zadaniem kolejki z fazy 3 i działa także dla
archiwów. Nie zużywa limitu automatycznych odczytów GGG. Obliczenia powstają poza
transakcją zapisu; publikacja całej projekcji sprawdza lease, rewizję i ustawienia.
Zmiana danych lub konfiguracji w trakcie pracy wycofuje publikację i wymaga retry.
Wykresy i wycena są opisane w dalszych fazach.

GET /api/leagues/<id>/quantities przyjmuje view=summary/players/stashes/state,
account/stash/item/from/to, page i page_size=25/50/100, opcjonalnie revision
oraz projection_id. Wyniki są stronicowane. Stan nie przyjmuje filtrów gracza
ani dat, zamiast ignorować je po cichu. GET nie generuje zadań.

GET/PUT /api/leagues/<id>/quantity-settings czyta i zapisuje ustawienia.
PUT wymaga JSON, expected_hash oraz settings; scope=league/guild/inherit.
Zapis gildii wymaga również expected_guild_hash. Błędy mają stabilne kody;
niezgodna wersja daje 409. Obcy Origin jest odrzucany.

Dotychczasowe /transactions zawiera teraz projection oraz quantity przy
wierszach, dla których istnieje zgodny wynik. Dane źródłowe i paginacja
pozostają oddzielone od projekcji. Frontend wykrywa zmianę ustawień przez
polling statusu i przeładowuje właściwe metadane bez przeładowania strony.
Daty generowania w panelu Odświeżanie uwzględniają gotową projekcję ilościową,
co jest odrębne od synchronizacji GGG i weryfikacji lokalnej.

## Walidacja

```sh
.venv/bin/python -m unittest discover -s tests -q
bash tests/test_service.sh
npm --prefix frontend run test:locales
npm --prefix frontend run build
npm --prefix frontend run test:browser
```

Wyniki: 110 testów backendu (37 nowych testów fazy 4), 44 testy Chromium
(12 nowych scenariuszy), 16 testów tłumaczeń oraz testy launchera/nginx —
wszystkie zakończone powodzeniem. TypeScript i produkcyjny build przechodzą.

Testy obejmują parser, granice historii, znane stany, zamianę przedmiotu,
niejednoznaczne ID, konflikty, aliasy, selekcję, izolację lig/źródeł/koordynatów,
pełną historię przed filtrami, stronicowanie, niezmienione surowe rekordy,
fencing publikacji, utratę aktualności i złożone FK. Testy dziedziczenia
sprawdzają wspólną konfigurację oraz niezależne stany lig i innych gildii.

Porównanie ze starym kodem wyciąga wyłącznie trzy funkcje arytmetyczne przez
AST, bez importowania private_config ani uruchamiania IO starej aplikacji.
Dla pustego początku sumy i stan końcowy są zgodne. Test potwierdza
również deltę +20 dla pierwszego Modified: 20.
Integracyjny test porównania używa sąsiedniego starego checkoutu; bez niego
jest pomijany, a samodzielne testy reguł nadal działają.

Historyczny audyt quantities-v1 (przed zmianą reguły początku na 0),
na tymczasowej kopii rzeczywistych danych, przy wszystkich zakładkach:

| Liga | Zdarzenia | Nieustalone ruchy | Wywnioskowane zdarzenia | Ostrzeżenia | Grupy przedmiotów |
| --- | ---: | ---: | ---: | ---: | ---: |
| Forbidden Rites | 15 344 | 253 | 113 | 47 | 2 266 |
| Runes of Aldur | 89 190 | 901 | 214 | 154 | 6 401 |

Przebieg wraz z odczytem wyników trwał około 0,3 s i 1,7 s na tym serwerze.
To pojedynczy pomiar, nie gwarantowany czas. Audyt nie zmieniał oryginalnej bazy
ani starego katalogu. Wyniki nie twierdzą, że historyczny inwentarz jest kompletny.

## Wdrożenie

Zatrzymano wyłącznie nową usługę, wykonano SQLite backup do
data/poe2guild.before-phase4.sqlite i zastosowano migrację 3. Web i worker
działają na porcie 9002. Worker przygotował dwie niezależne projekcje.
Porównanie skrótów wszystkich kolumn transactions z kopią sprzed migracji
potwierdza identyczność 104 534 rekordów; PRAGMA foreign_key_check przechodzi.

Smoke test publicznego adresu przez nginx potwierdził prawdziwy wpis Modified
z ujemną deltą i akcją Removed, rozwijane wyjaśnienie, cztery widoki obu lig,
PL/EN, układ mobilny i brak błędów JavaScript. Nie zmieniano ustawień gildii
w produkcji podczas testu; testy ich zapisu działały na bazie tymczasowej.
Stary projekt, jego dane i proces nie zostały zmienione.

## Odbiór manualny

1. Otwórz http://dyyyl.ovh/poe2guild/?lang=pl. Zobacz dwie nowe kolumny historii.
2. Znajdź Modified z rozpoznaną zmianą, rozwiń Podstawę obliczenia i porównaj
   ilość przed/po, znak i akcję zastępczą. Oryginalna Akcja GGG pozostaje widoczna.
3. Sprawdź Podsumowanie / Gracze / Skrytki / Odtworzony stan i ich paginację.
4. Zastosuj filtry; stan końcowy jawnie pomija filtr gracza/daty.
5. W ustawieniach wybierz zakres Tylko ta liga lub Domyślne ustawienia gildii.
   Nazwy i wybór zakładek mogą być wspólne; historia każdej ligi jest niezależna.
6. Zmień strefę czasu albo wybór zakładek, zapisz, poczekaj na przeliczenie.
   Surowe zdarzenia nie powinny się zmienić. Sprawdź PL/EN i wersję mobilną.

Po odbiorze następny osobny zakres to faza 5: interaktywne wykresy.


## Korekta po fazie 4b — początek od zera

Na polecenie użytkownika model quantities-v2 zawsze inicjuje każde pole ligi
zerem. Nie ma transakcji — nie ma ruchu, stan wynosi 0. Puste wyniki i sumy
pozostają zerowe; nie materializujemy w bazie wszystkich nieużytych pól.
Nie jest to zamiana każdego null na 0: null po konflikcie, błędzie ilości,
niejednoznacznej kolejności lub przy mieszanej wymianie przedmiotu nadal ma
znaczenie i jest wyjaśniany w interfejsie.

Nowa wersja algorytmu unieważnia stare projekcje przy odczycie, bez ich usuwania.
Przeliczane są tylko projekcje; transactions i raw_json pozostają niezmienione.
Schemat SQLite pozostaje w wersji 3. history_complete nie jest nadpisywane.
Testy obejmują pierwszy Added/Modified, zerowe ruchy, pustą historię, izolację
lig i źródeł, niepotwierdzoną/niepełną/pełną historię oraz zachowanie starych
projekcji po zmianie algorytmu.


Po wdrożeniu quantities-v2 obie ligi mają gotowe projekcje: Forbidden Rites
15 344 zdarzenia / 67 nieustalonych ruchów, Runes of Aldur 89 190 / 218.
Pozostałe nieustalone przypadki wynikają z konfliktów lub niejednoznacznych
danych, a nie domyślnego nieznanego początku. Kopia przed zmianą:
data/poe2guild.before-zero-baseline.sqlite. Skrót wszystkich kolumn 104 534
transakcji przed i po przeliczeniu jest identyczny.

Końcowa walidacja obu poprawek po fazie 4b: 113 testów backendu,
54 przeglądarkowe i 16 tłumaczeń zakończone powodzeniem, build TypeScript/Vite
poprawny. Publiczny HTTP nginx potwierdza nową wersję, początek 0 w obu ligach
oraz wspólny formularz włączania/wyłączania i zmiany nazw skrytek w PL/EN/mobile.


## Korekta Removed — quantities-v3

Użytkownik doprecyzował semantykę GGG: Removed usuwa cały przedmiot ze slotu,
a częściową zmianę stosu opisuje Modified. Poprzednie odejmowanie ilości ze
stanu slotu było błędne. Po Removed zapisujemy ilość 0 i pustą nazwę w projekcji
quantity_state (schemat 3 wymaga tekstu), a kolejne zdarzenie ma before_item=null.
Oryginalny przedmiot i ilość pozostają w transakcji, adnotacji i ruchu −q.
Puste sloty są pomijane w tabeli aktualnego stanu.

Regresja odtwarza wskazaną sekwencję pozycji 34,0: Removed 3 Orb of Extraction,
Added/Removed Core Destabiliser, Added/Removed 4 Vaal Siphoner. Końcowy stan
jest pusty (0), a Vaal Siphoner nie występuje w tabeli niepustych slotów.
Zmiana wersji algorytmu wymusza nowe projekcje obu lig bez usuwania poprzednich.


Walidacja quantities-v3: 120 testów backendu, 57 przeglądarkowych,
16 tłumaczeń i build TypeScript/Vite zakończone powodzeniem. Obie produkcyjne
projekcje zostały przeliczone przez workera. Publiczny nginx potwierdził
quantity_after=0 dla Removed 4 Vaal Siphoner (ID 3192208954) oraz brak pozycji
34,0 w API i widoku stanu. W bazie slot ma item_name='' i quantity=0.
Skrót wszystkich kolumn 104 534 źródłowych transakcji przed i po wdrożeniu
pozostał identyczny. Ustawienia lig i gildii nie były modyfikowane.
