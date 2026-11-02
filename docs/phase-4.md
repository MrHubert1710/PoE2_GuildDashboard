# Faza 4 — wyliczone ruchy i analiza ilościowa

Status: implementacja zakończona, oczekuje odbioru manualnego.
Faza 3 została odebrana poleceniem przejścia dalej. Faza 5 nie jest rozpoczęta.

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

Filtry historii konta, zakładki, przedmiotu i dni UTC działają również na sumy.
Obliczenia zawsze odtwarzają całą historię przed zastosowaniem filtrów:
zmiana gracza/dnia nie kasuje poprzedniego stanu stosu. Stan końcowy obejmuje
całą zapisaną historię i respektuje filtr zakładki/przedmiotu; nie ograniczamy
go datą ani graczem. Jest to opisane przy tym widoku. Nie jest to kompletny
inwentarz gildii: brak pozycji lub nieznana ilość nie dowodzi pustej skrytki.

Widok i strona analizy są w URL jako analysis / analysis_page. Zmiana języka
nie przelicza danych. Daty w tabeli i analizie mają strefę wybraną dla ligi;
filtry nadal opisują całe dni UTC. Strefa nie zmienia kolejności zdarzeń.

## Izolacja lig i ustawienia gildii

Każda liga ma własną historię, projekcje, ruchy i stan. Wspólne pliki SQLite
zawierają oddzielne zbiory powiązane przez league_id; nie ma globalnego stanu
skrytek ani procesu resetującego stan innej ligi. Obliczenie ligi rozpoczyna
nowe, lokalne odtwarzanie wyłącznie jej zdarzeń. Nazwa zakładki wspólna dla
dwóch lig nigdy nie łączy ich stanów lub bilansów.

Każda nowa liga w grze zaczyna z pustymi skrytkami. To odrębny fakt od
pokrycia zachowanych logów: jeżeli obejmują tylko fragment ligi, nie zakładamy,
że skrytka była pusta przy pierwszym zapisanym zdarzeniu. Potwierdzone
history_complete=true pozwala przyjąć pusty początek; w obecnych archiwach
kompletność nie jest potwierdzona i początek pozostaje nieznany.

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

## Reguły algorytmu quantities-v1

- Parser obsługuje liczbę i x / × oraz zastany zapis Ă—; bez prefiksu ilość
  wynosi 1. Nazwa zaczynająca się od liczby, np. 7 League Boots, pozostaje
  nazwą. Niepoprawne, ujemne, ułamkowe lub przekraczające 10^9 ilości są
  nierozpoznane. Zero jest poprawnym stanem.
- Odtwarzanie jest rozdzielone przez ligę, źródło, kanoniczną zakładkę i x/y.
- Kolejność: czas UTC i numeryczne zewnętrzne ID jako legacy tie-breaker.
  Kilka wpisów z tym samym czasem/współrzędnymi bez jednoznacznej kolejności
  numerycznych ID daje ambiguous_order i nieznany stan, zamiast zgadywania.
- Added / Removed oznaczają jawny ruch +q / −q, zgodnie z modelem starego kodu.
  Sam ruch nie zawsze dowodzi całkowitego stanu stosu przy brakującym początku.
- Modified opisuje stan po zdarzeniu. Ten sam przedmiot, znana poprzednia
  ilość 20, nowa 15: delta −5 / Removed. Równe ilości: delta 0 / unchanged.
- Pierwszy Modified przy nieznanym stanie nie daje delty, ale ustala obserwowany
  stan do kolejnego wpisu. Po obserwowanym zerze można odtwarzać nowe dodania.
- Inny przedmiot w zajętych współrzędnych: inferred −stary / +nowy. Nie jest
  to twierdzenie, że użytkownik aktualnego wpisu na pewno wykonał pominiętą
  operację usunięcia; w podsumowaniach te ruchy są jawnie wywnioskowane.
- Usunięcie większej ilości niż znana lub konflikt przedmiotu daje ostrzeżenie
  state_conflict i nieznany stan. Jawny ruch źródłowy pozostaje zapisany.

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
Nie generujemy statycznego HTML, wykresów ani wyceny z przyszłych faz.

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

Wyniki: 96 testów backendu (23 nowe testy fazy 4), 37 testów Chromium
(5 nowych scenariuszy), 16 testów tłumaczeń oraz testy launchera/nginx —
wszystkie zakończone powodzeniem. TypeScript i produkcyjny build przechodzą.

Testy obejmują parser, granice historii, znane stany, zamianę przedmiotu,
niejednoznaczne ID, konflikty, aliasy, selekcję, izolację lig/źródeł/koordynatów,
pełną historię przed filtrami, stronicowanie, niezmienione surowe rekordy,
fencing publikacji, utratę aktualności i złożone FK. Testy dziedziczenia
sprawdzają wspólną konfigurację oraz niezależne stany lig i innych gildii.

Porównanie ze starym kodem wyciąga wyłącznie trzy funkcje arytmetyczne przez
AST, bez importowania private_config ani uruchamiania IO starej aplikacji.
Dla znanego pustego początku sumy i stan końcowy są zgodne. Test osobno
potwierdza zamierzoną różnicę dla pierwszego Modified o nieznanym początku.
Integracyjny test porównania używa sąsiedniego starego checkoutu; bez niego
jest pomijany, a samodzielne testy reguł nadal działają.

Audyt na tymczasowej kopii rzeczywistych danych, przy domyślnych wszystkich
zakładkach i niepotwierdzonym początku:

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
