# Plan implementacji poe2guild

Data: 2026-11-02. Branch: `rework/vue-flask`.
Status: fazy 0–5b odebrane przez użytkownika. Faza 6 zaimplementowana
i wdrożona, oczekuje odbioru manualnego. Fazy 7 i dalsze nie są rozpoczęte;
symulacja stasha pozostaje opcjonalnym etapem 9.
Wyniki: [phase-0.md](phase-0.md), [phase-1.md](phase-1.md), [phase-2.md](phase-2.md), [phase-2a.md](phase-2a.md), [phase-3.md](phase-3.md), [phase-4.md](phase-4.md), [phase-4b.md](phase-4b.md), [phase-5.md](phase-5.md), [phase-5a.md](phase-5a.md), [phase-5b.md](phase-5b.md), [phase-6.md](phase-6.md).
Założenia i ustalenia o API: [architecture.md](architecture.md).

## Cel i granice

Zastąpić starą aplikację usługą Vue/TypeScript + Flask, obsługującą wiele lig,
archiwa offline, interaktywne wykresy oraz synchronizację danych przez wymienne
adaptery. Zachować autofetch po wejściu i ręczny fetch. Automatyzować katalogi
lig i kategorii tam, gdzie dostawca udostępnia wiarygodne informacje.
Wspierać wiele tłumaczeń interfejsu z wyborem języka niezależnym od ligi.

Stary katalog jest niezależnym źródłem danych i punktem odniesienia.
Nie modyfikować go w trakcie portowania. Nie przełączać jego brancha.
Nową bazę i kopie danych można odtwarzać z niego wielokrotnie.
Nie przenosić globalnego stanu starego procesu ani zależności od jednej ligi.

## Zasady wspólne

- Oddzielić fakty źródłowe, projekcje ilościowe, snapshoty cen i wycenę.
- Wszystkie zapytania i obliczenia mają jawny kontekst ligi oraz rewizji.
- Rozdzielić stan ligi, archiwizację, dostępność źródła i świeżość danych.
- Odczyt raportu jest szybki i korzysta z ostatniej poprawnej rewizji.
- Backend publikuje rewizję dopiero po udanym zakończeniu niezbędnych obliczeń.
  Interfejs nie może łączyć odpowiedzi z różnych rewizji w jednym raporcie.
- Zadania zewnętrzne wykonuje osobny worker, nie wątki wewnątrz Gunicorna.
- Konta/GGG OAuth nie są tożsame z wyborem ligi ani stanem przeglądarki.
- Baza, surowe dane i sekrety pozostają poza Git. Migracje i kontrakty w Git.
- Każdy etap dostarcza samodzielny, testowalny rezultat i osobny commit/commity.
- Teksty interfejsu są kluczami tłumaczeń z parametrami, a kody API i dane
  źródłowe pozostają niezależne od języka. Formatowanie liczb i dat respektuje
  locale; wybór języka nie zmienia automatycznie strefy czasu.

## Etap 0 — kontrakty i punkty odniesienia

Zakres:
- Ustalić kontrakty modułów: LeagueCatalog, GuildHistorySource, PriceCatalog,
  PriceSource, ReportService, JobQueue i CredentialStore.
- Opisać capabilities adapterów: historia, katalog lig, katalog kategorii,
  odświeżenie tokenu, zakres deduplikacji zadań i zasady cache.
- Sprawdzić dostępne zasoby GGG/scopes i możliwość uzyskania klienta. Nie
  kontaktować GGG w imieniu użytkownika bez osobnego polecenia.
- Potwierdzić wspierane źródło katalogu kategorii poe.ninja. Jeżeli go brak,
  zaplanować izolowany parser publikowanej listy z cache i kontrolą zmian.
- Wybrać przykłady transakcji i raportów starej aplikacji do porównań;
  uwzględnić skrytki, aliasy, daty, duplikaty i nieznane przedmioty.
- Zapisać dla obu lig zakres, liczbę rekordów, SHA-256 i dostępne ceny.

Odbiór: kontrakty i testowe przykłady są zapisane; wiadomo, które integracje
mają potwierdzony dostęp, a które pozostają warunkowe. Brak dostępu do GGG
nie zatrzymuje implementacji archiwów.

## Etap 1 — SQLite i powtarzalny import

Zależność: etap 0 w zakresie modelu danych.

Zakres:
- Migracje schematu i repozytoria danych; SQLite z krótkimi transakcjami,
  foreign keys, WAL i obsługą konkurencji odczytu z workerem.
