# poe2guild — rework

Niezależny szkielet Vue + TypeScript + Vite oraz Flask/Gunicorn.
Rework kontynuuje historię repozytorium na branchu `rework/vue-flask`.
Poprzednia aplikacja pozostaje w sąsiednim `../poe2-guild`.

Plan etapów i kryteria odbioru: [docs/implementation-plan.md](docs/implementation-plan.md).
Wymagania nowych funkcji i ograniczenia integracji dostawców:
[docs/architecture.md](docs/architecture.md).

Faza 0: [wyniki audytu i instrukcja odbioru](docs/phase-0.md),
[kontrakty modułów](docs/contracts.md).

Faza 1: [SQLite, import i instrukcja odbioru](docs/phase-1.md).

Faza 2: [historia transakcji, filtry i archiwa HTML](docs/phase-2.md).
Domyślny widok to Historia; wcześniejsze wyniki audytu są w Diagnostyce.

Faza 2a: [języki PL/EN, katalogi tłumaczeń i instrukcja odbioru](docs/phase-2a.md).
English jest językiem domyślnym i fallbackiem. Wybór w nagłówku zachowuje
kontekst ligi i filtrów; języki wynikają z frontend/src/locales/*.json.

Faza 3: [worker, kolejka i odświeżanie](docs/phase-3.md). Panel Historii pozwala
zweryfikować lokalne dane; archiwa nie pobierają historii GGG.

Faza 4: [wyliczone ruchy, podsumowania i ustawienia gildii/ligi](docs/phase-4.md).
Historia pokazuje źródłową akcję oraz własną deltę i akcję zastępczą; archiwalne
dane pozostają niezmienione. Każda liga ma niezależną historię i stan.

Faza 4b: [nowa organizacja panelu i nawigacji](docs/phase-4b.md).
Startowym widokiem jest Podsumowanie; Historia, Ustawienia i Raporty archiwalne
są osobnymi sekcjami. Szczegóły synchronizacji znajdują się w Diagnostyce.

Faza 5: [interaktywne wykresy ilościowe](docs/phase-5.md). Wybór przedmiotu,
zoom, przesuwanie, serie i zakres wspólny z filtrami raportu.

## Instalacja i uruchamianie

Wymagane: Linux, Python 3.10+ z venv/pip, Node.js 22.12+ (zalecany aktualny
LTS) z npm, Bash, flock, setsid, curl i narzędzia systemowe. Na tym serwerze Node.js
jest zainstalowany w katalogu użytkownika i dostępny przez `~/.local/bin`.

```sh
cd /home/nginx-http/poe2guild
./poe2guild build
./poe2guild start
./poe2guild status
./poe2guild logs
```

`build` tworzy `.venv`, instaluje zależności Pythona i npm (`npm ci`),
sprawdza TypeScript oraz buduje frontend. Node jest potrzebny tylko do budowania
i developmentu; produkcję obsługuje Gunicorn. `restart` nie przebudowuje kodu. Start/restart stosuje migracje SQLite i uruchamia
web oraz osobny worker.

| Komenda | Działanie |
| --- | --- |
| `build` | Przygotowanie zależności i produkcyjnego frontendu |
| `start` | Migracje i web + worker w tle; ponowne wywołanie jest bezpieczne |
| `stop` / `restart` | Zatrzymanie / restart obu procesów tego katalogu |
| `status` | PID-y obu procesów, heartbeat workera i `/health`; częściowa awaria: kod 1 |
| `logs` lub `log` | Blokujący podgląd `logs/gunicorn.log` i `logs/worker.log` |
| `install` / `uninstall` | Dodanie / usunięcie trasy Nginx; root/sudo |

Konfiguracja jest w `service.ini`: port `127.0.0.1:9002`, prefiks `/poe2guild`.
Zmiana prefiksu wymaga przebudowania frontendu. Opcjonalny lokalny `service.env`
jest ignorowany przez Git. Polecenia aplikacji uruchamiaj jako `nginx-http`;
tylko instalacja trasy wymaga roota. PID i blokady są w `.run/`.

## Nginx i Screen

```sh
sudo /home/nginx-http/poe2guild/poe2guild install --dry-run
sudo /home/nginx-http/poe2guild/poe2guild install
```

Installer aktualizuje wyłącznie trasę wybraną w `service.ini`, zachowuje pozostałe
usługi, sprawdza `nginx -t` i przeładowuje Nginx. Błąd wycofuje zmianę.
Przykładowy fragment do ręcznej instalacji wewnątrz bloku `server`:
`deploy/nginx/poe2guild.conf`. Nie instaluj go równocześnie z generowaną trasą.

Adres: http://dyyyl.ovh/poe2guild/ . Stara aplikacja używa `/poe2-guild/` i portu
9001. Główny `~/start.sh` ma osobne wpisy obu usług i okna Screen.

## Struktura

```text
backend/                 Flask API i obsługa zbudowanego frontendu
frontend/src/            Vue + TypeScript
frontend/dist/           wynik builda (poza Git)
data/leagues/<liga>/     niezależne kopie CSV, raportów, wykresów i cen
data/import-manifest.json  liczby transakcji i SHA-256 skopiowanych plików
data/poe2guild.sqlite     baza SQLite (poza Git)
backend/migrations/      wersjonowany schemat bazy
scripts/                 importer archiwów i edytor konfiguracji Nginx
deploy/nginx/            przykład konfiguracji reverse proxy
tests/                   testy API, importu i launchera
```

Stary generator raportów, fetcher, globalny stan oraz stary frontend zostały
usunięte z tego katalogu. Historyczne HTML są wyłącznie danymi archiwalnymi,
nie implementacją nowego interfejsu. Faza 2 udostępnia zarejestrowane raporty
w osobnych, izolowanych dokumentach; katalog danych nie jest publicznym statycznym katalogiem.
Szkielet nie pobiera danych gry, nie używa sesji PoE i nie przelicza archiwów.

Odtworzenie danych ze starego katalogu:

```sh
.venv/bin/python scripts/import-legacy-data.py --source ../poe2-guild
```

Importer kopiuje pliki i weryfikuje SHA-256. Powtórzenie z tymi samymi danymi
jest bezpieczne; przy różnej zawartości istniejącego archiwum przerywa pracę.
Baza SQLite (obecnie schemat 3) jest tworzona z tych danych lub z niezależnej kopii starego
katalogu. Komendy fazy 1:

```sh
.venv/bin/python scripts/database.py init
.venv/bin/python scripts/database.py import
.venv/bin/python scripts/database.py status
.venv/bin/python scripts/database.py verify
```

Pełne odtworzenie, polityka konfliktów i przechowywanie surowych danych są
opisane w [docs/phase-1.md](docs/phase-1.md). API udostępnia podgląd stanu bazy, listę lig i stronicowane transakcje.
Filtry i wybór ligi są zapisywane w query string; opis endpointów jest
w [docs/phase-2.md](docs/phase-2.md).

## Development i testy

```sh
# Backend na porcie 9002
.venv/bin/flask --app app run --host 127.0.0.1 --port 9002
# W innym terminalu, z katalogu frontend/
npm run dev

.venv/bin/python -m unittest discover -s tests -v
bash tests/test_service.sh
npm --prefix frontend run test:locales
npm --prefix frontend run build
npm --prefix frontend run test:browser
```

Vite w development proxy'uje `/api` do portu 9002. W produkcji Nginx usuwa
prefiks `/poe2guild/`, a Flask obsługuje API i statyczny build. `/health` służy
launcherowi; `/api/health` sprawdza połączenie strony z właściwą usługą.
Nieznane adresy API i zasobów zwracają 404, a nie dokument HTML.
