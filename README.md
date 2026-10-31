# Poe2Logger

Aplikacja Flask pobiera historię skrytki gildii i wyświetla raport HTML.
Dane źródłowe są przechowywane w CSV w `logs/`. Nowy raport zastępuje
poprzedni dopiero po zakończeniu generowania.

## Wymagania

- Linux, Bash, Python 3 z modułem venv i pip.
- Gunicorn i Flask z `required.txt` (instalowane przez `build`).
- Narzędzia systemowe: `flock`, `curl`, `awk`, `readlink`, `ps`, `stat`.
- Nginx dla publikacji przez reverse proxy; `sudo` tylko do jego konfiguracji.

Przygotuj `poe2logger/private_config.py` zgodnie z importami aplikacji.
Identyfikator gildii i sesję można nadpisać zmiennymi `POE_GUILD_ID`
i `POESESSID` / `POE_SESSION_ID`.

## Zarządzanie lokalne

Skrypt Bash `poe2guild` zarządza Gunicornem bez systemd. Można go wywoływać
z powłoki w istniejącej sesji screen lub ze skryptu startowego serwera,
uruchomionego pod kontem aplikacji. Sam skrypt nie tworzy sesji screen.
Autostart po restarcie systemu zapewnia zewnętrzny mechanizm startowy serwera.
Linger ani jednostki systemd użytkownika nie są używane.

```sh
./poe2guild build
./poe2guild start
./poe2guild status
```

| Polecenie | Działanie | Uprawnienia |
| --- | --- | --- |
| `./poe2guild build` | Tworzy virtualenv w razie potrzeby i instaluje `required.txt`. | Konto aplikacji |
| `./poe2guild start` | Uruchamia Gunicorn w tle; ponowne wywołanie nie tworzy drugiej instancji. | Konto aplikacji |
| `./poe2guild stop` | Wysyła TERM do zapisanego procesu Gunicorna i czeka na zakończenie. | Konto aplikacji |
| `./poe2guild restart` | Zatrzymuje i uruchamia aplikację; nie przebudowuje zależności. | Konto aplikacji |
| `./poe2guild status` | Pokazuje PID, katalog projektu, adres i wynik sprawdzenia `/health`. | Konto aplikacji |
| `./poe2guild logs` | Pokazuje ostatnie 100 linii logu i śledzi kolejne; Ctrl+C kończy podgląd. | Konto aplikacji |
| `./poe2guild install` | Dodaje brakujące wpisy trasy Nginx, testuje konfigurację i przeładowuje Nginx. | Root przez sudo |
| `./poe2guild uninstall` | Usuwa wpisy tej trasy, testuje konfigurację i przeładowuje Nginx. | Root przez sudo |
| `./poe2guild help` | Wyświetla pomoc. | Bez dodatkowych uprawnień |

Tylko `install` i `uninstall` wywołują `sudo`, jeśli nie są już uruchomione
jako root. Nie budują, nie uruchamiają ani nie zatrzymują aplikacji.
Pozostałe operacje wykonuj jako konto aplikacji; skrypt odrzuca je jako root.

Gunicorn daemonizuje się, zapisuje PID w `.run/gunicorn.pid`, tożsamość procesu
w `.run/gunicorn.identity`, a logi w `logs/gunicorn.log`. Te pliki są lokalne
i pomijane przez Git. Przed zatrzymaniem sprawdzany jest właściciel procesu,
katalog roboczy, polecenie i czas jego uruchomienia, aby nie zatrzymać innego
procesu po ponownym wykorzystaniu PID-u. Skrypt nie zabija procesów tylko
dlatego, że zajmują skonfigurowany port.

Gunicorn działa z dwoma procesami i czterema wątkami na proces. Operacje
zarządzania są serializowane przez `flock`. `status` zwraca kod 3 dla
zatrzymanej aplikacji, 1 dla nieudanego sprawdzenia HTTP i 0 dla działającej,
zdrowej aplikacji. `stop` czeka do 35 sekund na łagodne zakończenie.