- Encje: źródła/gildie, ligi i identyfikatory dostawców, importy, transakcje,
  ustawienia lig/skrytek, rewizje, metadane katalogów, zadania i kursory.
- Zweryfikować zakres unikalności ID transakcji przed ustaleniem klucza.
  Zachować oryginalny zapis pól, czas UTC i wersję normalizacji.
- Oddzielić kompletność lokalnej historii od zakończenia ligi. Archiwalne
  nazwy nie wystarczają do odtworzenia brakujących dat czy zasad ligi.
- Importować obie ligi z istniejących kopii lub wskazanego starego katalogu.
  Osobno zarejestrować cache cen z pochodzeniem.
- Polecenia inicjalizacji, migracji, importu i jawnego odtworzenia bazy.
  Odtwarzanie buduje nowy plik bazy i podmienia go dopiero po walidacji;
  nie kasuje źródeł i wymaga zatrzymania zapisujących procesów.

Odbiór: 89 190 transakcji Runes of Aldur i 15 344 Forbidden Rites; drugi import
nie dodaje rekordów; dane lig się nie mieszają; błędne rekordy są raportowane.
Baza daje się odtworzyć bez przełączania branchy. Korekty istniejących rekordów
mają jawną politykę i nie są cicho ignorowane jako zwykłe duplikaty.

## Etap 2 — pierwsza użyteczna wersja interfejsu

Zależność: etap 1.

Zakres:
- Zastąpić Hello World układem aplikacji i listą lig z lokalnego rejestru.
- API listy lig, ich metadanych oraz transakcji ze stronicowaniem, stabilnym
  sortowaniem i filtrami: gracz, skrytka, przedmiot, zakres dat.
- Zapisać ligę i filtry w URL; obsłużyć odświeżenie i historię przeglądarki.
- Wyświetlać stan pusty, brak danych, archiwum i błąd API.

Odbiór: użytkownik przełącza ligi i przegląda rzeczywistą historię w nowym UI;
URL odtwarza wybór; baza nie wymaga ładowania wszystkich rekordów do przeglądarki.
Zmiana ligi w trakcie żądania nie pozwala starej odpowiedzi nadpisać nowego widoku.
Archiwalne ligi działają bez połączenia z dostawcami.

Kamień milowy A: aplikacja do przeglądania archiwów.

## Etap 2a — wybór języka i tłumaczenia interfejsu

Status: odebrana przez użytkownika; wyniki: [phase-2a.md](phase-2a.md).
Nie łączyć jej automatycznie z fazą 3.

Zakres:
- Przygotować warstwę i18n i katalogi tłumaczeń; początkowy zakres PL/EN,
  z możliwością dodania kolejnego języka bez zmiany logiki komponentów.
  Konkretne narzędzie dobrać podczas implementacji do obecnego Vue/TypeScript.
- Dostępne języki odkrywać automatycznie na podstawie plików
  `frontend/src/locales/*.json`, bez osobnej listy kodów w komponencie lub API.
  Jeden plik reprezentuje język: kod pochodzi z nazwy pliku (np. pl.json),
  a pole metadanych nativeName zawiera nazwę własną (np. Polski). Pozostała
  część pliku zawiera messages. Sprawdzać zgodność kodu locale i schematu pliku.
  Pliki są jedynym źródłem listy: dodanie/usunięcie poprawnego pliku po rebuildzie
  i wdrożeniu dodaje/usuwa opcję przełącznika. Nie wymaga edycji komponentu.
  Nie zakładać odczytu nowych plików z dysku przez już zbudowany frontend.
- Przenieść istniejące teksty Historii, Diagnostyki, filtrów, statusów lig,
  błędów, pustych stanów, tooltipów i etykiet dostępności do słowników.
- Kompaktowy wybór języka, opisany nazwami własnymi języków, bez flag państw.
  Kolejność wyboru: obsługiwany lang w URL → zapisana preferencja przeglądarki
  → obsługiwany język przeglądarki → domyślne EN. Fallback brakującego tekstu: EN.
  Angielski jest językiem bazowym; plik en.json jest wymagany i stanowi punkt
  odniesienia przy sprawdzaniu kluczy i parametrów pozostałych tłumaczeń.
- Język zapisywać w preferencji i parametrze lang, aby link odtwarzał również
  język widoku. Zmiana aktualizuje URL bez utraty ligi, filtrów, sortowania,
  strony i otwartych elementów; nie wywołuje fetchowania ani ponownego importu.
  Dostosować serializer URL i nawigację Historia/Diagnostyka, aby nie usuwały lang.
