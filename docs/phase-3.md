# Faza 3 — worker i kontrakt odświeżania

Status: odebrana przez użytkownika poleceniem przejścia do fazy 4.
Faza 2a została odebrana poleceniem przejścia dalej.
Dalszy zakres opisuje [phase-4.md](phase-4.md).

## Widok do odbioru

W Historii, pod tytułem, jest panel Odświeżanie danych / Data refresh:

- Stan workera, ostatnia synchronizacja, ostatnie generowanie raportu
  i ostatnia weryfikacja lokalna są osobnymi informacjami.
- Wejście/wybór ligi zgłasza automatyczne sprawdzenie świeżości w tle.
  Otwarcie strony nie czeka na wykonanie zadania.
- Pobierz historię / Fetch history zgłasza ręczne odświeżenie.
- Sprawdź dane lokalne / Verify local data uruchamia rzeczywiste zadanie
  workera: porównanie lokalnych rekordów z surowymi danymi oraz ich SHA-256.
  Nie wywołuje dostawców, nie importuje zdarzeń i nie generuje raportu.
- Panel pokazuje kolejkę, wykonywanie, zakończenie, liczbę prób, oczekiwanie
  na cooldown/limit, błędy i liczbę sprawdzonych lokalnych rekordów.
- Błąd synchronizacji lub weryfikacji zachowuje ostatni poprawny wynik i dane.
  Błąd samego panelu nie usuwa tabeli transakcji.

Obie obecne ligi są archiwalne. Ich synchronizacja jest wyłączona zarówno
w interfejsie, jak i w API, przy przejmowaniu zadania i publikacji wyniku.
Nie włączono integracji historii GGG: dla niearchiwalnej ligi bez adaptera
status to source_unavailable, nie udana synchronizacja ani pusta historia.
Lokalna weryfikacja działa także dla archiwów i jest jednoznacznie podpisana.
Brak daty nowej synchronizacji/generowania jest zatem poprawnym stanem.

Instrukcja:

1. Otwórz http://dyyyl.ovh/poe2guild/?lang=pl i sprawdź „Worker działa”.
2. Dla Forbidden Rites kliknij Sprawdź dane lokalne. Zobacz zakończenie,
   datę weryfikacji i 15 344 sprawdzone rekordy. Dla Runes of Aldur: 89 190.
3. Otwórz drugą kartę z tą samą ligą. Obie pokazują wspólny wynik i aktywne
   zadanie. Ponowienie po zakończeniu może oczekiwać na 30-sekundowy cooldown.
4. Filtry, strona, sortowanie i język nie powinny zmieniać się przy aktualizacji.
5. Pobieranie historii pozostaje zablokowane dla archiwum; data synchronizacji
   i generowania nie są zastępowane datą lokalnego sprawdzenia.
6. Przełącz PL/EN i sprawdź również szerokość mobilną.

## Kolejka i polityka

Migracja 002 rozszerza istniejące jobs, dodaje refresh_scopes,
automatic_attempts i worker_status. Baza ma schemat 2. Migracja zachowuje
rekordy, importy, rewizje i pliki; niewykonywalne zadania z dawnej tabeli
placeholder są oznaczane failed/legacy_job. Migracje wykonuje CLI, nie HTTP.

Wszystkie decyzje kolejki używają krótkich transakcji BEGIN IMMEDIATE:

- Zakres historii pochodzi z konfiguracji serwera: provider + owner/gildia
  + zasób guild_history. SHA-256 tego zakresu jest kluczem deduplikacji,
  limitu i cooldownu. Wybór ligi nie tworzy osobnego limitu historii gildii.
  Właściciel nie pochodzi z żądania klienta i nie jest ujawniany w odpowiedzi.
- Unikalny indeks dopuszcza jedno queued/running na zakres. Weryfikacja
  lokalna ma odrębny zakres local + liga + verify, bo nie pobiera historii gildii.
- Automatyczny odczyt pomija pracę, jeśli ostatni udany wynik źródła ma mniej
  niż 30 minut. Stan fresh nie zużywa limitu. Ręczny odczyt pomija tę politykę.