## Konfiguracja

Plik `service.ini` obok skryptu:

```ini
[service]
bind = 127.0.0.1:9001
venv =
url_prefix = /poe2-guild
nginx_file = /etc/nginx/sites-enabled/services
nginx_server =
```

- `bind`: lokalny adres Gunicorna w formacie `127.0.0.1:PORT`.
- `venv`: ścieżka virtualenv, względna względem projektu lub absolutna.
  Pusta wartość wykrywa `.venv`, następnie `venv`, zawierające Gunicorna;
  `build` tworzy `.venv`, jeśli nie znajdzie istniejącego środowiska.
- `url_prefix`: ścieżka publiczna aplikacji bez końcowego ukośnika.
- `nginx_file`: istniejący plik konfiguracji Nginx, którego właścicielem jest
  root. Symlink jest rozwiązywany, a aktualizacja zachowuje jego cel.
- `nginx_server`: pojedyncza wartość `server_name`, wskazująca blok do edycji.
  Można pozostawić puste, jeśli plik zawiera dokładnie jeden blok `server`.
  Niejednoznaczny wybór zatrzymuje operację bez zmian.

Ustawienia są odczytywane jako dane, bez wykonywania poleceń powłoki.
Po zmianie adresu wykonaj `restart` dla aplikacji i `install` dla Nginx.
Przy zmianie prefiksu najpierw wykonaj `uninstall` ze starym prefiksem,
a następnie zmień ustawienie i uruchom `install`.

Opcjonalne zmienne środowiskowe aplikacji zapisz lokalnie w `service.env`:

```text
POE_GUILD_ID=...
POESESSID=...
```

Format to `NAME=value`, bez cudzysłowów i rozwijania zmiennych lub poleceń.
Plik jest pomijany przez Git i odczytywany przy starcie aplikacji.
Po zmianach wykonaj `restart`. Konto aplikacji musi mieć dostęp do projektu
oraz możliwość zapisu logów, raportów i `.run/`.

## Instalacja trasy Nginx

Najpierw ustaw `service.ini` odpowiednio do istniejącego pliku `services`.
Skrypt oczekuje gotowego bloku `server`; nie tworzy hosta, certyfikatów ani
konfiguracji nasłuchu. Podgląd i zastosowanie zmian:

```sh
./poe2guild install --dry-run
./poe2guild install
```

Dla domyślnych ustawień dodawane są lokalizacje `/poe2-guild/` kierująca do
`http://127.0.0.1:9001/` i `/poe2-guild` przekierowująca na wersję z ukośnikiem.
Nginx usuwa prefiks przed przekazaniem żądania do aplikacji. Strona używa
względnych adresów API i skryptu odświeżania, dzięki czemu działa pod prefiksem.

Skrypt sprawdza istniejące lokalizacje. Zgodny wpis pozostawia bez zmian,
wraz z jego dodatkowymi dyrektywami. Konflikt z innym upstreamem zatrzymuje
operację. Dodane przez skrypt fragmenty są oznaczone komentarzami
`BEGIN/END poe2guild`; ponowna instalacja ich nie dubluje.

Edycja jest chroniona wspólną blokadą. Przed zmianą sprawdzana jest aktualna
konfiguracja, a po zapisie wykonywane jest `nginx -t` i `nginx -s reload`.
Błąd walidacji lub przeładowania przywraca poprzedni plik. Pozostałe usługi
w pliku są zachowywane. Pliki tymczasowe pozostają pod uprawnieniami roota.

Usunięcie trasy bez zatrzymywania aplikacji:

```sh
./poe2guild uninstall --dry-run
./poe2guild uninstall
```

Usuwane są zarządzane fragmenty oraz zgodne lokalizacje tej trasy w wybranym
bloku `server`. Przy nieoznaczonej trasie upstream musi odpowiadać `bind`.
Skrypt nie usuwa całego pliku `services`.