- Formatować daty, liczby i liczebniki według locale; stosować całe komunikaty
  z parametrami i regułami liczby mnogiej zamiast sklejania słów. W danych API
  zachować ISO/UTC, a w filtrach daty YYYY-MM-DD. Strefa czasu pozostaje osobną
  preferencją; obecne UTC nie zmienia się wskutek wyboru PL lub EN.
- Backend zwraca stabilne kody błędów/statusów; frontend mapuje je na tłumaczenia.
  Klucze biznesowe, cache, identyfikatory i rewizje danych nie zależą od locale.
- Nie tłumaczyć nazw kont, skrytek ani surowych opisów zdarzeń. Nazwy lig,
  przedmiotów i kategorii źródłowych zachować jako kanoniczne; przyszłe oficjalne
  nazwy lokalizowane będą osobną warstwą prezentacji nad stabilnymi ID.
- Aktualizować html lang. Teksty i wartości parametrów renderować jako tekst,
  bez wstrzykiwania HTML z tłumaczeń. Dłuższe etykiety nie mogą psuć układu mobilnego.

Odbiór:
- Cały istniejący interfejs można przełączyć PL/EN bez przeładowania strony
  i bez utraty aktualnego kontekstu. Reload i skopiowany URL odtwarzają język.
- Przełączanie języka nie zmienia rekordów, wyników filtrów, rewizji ani cen.
- Kontrola zestawu kluczy i parametrów wykrywa niekompletne tłumaczenia;
  testy obejmują fallback, nieobsługiwane lang, liczby mnogie, daty/liczby,
  etykiety aria, URL/back/forward i dłuższe teksty w widoku mobilnym.
- Dokumentacja opisuje dodawanie języka i tłumaczenie nowych funkcji.
  Nowe teksty z faz 3–8 powstają od razu w katalogach tłumaczeń.
- Testy potwierdzają, że opcje odpowiadają plikom, używają nativeName,
  a dodanie/usunięcie języka nie wymaga zmiany kodu. Niepoprawny JSON,
  metadane lub kod locale dają błąd walidacji builda. Po usunięciu języka
  zapisana preferencja lub lang w URL bez odpowiadającego pliku korzysta
  z reguł fallbacku. Brak en.json lub nieprawidłowy słownik angielski blokuje build.

## Etap 3 — worker i kontrakt odświeżania

Status: odebrana przez użytkownika; wyniki: [phase-3.md](phase-3.md).

Zależność: etapy 1–2 i warstwa tekstów z 2a. Nie wymaga dostępu do historii GGG.

Zakres:
- Trwała kolejka SQLite, jeden worker, lease, heartbeat, retry z backoff,
  deduplikacja i odzyskiwanie zadań po restarcie. Wygasły worker nie może
  opublikować wyniku po przejęciu zadania przez inny proces.
- Rozszerzyć launcher: wspólny start/stop/status web + worker, osobne PID-y
  i logi, kontrolowane zatrzymanie oraz sygnalizacja częściowej awarii.
- Endpoint zgłoszenia aktualizacji i statusu; polling stanu/rewizji w Vue.
- Pokazać daty ostatniej synchronizacji i generowania oraz przycisk ręczny.
- Wejście na stronę inicjuje sprawdzenie świeżości, a nie blokujący fetch.
  Zachować limit 2 automatycznych prób/h, współdzielony przez klientów;
  zakres limitu odpowiada faktycznemu zakresowi źródła, np. gildii.
- Ręczny fetch pomija limit aplikacyjny, ale nie deduplikację, cooldown,
  cache ani limity dostawcy. Status wyjaśnia oczekiwanie/ograniczenie.
- Adapter lokalny/testowy weryfikuje cykl odświeżania. Gdy zewnętrzne źródło
  jest niedostępne, UI pokazuje ten stan zamiast pozornego sukcesu.
- Zmiana rewizji aktualizuje dane bez przeładowania i bez utraty kontekstu.

Odbiór: dwie karty zgłaszają jedno zadanie; limit działa między procesami;
restart nie gubi zadań; błąd pozostawia ostatnie poprawne dane. Archiwum nie
wykonuje fetchowania mimo ręcznie wysłanego żądania. Launcher zarządza oboma
procesami wyłącznie tego checkoutu.

## Etap 4 — obliczenia ilościowe

Status: odebrana przez użytkownika; wyniki: [phase-4.md](phase-4.md).

