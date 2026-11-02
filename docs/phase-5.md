# Faza 5 — wykresy balansu i zwarty panel

Status: poprawki po pierwszym odbiorze wdrożone do ponownej weryfikacji.
Faza 6 (wycena) nie jest rozpoczęta. Poniższy opis zastępuje pierwszy wariant
wykresów sum dodanych/usuniętych w regularnych przedziałach.

## Wykres i czas

Wykres pokazuje tylko narastający balans ustalonych ruchów. Podsumowanie ma
jedną serię gildii; Gracze i Skrytki mają oddzielne serie kont lub kanonicznych
nazw zakładek. Stała legenda nad wykresem pokazuje nazwy, kolory i checkboxy poszczególnych grup.
Nie ma osobnych serii Added/Removed. Różnica między widokami dotyczy danych,
a nie samego tytułu. Balans gracza to jego wkład netto od początku historii,
a nie zawartość jego ekwipunku. Brakujące operacje nadal ograniczają pewność.

Punkty odnoszą się do czasów rzeczywistych operacji i są uporządkowane według
czasu, numerycznego GGG ID, transakcji i sekwencji ruchu. Linia jest schodkowa.
Dodanie i natychmiastowe zabranie nie znika jako suma zero; także dwa ruchy
z identycznym czasem zachowują kolejność i pionowy skok balansu. Znaczniki
minimum/maksimum pomagają zobaczyć krótkie ekstrema.

Dla dużej liczby zdarzeń backend dzieli aktualny zakres na przedziały i wybiera
w każdym pierwszy, minimalny, maksymalny i ostatni balans, zachowując ich
oryginalną kolejność i czas. To próbkowanie, nie sumowanie ruchów w przedziale.
Nie gwarantuje pokazania każdego drobnego ekstremum przy tysiącach operacji;
po przybliżeniu API pobiera szczegóły wybranego zakresu. Gdy operacji jest mniej
niż limit, wszystkie są zwracane. Oś czasu zmienia opisy aż do sekund i
milisekund, zależnie od zoomu. Nie wstawiamy regularnej siatki zerowych punktów.

Zoom i pan wywołują odczyt dokładniejszych danych po 180 ms debounce. Obecny
wykres pozostaje widoczny w trakcie pobierania dokładniejszych punktów.
Spóźniona odpowiedź starszego zoomu lub poprzedniej ligi nie zastępuje nowej.
Zakres i wybór grup są w URL; refresh/reload ich nie zeruje. Zmiana ligi
rozpoczyna jej własny kontekst. Tooltip i rozwijana tabela punktów pozostają.

Filtr dnia i zoom nie zerują balansu: początek wykresu zawiera sumę wcześniejszych
ruchów pasujących do gracza, skrytek i przedmiotu. Podsumowanie ruchów tabeli
nadal dotyczy tylko wybranego okresu, więc może różnić się od końcowego balansu
o wartość wniesioną sprzed tego okresu. Nie zmieniono quantities-v3 ani
semantyki źródłowego Removed opróżniającego slot.

## Strefa czasu we wszystkich widokach

Wybrana strefa ligi obejmuje daty tabeli, wykresu, tooltipa, opisów,
Diagnostyki oraz filtrów. Dni from/to to dni kalendarzowe w tej strefie,
z końcem to włącznie. Backend przelicza lokalną północ i następną lokalną
północ na granice UTC; uwzględnia DST (np. dzień 23-godzinny w Europe/Warsaw).
Przesunięcia UTC±HH:MM i skróty PST/PDT nadal są stałymi przesunięciami,
a nazwy IANA stosują reguły strefy. Po zakończeniu gestu zakres automatycznie aktualizuje filtry dni w strefie ligi.
Zaokrąglenie na zewnątrz odpowiada dostępnej w formularzu dokładności do dnia;
wykres i miniatura zachowują dokładny zakres w milisekundach. Osobny przycisk
zastosowania zakresu został usunięty.

Źródłowe timestampy i zapis chart_from/chart_to pozostają w UTC. Zmienia się
interpretacja istniejących URL from/to dla ligi ze strefą inną niż UTC:
odpowiadają teraz ustawieniu ligi i etykietom formularza. Nie ma migracji danych.

## Układ i zwijanie

Panel wykorzystuje pełną szerokość okna z niewielkim marginesem. Nagłówek
zawiera wybór ligi, jej status i skrócony licznik (np. 60,6k), odświeżenie,
pobranie historii i język. Pełny licznik jest w tooltipie. Ten sam pill jest
w każdej opcji listy lig. Usunięto powtórzoną nazwę ligi, tytuł widoku, licznik,
status archiwizacji i osobny przycisk Stan synchronizacji; szczegóły są nadal
w Diagnostyce. Autofetch, manual fetch i polling nadal działają.

