# Plan implementacji poe2guild

Data: 2026-11-02. Branch: `rework/vue-flask`.
Status: plan do wykonania; działający szkielet Hello World pozostaje bez zmian.
Założenia i ustalenia o API: [architecture.md](architecture.md).

## Cel i granice

Zastąpić starą aplikację usługą Vue/TypeScript + Flask, obsługującą wiele lig,
archiwa offline, interaktywne wykresy oraz synchronizację danych przez wymienne
adaptery. Zachować autofetch po wejściu i ręczny fetch. Automatyzować katalogi
lig i kategorii tam, gdzie dostawca udostępnia wiarygodne informacje.

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
  Osobno zarejestrować HTML, SVG i cache cen jako archiwa z pochodzeniem.
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
- Udostępnić konkretne archiwalne raporty przez kontrolowane identyfikatory;
  nie wystawiać całego katalogu data. Historyczny HTML otwierać jako osobny
  dokument, bez wstrzykiwania go jako kodu do aplikacji Vue.

Odbiór: użytkownik przełącza ligi i przegląda rzeczywistą historię w nowym UI;
URL odtwarza wybór; baza nie wymaga ładowania wszystkich rekordów do przeglądarki.
Zmiana ligi w trakcie żądania nie pozwala starej odpowiedzi nadpisać nowego widoku.
Możliwy podgląd starego raportu bez połączenia z dostawcami.

Kamień milowy A: aplikacja do przeglądania archiwów.

## Etap 3 — worker i kontrakt odświeżania

Zależność: etapy 1–2. Nie wymaga dostępu do historii GGG.

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

Zależność: etapy 1–3.

Zakres:
- Przenieść parser ilości i normalizację zdarzeń jako czyste funkcje.
- Podsumowania graczy/skrytek, przepływy i odtwarzanie stanu współrzędnych.
- Ustawienia wybranych skrytek, aliasów i strefy czasu per liga.
- Projekcje wyników z wersją algorytmu i rewizją wejścia, bez globalnych
  słowników. Nieznane przypadki i luki danych mają jawne oznaczenia.
- Widoki podsumowań, graczy, skrytek oraz stanu końcowego w Vue.

Odbiór: porównania wybranych przypadków i sum ze starą aplikacją przechodzą
przy identycznych ustawieniach. Stan końcowy nie jest przedstawiany jako
pełny obraz skrytki, jeśli historia nie daje takiej pewności.

## Etap 5 — interaktywne wykresy

Zależność: etap 4; wykresy wartości uzupełnia etap 6.

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
- Snapshoty cen i wersjonowana wycena; rozróżnić ceny aktualne, historyczne
  i estymowane. Nie utożsamiać braku wyceny z wartością zero.
- Tabele i wykresy wartości oraz widok przedmiotów bez wyceny.

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

## Etap 8 — eksport, zgodność i przejście na rework

Zależność: etapy 2, 4–6; etap 7B tylko dla odbioru synchronizacji.

Zakres:
- Eksport offline currentday.html/lastday.html z jednej zatwierdzonej rewizji,
  według ustalonej polityki rotacji. Nie przebudowywać archiwów automatycznie.
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

## Zależności i następny zakres pracy

Główna ścieżka: 0 → 1 → 2 → 3 → 4 → 5 → 6 → 8.
Etap 3 dostarcza mechanizm aktualizacji używany następnie przez 4, 6 i 7.
Rozpoznanie dostępu z etapu 0 trwa niezależnie od portowania archiwów.
Część 7A można wdrożyć po 3, przed zakończeniem obliczeń i wykresów.

Najbliższy zakres implementacji: etapy 0–2. Rezultatem ma być baza obu lig,
wybór ligi, tabela transakcji i dostęp do archiwalnego raportu. Następnie etap 3
domyka fundamenty aktualizacji przed rozbudową raportów i integracji.