Zależność: etapy 1–3.

Zakres:
- Przenieść parser ilości i normalizację zdarzeń jako czyste funkcje.
- Podsumowania graczy/skrytek, przepływy i odtwarzanie stanu współrzędnych.
- Wyliczona delta ze znakiem i akcja zastępcza dla zdarzeń; źródłowy wpis pozostaje niezmienny.
- Osobna historia, ruchy i stan każdej ligi. Wspólna konfiguracja gildii
  (wybór skrytek, aliasy, strefa czasu), dziedziczona z nadpisaniem per liga.
  Wspólne nazwy nigdy nie łączą stanów przedmiotów między ligami.
- Projekcje wyników z wersją algorytmu i rewizją wejścia, bez globalnych
  słowników. Nieznane przypadki i luki danych mają jawne oznaczenia.
- Widoki podsumowań, graczy, skrytek oraz stanu końcowego w Vue.

Odbiór: porównania wybranych przypadków i sum ze starą aplikacją przechodzą
przy identycznych ustawieniach. Stan końcowy nie jest przedstawiany jako
pełny obraz skrytki, jeśli historia nie daje takiej pewności.

## Etap 4b — reorganizacja frontendu

Status: odebrana przez użytkownika wraz z poprawkami.
Faza dodana po wyborze użytkownika, przed wykresami.
Wyniki i instrukcja odbioru: [phase-4b.md](phase-4b.md).

Zakres:
- Domyślne Podsumowanie i osobne widoki graczy, skrytek, stanu, historii,
  ustawień klienta i konfiguracji serwera.
- Jeden kontekst ligi i filtrów; zachowanie draftów, URL, paginacji i języka.
- Kompaktowe odświeżanie oraz szczegóły workera i źródeł w Diagnostyce.
- Oddzielenie prezentacji, formularzy i odczytu danych w komponentach/composables.
- Nawigacja desktop/mobile, testy przeglądarkowe i zgodność starszych linków.

Odbiór: sekcje pokazują jedną treść naraz, zmiana widoku nie usuwa kontekstu
ani nie uruchamia od nowa sprawdzenia źródła. Weryfikacja manualna wymagana
przed rozpoczęciem fazy 5.

## Etap 5 — interaktywne wykresy

Status: implementacja zakończona, oczekuje odbioru manualnego.
Wyniki, granice i instrukcja odbioru: [phase-5.md](phase-5.md).

Zależność: etapy 4 i 4b; wykresy wartości uzupełnia etap 6.

Zakres:
- Wdrożyć ECharts jako komponent Vue, z API szeregów czasowych niezależnym
  od biblioteki. UTC w danych, formatowanie według ustawień widoku.
- Tooltip, wybór serii, zoom, przesuwanie zakresu i reset widoku.
- Powiązać zakres wykresu z filtrami raportu/tabeli; zachować go po aktualizacji.
- Agregacja backendowa według zakresu i limitu punktów; nie przesyłać całej
  historii do każdego wykresu. Obsłużyć brak danych i resize.

Odbiór: wykresy ilościowe działają na obu ligach, reagują na wybór gracza
i skrytki, a odświeżenie nie zeruje interakcji. Oceniona wydajność na większej
lidze; po wycenie ten sam mechanizm obsługuje szeregi wartości.

## Etap 6 — katalog kategorii, snapshoty cen i wycena

Status: wdrożona; oczekuje odbioru manualnego. Wyniki i ograniczenia danych:
[phase-6.md](phase-6.md). Nie rozpoczęto fazy 7.

Zależność: etapy 1, 3–4. Prezentacja wartości korzysta też z etapu 5.

Zakres:
- Oddzielny adapter poe.ninja; rozróżnić exchange i stash item oraz ich formaty.
- Dynamiczny katalog ID kategorii, etykiet, feedów i dostępności per liga.
  Preferować wspierany katalog, gdy istnieje. W przeciwnym razie izolowany
  parser publikowanej listy, walidacja i ostatni poprawny katalog.
- Odkrywać dodania/zmiany/usunięcia bez kasowania historycznych danych.
  Awaria parsowania katalogu nie może zostać uznana za usunięcie kategorii.
- Wspólny cache/ETag i harmonogramy dostawcy. Nie odpytywać cen per użytkownik.
- Normalizacja walut, tożsamości przedmiotów i aliasów niezależna od kategorii.
- Import istniejącego cache z oznaczeniem niepewnego pochodzenia lub czasu,
  gdy brakuje tych informacji; nie odgadywać ich jako pewnych faktów.