Filtry są zwarte, a wykres jest widoczny bez przewijania na typowym desktopie.
Wykres i tabela są niezależnymi panelami z możliwością zwinięcia. Metadane
liczby zdarzeń, generacji, reguł filtrów i lokalnego przeliczenia są w Dodatkowych
informacjach pod tabelą, domyślnie zwinięte. Informacje techniczne wykresu i jego
tabela punktów także są zwinięte. Stan otwarcia paneli jest lokalną preferencją
sessionStorage, osobno dla ligi/widoku, i pozostaje po reloadzie. Nie zmienia
wspólnej konfiguracji analizy. Mobilnie zachowane jest poziome przewijanie
nawigacji i tabel bez przepełniania całego dokumentu.

## API

GET /api/leagues/{id}/quantity-series obsługuje dotychczasowe filtry,
revision/projection_id, series_item i max_points (24–600), a także:

- view=summary/players/stashes;
- window_start/window_end — całkowite milisekundy UTC, koniec wyłączny.

Odpowiedź zawiera projection, timezone, unit=item_count, wybrany item i
katalog do 50 najaktywniejszych nazw, bounds całego filtrowanego zakresu,
window aktualnego odczytu, sampled/resolution_ms oraz series. Każda seria ma
stabilny id, name, opening_balance, closing_balance, liczbę operacji i punkty
{timestamp,balance}. Totals nadal opisuje ustalone ruchy w całym filtrowanym
okresie. Unresolved_events jest oddzielne; nie dopisujemy nieznanych ilości do
balansu. Format nie zawiera opcji ECharts.

Przesyłamy najwyżej 100 grup; przekroczenie jest oznaczane series_truncated.
Domyślny limit to 240 punktów na grupę, dodatkowo dzielimy budżet około 6000
punktów między widoczne grupy. Nie wysyłamy całej historii do przeglądarki.
Na serwerze czytane są ruchy wybranego przedmiotu do końca zakresu, również
poprzedzające początek, aby policzyć poprawny balans otwarcia. GET jest read-only,
nie uruchamia workera ani fetchera. Starsza postać points/added/removed została
zastąpiona przez series/balance w wewnętrznym API frontendu; po wdrożeniu
należy odświeżyć kartę, aby załadować zgodny frontend.

## Granice wyceny — faza 6

Wybór pojedynczego przedmiotu pozostaje tymczasowy, żeby nie dodawać sztuk
różnych przedmiotów. Faza 6 zastąpi go wartością wszystkich operacji:

- domyślnie każda podpisana operacja jest wyceniana tylko ceną z czasu jej realizacji;
- alternatywny tryb przelicza wszystkie operacje najnowszym zestawem cen ligi;
- ceny późniejsze nie mogą być po cichu podstawiane w trybie historycznym;
- snapshoty i brak wyceny pozostają jawne, a serie graczy/skrytek zachowują balans.

Ten zakres jest zapisany w implementation-plan.md; nie wdrożono jeszcze
adaptera cen ani przełącznika wyceny. Stary projekt i źródłowe logi są nienaruszone.
SQLite nadal ma schemat 3, a projekcje wersję quantities-v3.

## Walidacja i odbiór

Testy obejmują zerujące się operacje o tym samym czasie, zachowanie ekstremów,
zmianę rozdzielczości po zoomie, niezależne serie grup, bilans otwarcia, limity,
regex i aliasy, strefy stałe i DST, zgodność historii/raportu/wykresu, zwijanie,
zwarty desktop i mobile oraz ignorowanie spóźnionych odpowiedzi.

Do odbioru: odśwież stronę; sprawdź Graczy i Skrytki, przybliż krótki fragment,
porównaj ekstrema z historią, zwiń wykres/tabelę i odśwież, zmień strefę ligi
oraz zastosuj zakres do filtrów. Dalsza faza wymaga osobnego polecenia użytkownika.


Końcowa walidacja poprawek: 130 testów backendu, 64 przeglądarkowe i 16 tłumaczeń
zakończone powodzeniem. Po ostatnich poprawkach kolorów i przepełnienia SVG
powtórzono 6 testów wykresów — wszystkie przeszły. Build TypeScript/Vite poprawny.