- Maksymalnie 2 automatyczne próby w ruchomym oknie 3600 sekund, wspólnie
  między klientami/procesami/ligami tego samego zakresu. Ponowienia również
  zużywają limit. Rezerwacja przy enqueue jest przesuwana na faktyczny start,
  więc długie oczekiwanie nie pozwala wykonać trzech odczytów w jednym oknie.
- Ręczne zgłoszenie omija limit automatyczny, ale współdzieli istniejące zadanie.
  Oczekujące zadanie automatyczne można awansować do manual bez tworzenia
  duplikatu; nie resetuje to prób ani oczekiwania narzuconego przez źródło.
- Minimum między pracami: 30 sekund. Retry: najwyżej 3 wykonania, backoff
  co najmniej 5/10 sekund oraz cooldown źródła. retry_after od adaptera może
  wydłużyć oczekiwanie; ręczne żądanie go nie skraca.
- Lease: 30 sekund, odnawiane w tle co 10 sekund. Każde claim daje nowy losowy
  token. Renew/fail/complete wymagają bieżącego tokenu i niewygasłej dzierżawy.
  Po wygaśnięciu zadanie wraca do kolejki lub kończy się po wyczerpaniu prób.
- Adapter przygotowuje wynik poza transakcją. complete sprawdza dzierżawę,
  politykę ligi, zapisuje dane/kursor/rewizję przez krótki callback i zatwierdza
  je razem ze stanem zadania. Błąd lub utrata lease wycofuje całą publikację.
  Wygasły worker po przejęciu zadania nie może zapisać wyniku.

Worker ma osobną blokadę plikową przy bazie (*.worker.lock), więc drugi proces
tej samej bazy nie uruchomi pętli. Heartbeat procesu jest aktualizowany co
2 sekundy; po 15 sekundach bez sygnału UI zgłasza offline. SIGTERM zatrzymuje
pracę kontrolowanie; nagła śmierć pozostawia trwałe zadanie do odzyskania.
W logach i error_code nie zapisujemy treści wyjątków, requestów ani poświadczeń.

## Adapter lokalny i przyszłe adaptery

LocalVerification odczytuje spójny snapshot SQLite. Sprawdza surowy JSON,
normalizację, SHA-256 i zgodność kolumn każdego rekordu wybranej ligi.
Zapisuje liczbę, digest oraz rewizję sprawdzonych danych. Jeśli rewizja zmieniła
się przed publikacją, wynik nie jest publikowany i następuje retry. To kontrola
spójności danych, nie dowód kompletności historii lub zgodności z grą.

UnavailableHistory jawnie odrzuca historię. Nie ma trybu, który zamienia brak
integracji w fikcyjny sukces. HISTORY_AVAILABLE domyślnie false; testy wstrzykują
adaptery oraz wspólny scope. Nowy adapter musi być dostępny zarówno dla API,
jak i workera, wykorzystywać cache/conditional requests i respektować własne
limity, a retry_after przekazywać do kolejki. HTTP wykonuje się wyłącznie
podczas przygotowania wyniku, nigdy wewnątrz callbacku publikującego.

Środowisko POE2GUILD_DATABASE może wskazać inną bazę obu procesom; używaj
absolutnej ścieżki, niezależnej od katalogu wywołania launchera.
POE2GUILD_GUILD_REFERENCE pozwala ustalić właściciela zakresu historii;
samo ustawienie zmiennej nie włącza niedostępnego adaptera ani poświadczeń.

## API i frontend

GET /api/leagues/<id>/refresh zwraca rewizję ligi, online/offline workera,
stan history i local_verify, ostatnie wyniki/datę sukcesu, bieżące zadania,
cooldown, termin limitu automatycznego i datę raportu z revisions.
Nie zwraca lease tokenów, worker ID, właściciela źródła ani poświadczeń.

POST /api/leagues/<id>/refresh przyjmuje JSON:

```json
{"kind": "history", "trigger": "automatic"}
```

kind: history/local_verify; trigger: automatic/manual. Weryfikacja lokalna
jest wyłącznie ręczna. Odpowiedzi: queued/coalesced (202), fresh/limited/unavailable
(200) ze stabilnym reason i ewentualnym retry_at. Nieznana liga: 404; błędne
pola/typy: 400; brak JSON: 415; obcy Origin: 403; niedostępna baza: 503.
GET nie zgłasza zadań. Odpowiedzi mają Cache-Control: no-store.