- Pobierać dostępną dzienną historię cen per przedmiot z endpointów details/history,
  zachowując znaczniki UTC, kotwicę daysAgo i surową odpowiedź. Krótkiego
  sparkline ani dzisiejszego kursu nie używać do odtwarzania dawnych cen.
- Snapshoty cen i wersjonowana wycena; rozróżnić ceny aktualne, historyczne
  i estymowane. Nie utożsamiać braku wyceny z wartością zero.
- Tabele i wykresy wartości oraz widok przedmiotów bez wyceny.
- Zastąpić tymczasowy wybór pojedynczego przedmiotu na wykresie łączną wartością
  operacji. Podstawowy tryb wycenia każdą operację ceną z chwili jej realizacji;
  późniejsze wahania ceny nie przeszacowują już wykonanych operacji.
- Dodać przełącznik „najnowsze ceny”: wycenić wszystkie operacje jednym jawnym,
  najnowszym zestawem cen ligi. Przeliczać podpisane ruchy, nie łączyć cen lig.
  Zapisywać identyfikatory snapshotów i oznaczać brak historycznej ceny;
  nie podstawiać ceny przyszłej lub najnowszej w trybie historycznym po cichu.
- Zachować serie balansu wartości dla gildii, poszczególnych graczy i skrytek,
  a także próbkowanie zachowujące ekstrema i szczegóły na żądanie po zoomie.

Odbiór: nowa kategoria o znanym formacie nie wymaga zmiany UI; nieznany format
jest raportowany bez uszkodzenia wyników. Usunięta kategoria zachowuje archiwum.
Wycenę można odtworzyć z określonego zestawu cen i wersji algorytmu.
Porównania kwot używają tych samych cen, zasad i waluty co wynik referencyjny.

## Etap 7 — katalog lig i oficjalna synchronizacja GGG

Część A: automatyczny katalog lig. Zależność: etapy 1 i 3.
- Synchronizować lokalne ligi z katalogiem GGG, jeżeli dostępny, i katalogiem
  ekonomii poe.ninja. Zachować mapowanie game/realm/wariantów/ID dostawców.
- Zapisywać źródło, datę obserwacji i dowody statusu. Nie archiwizować ligi
  z powodu błędu sieci lub braku na liście cen.
- Odkrycie nowej ligi aktualizuje listę; osobna polityka określa, które ligi
  gildia monitoruje. Zachować ręczną korektę i lokalne archiwa.

Część B: OAuth i historia gildii. Zależność: etapy 0, 3 i potwierdzony dostęp.
- Wdrożyć wyłącznie flow/scopes obsługujące potrzebny zasób.
- HTTPS callback, backendowy magazyn sekretów, stan połączenia i odnowienie
  tokenu pod blokadą; bez tokenów w Vue/logach. Rotacja refresh tokenu nie
  może być traktowana jako przedłużenie pierwotnego terminu ważności.
- Adapter historii z pobieraniem przyrostowym, zakładką, paginacją i limitami.
  Kursor zatwierdzać razem z poprawnym importem; nie pomijać danych po błędzie.
- Rozdzielać dane gildii do właściwych lig; pusta odpowiedź nie usuwa historii.
- Jawnie obsłużyć utratę zgody, wygaśnięcie i brak uprawnień.

Odbiór: nowa liga pojawia się bez edycji kodu; awaria katalogu zachowuje znany
stan. Jeżeli źródło historii jest dostępne, autofetch i manual fetch przechodzą
pełny test integracyjny, włącznie z limitem i utratą autoryzacji.

Jeżeli dostęp GGG nie zostanie przyznany, część B pozostaje warunkowa.
Pozostałe etapy dostarczają działającą aplikację z lokalnym importem i cenami.
Nie zastępować tego automatycznym logowaniem ani nie zakładać, że POESESSID
jest oficjalnym, trwalszym rozwiązaniem. Nie deklarować fetchowania jako gotowego.

Kamień milowy B: analityka i ceny. Kamień milowy C: pełna synchronizacja,
o ile wymagane źródła są dostępne.

## Etap 7C — analiza wiarygodności logów GGG na żywo

Status: zaplanowany; nie rozpoczynać przed wdrożeniem i odbiorem pobierania
historii z API w 7B. Osobna faza, wymagająca polecenia użytkownika.
Zależność: działający adapter historii oraz dostęp do ligi, w której można
wykonać kontrolowane operacje w skrytce gildii. Przy braku dostępu etap czeka;
analiza samych archiwów nie zastępuje odtworzenia na żywo.