## Aktualizacja i diagnostyka

```sh
git pull
./poe2guild build
./poe2guild restart
./poe2guild status
curl --fail http://127.0.0.1:9001/health
```

Dostosuj port do `bind`. `/health` nie wywołuje fetcha danych.
Przy problemach uruchom `./poe2guild logs`. Po przeniesieniu projektu
zatrzymaj proces ze starego katalogu i uruchom aplikację z nowego.

Jeśli wcześniej aplikacja była uruchamiana przez systemd, administrator
powinien jednorazowo zatrzymać i wyłączyć jej starą jednostkę przed `start`:

```sh
sudo systemctl disable --now STARA_USLUGA.service
```

Zastąp nazwę właściwą jednostką aplikacji. Skrypt nie migruje ani nie zatrzymuje
starych procesów automatycznie. Nginx pozostaje zarządzany przez administratora;
`install`/`uninstall` zmieniają wyłącznie trasę aplikacji i przeładowują konfigurację.

## Odświeżanie

- Wejście na stronę natychmiast zwraca ostatni zapisany raport i uruchamia
  odświeżanie w tle, o ile limit na to pozwala.
- Limit jest wspólny dla klientów i procesów: maksymalnie dwie automatyczne
  próby w ruchomym oknie 3600 sekund, także gdy próba zakończy się błędem.
  Ustawienia: `AUTO_REFRESH_LIMIT` i `AUTO_REFRESH_WINDOW_SECONDS` w `config.py`.
- Kliknięcie pilla pomija limit automatyczny. Równoległe żądania dołączają
  do już trwającego odświeżania. Nagłówki limitów API, `Retry-After`, opóźnienia
  i ponowienia nadal obowiązują. Termin kolejnego dozwolonego zapytania jest
  zapisywany także pomiędzy osobnymi odświeżeniami.
- Otwarte strony sprawdzają lokalny status co trzy sekundy. Nowy raport,
  również wygenerowany przez `python main.py --fetch-history`, aktualizuje
  wszystkich klientów. Zakładka, wybrany gracz/skrytka, widok logu, filtry,
  sortowanie i przewinięcie są odtwarzane przy użyciu `sessionStorage`.
- Błąd pozostawia poprzedni raport i datę ostatniego udanego odświeżenia.
  Czerwony baner nie ujawnia przyczyny. Znika po kolejnym udanym odświeżeniu.
  Przed pierwszym udanym fetchem data jest oznaczona jako nieznana; nie jest
  wyliczana z daty zdarzeń w CSV.

Wszystkie procesy WWW i CLI muszą pracować w tym samym katalogu projektu
i korzystać ze wspólnego lokalnego dysku. Zachowaj `logs/`, `stash_reports/`
oraz `GuildReport_Latest.html` między restartami. Stan limitu jest w
`stash_reports/refresh_state.json`, a blokada systemowa w `refresh.lock`.
Zadanie działa w wątku procesu WWW; zakończenie procesu przerywa zadanie,
zwalnia blokadę i przy następnym odczycie statusu zgłasza nieudaną próbę.
Wdrożenie na wielu niezależnych hostach wymaga wspólnej kolejki zadań i magazynu
raportów zamiast lokalnej blokady plikowej.

## Testy

```sh
python -m unittest discover -s tests -v
bash tests/test_service.sh
node --check static/refresh.js
```

Test przeglądarkowy `node tests/browser_refresh.cjs` wymaga modułu Playwright
i jego Chromium. Opcjonalne zmienne `PLAYWRIGHT_MODULE`, `TEST_PYTHON` oraz
`BROWSER_CHANNEL` wskazują niestandardowe środowisko. Test renderuje rzeczywisty
szablon z syntetycznymi danymi, symuluje dwóch klientów i przechwytuje ruch
aplikacji. Testy nie odpytują API gry ani nie modyfikują zapisanych raportów.