Vue odczytuje status co sekundę przy aktywnym zadaniu, poza tym co 5 sekund.
Nowa rewizja odświeża metadane i transakcje bez przeładowania strony, zachowując
URL, ligę, język, zastosowane filtry, niewysłany formularz, sort i stronę
(z dotychczasowym ograniczeniem do istniejących stron). Odpowiedzi dla
opuszczonej ligi są ignorowane/abortowane. Zmiana samego języka nie zgłasza zadań.

## Launcher i wdrożenie

```sh
./poe2guild start
./poe2guild status
./poe2guild logs
./poe2guild restart
./poe2guild stop
```

start/restart stosuje migracje przez CLI, startuje web i worker (osobna sesja procesu przez setsid); start jest
idempotentny i uzupełnia brakujący proces. stop kończy najpierw worker, potem
web. Czas kontrolowanego zatrzymania każdego procesu: do 35 sekund; po tym
czasie pozostawia rekordy PID do inspekcji, bez automatycznego SIGKILL.
status sprawdza web health oraz PID i heartbeat workera; kod 0 = oba zdrowe,
1 = częściowa awaria, 3 = oba zatrzymane. Żywy worker ze starym heartbeat
wymaga inspekcji/restartu; start nie uruchamia drugiego procesu w jego miejsce.

PIDs/tożsamości: .run/gunicorn.* oraz .run/worker.*. Weryfikowane są użytkownik,
katalog procesu, argumenty i starttime PID, aby nie sygnalizować innego checkoutu.
Logi: logs/gunicorn.log i logs/worker.log; logs śledzi oba. Nie zmieniano
konfiguracji nginx ani starej usługi na porcie 9001.

Przed wdrożeniem zatrzymano nową usługę i wykonano kopię SQLite przez backup API:
data/poe2guild.before-phase3.sqlite (poza Git). Migracja 2 została zastosowana,
web i worker uruchomione na porcie 9002. Nie odtwarzano danych ze starego katalogu.

## Walidacja

```sh
.venv/bin/python -m unittest discover -s tests -q
bash tests/test_service.sh
npm --prefix frontend run test:locales
npm --prefix frontend run build
npm --prefix frontend run test:browser
```

Testy obejmują równoczesne zgłoszenia z dwóch procesów, scope między ligami,
limit/rezerwacje/freshness, manual/cooldown, retry i jego wyczerpanie, heartbeat,
renew, odzyskanie kolejki, zabicie rzeczywistego procesu i przejęcie lease,
fencing starego wyniku i rollback, atomowy zapis rewizji/kursora, błędy lokalnych
danych, ochronę archiwów, migrację ze schematu 1, walidację HTTP oraz launcher
z izolowanymi procesami i obcym checkoutem. Testy nie kontaktują się z GGG.

Wyniki: 73 testy backendu (26 nowych testów kolejki/workera/API),
32 testy Chromium (6 nowych scenariuszy), 16 testów katalogów tłumaczeń
oraz integracyjny skrypt launchera/nginx — wszystkie przechodzą. Skrypt
launchera sprawdza także osobną sesję workera i heartbeat niezależnie od PID.

Przeglądarka testowa uruchamia osobny proces workera z tymczasową bazą.
Weryfikuje prawdziwą pracę lokalną, odzyskanie panelu po awarii, błąd zgłoszenia,
zmianę rewizji przy zachowaniu kontekstu, porzucone odpowiedzi i tłumaczenia.
Nie wymaga mutowania produkcyjnej bazy dla symulacji nowej historii.

Smoke test przez publiczny nginx potwierdził trwałość procesu po zakończeniu
polecenia startowego i kontrolowany restart obu procesów, zachowanie wszystkich
104 534 rekordów po migracji, weryfikację 15 344 + 89 190 rekordów obu lig, blokadę
fetchowania archiwów, niezmienione daty synchronizacji/generowania, przełączanie
PL/EN, układ mobilny i brak błędów JavaScript.

Po odbiorze następna osobna faza to 4: obliczenia ilościowe.