Problem do sprawdzenia:
- Według doniesień graczy przekazanych przez użytkownika logi GGG bywają
  nierzetelne. To przesłanka do eksperymentów, nie potwierdzona przyczyna
  rozbieżności w naszej bazie.
- Szczególnie sprawdzić **podmianę różnych przedmiotów w tym samym slocie**:
  czy pojawia się osobne usunięcie poprzedniego przedmiotu, jaki przedmiot
  i ilość opisuje Modified oraz czy współrzędne jednoznacznie identyfikują slot.
- Obecny model może wywnioskować usunięcie przy pojawieniu się innego
  przedmiotu, a Removed może opróżnić slot zawierający według replaya inny
  przedmiot. Trzeba oddzielić niepełność źródła od błędnej interpretacji,
  niewłaściwego klucza slotu i problemów naszego fetchera.
- Przypadek referencyjny: Runes of Aldur, Abyss/Expedition, Verisium.
  Pomiar na quantities-v3: bilans operacji 7776, suma znanych stanów slotów 21776; różnica 14000.
  W modelu 21 usunięć Verisium bez pasującego stanu zmniejsza bilans o 21000,
  a 7 usunięć innych przedmiotów zeruje 7000 Verisium bez odpowiadającej
  zmiany jego bilansu. Żadna z tych końcowych liczb nie jest potwierdzonym
  stanem w grze. Zachować ten przypadek jako regresję do analizy.
  Tymczasowo quantities-v4 stosuje uzgodnione opróżnianie slotów i osobne
  korekty rekonstrukcji; to przyjęta polityka księgowania, a nie dowód
  rzeczywistej semantyki GGG. Szczegóły: [phase-4.md](phase-4.md).

Zakres eksperymentów:
- Uzgodnić z użytkownikiem sekwencję ręcznie wykonywanych działań w grze.
  Zapisać rzeczywistą zawartość i ilości przed oraz po każdej operacji.
- Sprawdzić Added, częściowe zmiany stosu, Removed, podmianę A → B,
  przenoszenie pomiędzy slotami/skrytkami, dzielenie i łączenie stosów,
  szybkie dodanie/usunięcie oraz działania różnych graczy. Jeśli dostępne,
  porównać zwykłą i specjalną skrytkę oraz różne kontenery w jej obrębie.
- Dla każdego kroku zachować oryginalne odpowiedzi API, identyfikatory,
  czasy, wszystkie dostępne pola identyfikujące skrytkę/kontener/przedmiot
  i parametry pobierania: kursor, strony, czas żądania. Nie utrwalać sekretów.
  Ponowić odczyt po opóźnieniu, aby sprawdzić widoczność i kolejność wpisów.
- Porównać stan gry → surowe API → zaimportowane wpisy → wyliczone operacje
  → replay. Sprawdzić paginację, duplikaty, kolejność i opóźnione zdarzenia,
  zanim brakujący wpis zostanie przypisany systemowi GGG.
- Opisać potwierdzoną semantykę oraz przypadki niejednoznaczne. Zbudować
  zanonimizowane fixture'y i testy regresyjne; dopiero na tej podstawie zmienić
  interpretację i wersję algorytmu. Surowa historia pozostaje niezmieniona.
- Weryfikować warunek: stan początkowy + suma zmian = stan końcowy dla każdego
  przedmiotu i skrytki. Niewyjaśnione przejścia oznaczać jawnie; nie maskować
  problemu przycięciem wykresu do zera ani uznaniem replaya za pewny stan gry.

Odbiór: sytuacje odtworzono na żywo, istnieje zapis rzeczywistych działań
wraz z odpowiadającymi odpowiedziami API oraz udokumentowane reguły ich
interpretacji. Testy odróżniają operacje źródłowe, wnioskowane i nierozstrzygnięte;
każda korekta obliczeń ma dowód w zebranych danych i zachowuje audytowalność.

## Etap 8 — zgodność i przejście na rework

Zależność: etapy 2, 4–6; etapy 7B i 7C dla odbioru synchronizacji
i interpretacji historii z API.

Zakres:
- Porównanie wyników obu aplikacji na tym samym wejściu i jawne opisanie
  zamierzonych różnic, zwłaszcza wyceny i przypadków wcześniej błędnych.