Publiczny nginx potwierdził trzy widoki dla obu lig. Runes of Aldur ma dla
domyślnego Verisium 7 serii graczy (514 punktów) i 2 skrytek (236 punktów),
a Podsumowanie 1 serię (176 punktów). Końcowe salda sumują się do raportu.
Zoom odczytuje węższy zakres, a nagłówek, zwijanie, kolory, PL i mobile działają
na rzeczywistych danych. Na desktopie 1440 px wykres zaczyna się przed 320 px
wysokości strony; obszar roboczy przekracza 1350 px szerokości. Sprawdzenie
API wraz z kontrolnym odczytem raportu trwało w pojedynczych próbach około
45–57 ms dla Forbidden Rites i 246–251 ms dla Runes of Aldur; to pomiar tego
serwera, nie gwarancja czasu. JSON mieścił się między około 7 i 25 KB.

Skróty wszystkich kolumn 104 534 transakcji oraz zapisanych ustawień gildii/lig
przed i po wdrożeniu są identyczne. Nie zmieniono cen, projekcji ani schematu.
Poprawki fazy 5 oczekują ponownego odbioru; faza 6 pozostaje niewdrożona.


## Korekta miniatury i przesuwania

Podgląd miniatury ma własne, stałe punkty overview dla całej domeny, przekazywane
w każdej serii obok szczegółowych points. Zakres głównego wykresu i zaznaczenia
miniatury pochodzi z jednego modelu czasu. Podgląd jest rysowany w SVG według
rzeczywistych timestampów, bez indeksowego cienia dataZoom. ECharts rysuje główny
wykres z jawnymi min/max aktualnego okna; nie wyznacza drugiego własnego zakresu.

Przesuwanie miniatury, jej uchwytów lub wykresu pobiera szczegóły dla nowego
zakresu. Przed odpowiedzią pełny overview uzupełnia obszary poza poprzednio
pobranym oknem; nie rozciągamy starego okna jako danych nowego. Punkty podglądu
nie zmieniają się przy pan/zoom, z wyjątkiem jawnej zmiany kontekstu danych.
Początek/koniec i klawiatura Home/End pozwalają przechodzić przez pełną domenę.

Zakończenie gestu synchronizuje dni from/to w strefie ligi i odświeża raport
oraz historię. chart_base_from/chart_base_to zachowują pierwotny zakres podglądu,
żeby zawężenie tabeli nie zamykało możliwości przesuwania dalej. Stan pozostaje
po reloadzie. Ręczna zmiana dat ustanawia nową domenę; Resetuj widok przywraca
pierwotne dni i pełny zakres. Gesty zastępują bieżący URL zamiast tworzyć
niespójne wpisy historii z nowym oknem i starymi filtrami. Wybór innego przedmiotu
przywraca pierwotny okres i zachowuje poprzedni spójny widok we Wstecz.

Legenda jest stale widoczna, bez rozwijania ustawień; kolory pozostają stałe
przy ukrywaniu serii. Dni filtrów są zsynchronizowane do ich rozdzielczości,
a dokładność sekund/milisekund nadal jest dostępna w wykresie i jego zakresie.


Walidacja tej poprawki: 131 testów backendu, 67 przeglądarkowych i 16 tłumaczeń
zakończone powodzeniem; build TypeScript/Vite poprawny. Testy przesuwają okno
wielokrotnie poza centralny obszar, sprawdzają oba końce miniatury, niezmienność
jej ścieżek, szczegóły po panie, zgodność granic głównego wykresu i podglądu,
automatyczne dni, reload, ręczne daty i reset.

Publiczny nginx: odtworzono Divine Orb w Runes of Aldur, $$$, pierwotnie
7–20 lipca 2026, 7 serii graczy. Początkowe okno 13 lipca 06:00–14 lipca 02:00
w UTC+01:00 przesunięto strzałkami miniatury i gestem głównego wykresu poza
pierwotny zakres. API zwróciło komplet operacji w nowym oknie, podgląd zachował
identyczne ścieżki i domenę, a pola dni aktualizowały się automatycznie.
Zweryfikowano Home/End, reset pierwotnych dat, stale widoczną legendę i mobile.
Porównanie wszystkich źródłowych kolumn transakcji i ustawień przed/po wykazało
brak zmian. Nie ma migracji, zmiany ilości ani rozpoczęcia fazy 6.

### Miniatura wartości i format godzin