- Kopia i odtworzenie bazy, migracje, test restartu i awarii worker/web,
  przegląd logów, kontrola rozmiaru odpowiedzi i czasu działania na obu ligach.
- Testy przeglądarkowe zmiany ligi, URL, filtrów, wykresów, wielu klientów,
  błędu źródła i zachowania kontekstu. Testy pod rzeczywistym prefiksem Nginx.
- Aktualizacja instrukcji build/start/status/logs i dokumentacji danych.

Odbiór: użytkownik może sprawdzić pełne widoki w przeglądarce, archiwa działają
bez sieci, odtworzenie danych jest powtarzalne, a znane ograniczenia źródeł są
widoczne. Stara usługa pozostaje dostępna do porównania; wyłączenie jej lub
usunięcie katalogu wymaga osobnego polecenia użytkownika.

## Etap 9 — symulacja Stash state (opcjonalny, nice to have)

Status: odłożony na koniec głównej ścieżki; wcześniej planowany jako 5c.
Nie jest wymagany do ukończenia ani wdrożenia podstawowej aplikacji.

Warunki rozpoczęcia:
- Zakończyć integrację historii z API (7B), analizę na żywo (7C) i rozwiązać
  problem desynchronizacji odtwarzanego stanu z logami. Potwierdzić reguły
  interpretacji i zgodność stanów na kontrolowanych operacjach w grze.
- Tymczasowe korekty rekonstrukcji uzgadniające księgowanie nie wystarczają
  do uznania problemu desynchronizacji za rozwiązany.
- Zakończyć główny zakres i odbiór w etapie 8. Wrócić do funkcji wyłącznie
  na osobne polecenie użytkownika, jeśli nadal będzie potrzebna.

**Przed rozpoczęciem zapytać użytkownika o design i poczekać na doprecyzowanie.**
Nie budować wizualnej symulacji na podstawie domyślnych założeń.

- Zastąpić tabelę odwzorowaniem skrytek z przedmiotami i tooltipem zawierającym
  ostatnie zdarzenie dla danego przedmiotu/slotu.
- Suwak czasu rekonstruuje stan skrytek w wybranym momencie, z osobną historią
  każdej ligi. Removed opróżnia slot, a brak operacji zachowuje wcześniejszy stan.
- Filtry strony nie wpływają na ten widok i mogą być w nim ukryte. Serwerowa
  lista ignorowanych zakładek pozostaje wiążąca i nie może być obchodzona.
- Rozważyć snapshoty stanów i odtwarzanie przyrostowe dla płynnego suwaka,
  z testami spójności względem pełnego replay i kolejności równoczesnych operacji.

Odbiór: uzgodniony design, zgodność układu i stanów z replay, ostatnie zdarzenia
w tooltipach, płynna zmiana czasu i izolacja lig oraz ukrytych skrytek.

## Zależności i następny zakres pracy

Główna ścieżka: 0 → 1 → 2 → 2a → 3 → 4 → 4b → 5 → 5a → 5b → 6 → 7A/7B → 7C → 8.
Po głównej ścieżce: opcjonalny etap 9, po rozwiązaniu desynchronizacji stanów.
Etap 3 dostarcza mechanizm aktualizacji używany następnie przez 4, 6 i 7.
Rozpoznanie dostępu z etapu 0 trwa niezależnie od portowania archiwów.
Część 7A można wdrożyć po 3, przed zakończeniem obliczeń i wykresów.
Ścieżka integracji historii: 7B → 7C → odbiór integracyjny w 8.
Nie łączyć automatycznie wdrożenia fetchera z analizą logów na żywo.

Praca odbywa się po jednej fazie. Po zakończeniu każdej fazy wymagany jest
odbiór manualny i osobne polecenie użytkownika do przejścia dalej.
Fazy 5a i 5b zostały odebrane; faza 6 (wycena) została wdrożona
i oczekuje odbioru. Następny jest etap 7 (katalog lig i synchronizacja). Symulacja stasha została
odłożona do opcjonalnego etapu 9, po rozwiązaniu desynchronizacji i odbiorze w 8.
Łączenie zakresu kilku faz wymaga wcześniejszego przedstawienia propozycji
i uzyskania opinii użytkownika; nie jest decyzją autonomiczną implementacji.

## Aktualizacja zakresu po testach wykresów — 2026-11-02