Po prawej stronie wykresu znajduje się pionowa miniatura pełnego zakresu
wartości. Górny i dolny uchwyt zawężają oś Y, a przesuwanie zaznaczenia zmienia
jej położenie. Obsługuje także strzałki, Shift oraz Home/End. „Przybliż wartości”
zawęża zakres, „Resetuj wartości” przywraca automatyczną skalę dla aktualnego
okna czasu. Zakres Y jest zapisany w URL jako chart_ymin/chart_ymax; zachowuje
się po odświeżeniu. Nie zmienia czasu, filtrów ani danych i nie pobiera ponownie
serii. Zmiana przedmiotu lub pełny reset usuwa ręczne przybliżenie wartości.

Ustawienia zawierają wybór formatu godzin: domyślny dla języka, 12 h lub 24 h.
Obejmuje tabele, wykresy, tooltipy, diagnostykę i stopkę. Ustawienie hour_format
jest przechowywane na serwerze wraz z ustawieniami ligi albo domyślnymi gildii;
obowiązuje wszystkich klientów korzystających z tej konfiguracji. Starsze
konfiguracje otrzymują domyślne auto bez zapisywania ich ponownie.
Zmiana samego formatu godzin nie unieważnia projekcji ilości i nie wymaga
przeliczania historii. display_settings_hash pozwala innym klientom wykryć
zmianę prezentacji. Schemat bazy i surowe transakcje pozostają bez zmian.

Walidacja: 133 testy backendu, 69 przeglądarkowych i 16 tłumaczeń przeszły;
TypeScript/Vite buduje się poprawnie. Testy obejmują niezależność osi, zachowanie
URL po refresh/reload, reset, wysokość miniatur na desktop/mobile, dziedziczenie
formatu godzin i brak nowej projekcji przy jego zmianie. Test zmiany języka
pomija niezależne, cykliczne odczyty statusu synchronizacji.

Po wdrożeniu przez nginx sprawdzono zoom Y, przesuwanie zaznaczenia, zachowanie
osi czasu, reload/reset, ustawienie formatu i gotowe projekcje obu lig.
Obie miniatury mieszczą się przy głównym wykresie; mobile nie ma poziomego
przepełnienia dokumentu. Brak błędów JavaScript. Hash wszystkich kolumn 104534
źródłowych transakcji oraz konfiguracje lig/gildii są identyczne przed i po.
Faza 6 nie została rozpoczęta; etap kończy się weryfikacją manualną użytkownika.

### Wyśrodkowany nawigator czasu (30%)

Nawigator czasu pokazuje teraz lokalne otoczenie wybranego okna. Po zakończeniu
interakcji zaznaczenie zajmuje środkowe 30% szerokości (35–65%). Wyświetlana
liniowa domena miniatury wynosi długość wyboru / 0,3, z równym marginesem czasu
po obu stronach. Domena źródłowych danych oraz ograniczenia wyboru nadal
wynikają z pierwotnych filtrów. Przy krańcach historii miniatura może pokazywać
pusty obszar poza dostępnymi danymi, aby zachować wyśrodkowanie.

Podczas przeciągania zaznaczenia lub uchwytu domena miniatury jest zamrożona.
Po puszczeniu płynna animacja 280 ms przesuwa i skaluje podgląd, przywracając
wybór do środka. Animowana jest wyłącznie prezentacja: wybrany czas oraz filtry
nie zmieniają się podczas powrotu. Kolejny gest przerywa animację i korzysta
z aktualnej geometrii. Preferencja systemowa ograniczenia ruchu wyłącza animację.
Zoom głównego wykresu, klawiatura, reset i reload również zachowują proporcję
30%. Home/End nadal prowadzą do granic pełnej historii; strzałki przesuwają
wybór względem lokalnego zakresu miniatury. Oś Y pozostaje niezależna.

Zmiana zastępuje poprzednią stałą domenę wyświetlania miniatury, zachowując
niezmienny zestaw danych overview, synchronizację czasu i pobieranie szczegółów.
Nie zmienia API, bazy, ustawień ani sposobu liczenia transakcji.

Walidacja: build TypeScript/Vite, 70 testów przeglądarkowych i 16 tłumaczeń
przeszły. Nowy test sprawdza zamrożenie domeny w trakcie gestu, pośrednie klatki
animacji, powrót do 35–65%, zmianę szerokości uchwytem, reload, ograniczenie ruchu
i mobile. Dotychczasowe testy nadal sprawdzają szczegóły po przesuwaniu daleko
od początkowego okna oraz synchronizację dat. Publiczny nginx potwierdził
przeciąganie, wyśrodkowanie, reset domeny po reloadzie, End i brak przepełnienia
na mobile. Brak błędów JavaScript; surowe transakcje mają niezmieniony hash.