W bieżącej fazie 5: linie bez punktów, dokładny tooltip stanu w dowolnym czasie,
wybór All (suma ilości wszystkich typów), zoom wyłącznie miniaturami i reset
odpowiedniej osi dwuklikiem. Refresh chart pozostaje ręcznym ponowieniem odczytu.
Przełącznik ilość/wartość: domyślnie ilość, tryb wartościowy ukrywa wybór
przedmiotu i wybiera All. Do fazy 6 pokazuje pusty wykres. Przełącznik cen
historyczne/aktualne jest w nim zablokowany, z wybraną opcją historyczną.
Faza 6 uruchomi wycenę i zmieni domyślny tryb na wartościowy. Kliknięcie koloru
w legendzie otwiera picker, a kolory są zapisywane po stronie klienta.

### Etap 5a — lokalne preferencje prezentacji (odebrana)

- Język, strefa czasu, 12/24 h, kolory, zwinięte panele i domyślny widok są
  preferencjami klienta, w wersjonowanym magazynie przeglądarki. Migracja
  zachowuje wcześniejszy język i kolory; brak lokalnego języka oznacza angielski.
- **Filtry, zakres czasu i liga wynikają wyłącznie z URL. Nie zapamiętywać ich
  w preferencjach ani nie przywracać z localStorage.** Granice czasu są
  jednoznacznymi timestampami ISO 8601 UTC z Z; koniec jest wyłączny.
- Konfiguracja klienta zmienia wyłącznie wyświetlanie tych samych danych.
  Ręczna edycja dnia tworzy granicę UTC w wybranej strefie; zmiana samej strefy
  nie zmienia żadnej wartości filtra UTC. Uwzględnić dni 23- i 25-godzinne.
- Aliasy i ignorowane zakładki pozostają konfiguracją serwera dla wszystkich.
  Dostęp zostanie ograniczony do administratora w fazie 5b.
- Nagłówek i zwijalny pasek filtrów są poza obszarem przewijania. Przewija się
  zawartość pod nimi; zwinięte filtry pozostają po prawej stronie. Kolory wybiera się w popupie z kołem barw, nasyceniem i jasnością.

Odbiór: dwie przeglądarki z różnymi preferencjami prezentują te same rekordy
z tego samego URL UTC, bez zapisu ustawień serwera i bez przeliczania projekcji.
Działają reload, Wstecz/Dalej, migracja kolorów oraz zablokowany localStorage.

### Etap 5b — administracja i logowanie (odebrana)

- Widoczny przycisk Login / Admin; kliknięcie otwiera popup logowania lub
  wylogowania. Konto administracyjne i sesja są weryfikowane na backendzie.
- Diagnostyka oraz konfiguracja serwera wymagają zalogowania. Bez logowania
  ukryć wybór Workspace / Diagnostics, a endpointy administracyjne chronić
  niezależnie od widoczności interfejsu.
- Przenieść serwerowe aliasy i ignorowane zakładki do osobnej zakładki
  System settings, widocznej tylko po zalogowaniu. Jedyne konto to admin;
  formularz logowania zawiera wyłącznie hasło.
  Publiczne widoki nadal respektują te wyłączenia.
- Rozważyć konfigurację GUILD_ID i SESSION_ID albo oficjalnych odpowiedników
  GGG: sekrety przechowywać po stronie serwera, nie zwracać ich w odczytach
  publicznych ani ujawniać w logach. Powiązać z oficjalnym OAuth w etapie 7B.
- Konto początkowe admin / kalandra; instalacja pyta o nowe hasło, z Enter
  pomijającym zmianę (not recommended). Gdy domyślne hasło obowiązuje, strona
  automatycznie otwiera popup zmiany hasła po uwierzytelnieniu administratora.
- Ustalić sposób pierwszego utworzenia administratora, hasła/sesje, CSRF,
  limity prób i wygasanie sesji. Nie utożsamiać logowania Admin z autoryzacją GGG.

Odbiór: gracz nie może odczytać diagnostyki ani zmieniać konfiguracji także
bezpośrednio przez API; administrator może zalogować się, skonfigurować skrytki
oraz wylogować. Konfiguracja połączenia GGG nastąpi z adapterem w 7B. Sekrety nie trafiają do odpowiedzi ani frontendu.

Proponowana kolejność po odbiorze fazy 5a: 5b → 6 → 7A/7B → 7C (po 7B) → 8 → opcjonalnie 9.
Każdy etap wymaga osobnego polecenia rozpoczęcia i kończy się zatrzymaniem do
odbioru. Fazy 5b i 6 są wdrożone; faza 6 oczekuje odbioru. Opcjonalna symulacja nie została rozpoczęta.
