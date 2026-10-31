# Poe2Logger

Aplikacja Flask wyświetla zapisany raport gildii. Dane źródłowe są przechowywane
w CSV w `logs/`, a raport HTML jest publikowany dopiero po zakończeniu generowania.

## Uruchomienie

Zainstaluj `required.txt`, ustaw konfigurację prywatną lub zmienne środowiskowe
`POE_GUILD_ID` i `POESESSID` / `POE_SESSION_ID`, następnie uruchom aplikację:

```sh
python -m pip install -r required.txt
python -m flask --app app run
```

Serwer produkcyjny na Linuxie może używać `gunicorn app:app`.

## Usługa na Ubuntu (systemd)

W katalogu projektu na serwerze przygotuj środowisko jako użytkownik aplikacji:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r required.txt
python3 service.py install
python3 service.py start
```

Jeśli brakuje modułu `venv`, zainstaluj `sudo apt install python3-venv`.
Instalator sam używa `sudo` do operacji systemowych. Przy uruchomieniu jako root
podaj konto aplikacji: `python3 service.py install --user NAZWA_UZYTKOWNIKA`.
Konto musi mieć dostęp do projektu i możliwość zapisu raportów, logów CSV
oraz stanu odświeżania. Istniejący katalog `venv` także jest wykrywany;
inne środowisko wskaż przez `--venv /sciezka/do/venv`.

```sh
python3 service.py status
python3 service.py stop
python3 service.py start
python3 service.py restart
python3 service.py logs
```

`status` pokazuje stan procesu i ostatnie logi; dla zatrzymanej usługi zwraca
niezerowy kod systemctl. `logs` śledzi dziennik do przerwania przez Ctrl+C.
Te same operacje są dostępne bez skryptu:

```sh
sudo systemctl status poe2logger --no-pager
sudo systemctl stop poe2logger
sudo systemctl start poe2logger
sudo systemctl restart poe2logger
sudo journalctl -u poe2logger -n 100 -f
```

Instalacja tworzy `/etc/systemd/system/poe2logger.service` i włącza autostart
po restarcie serwera; osobne `start` uruchamia usługę od razu. systemd ponawia
uruchomienie po awarii, a ręczne `stop` pozostawia usługę zatrzymaną.
Gunicorn działa w katalogu rzeczywistym projektu (po rozwiązaniu symlinków)
z dwoma procesami i czterema wątkami na proces.

Domyślny adres to `127.0.0.1:8000`, np. dla reverse proxy. Do bezpośredniego
dostępu z sieci ustaw adres podczas instalacji:

```sh
python3 service.py install --bind 0.0.0.0:8000
python3 service.py restart
```

Jeśli aplikacja jest obecnie uruchomiona inną metodą na tym samym porcie,
zatrzymaj poprzedni proces przed pierwszym `start`.
Konfiguracja `private_config.py` pozostaje używana. Zmienne środowiskowe usługi
możesz dodatkowo zapisać w opcjonalnym `/etc/poe2logger.env`, np.
`POESESSID=...` i `POE_GUILD_ID=...` (po jednej na wiersz). Usługa nie dziedziczy
zmiennych z interaktywnej sesji SSH. Po zmianie konfiguracji wykonaj `restart`.

Po aktualizacji projektu:

```sh
git pull
.venv/bin/python -m pip install -r required.txt
python3 service.py restart
```

Po przeniesieniu projektu lub zmianie ustawień usługi wykonaj ponownie
`install`, a następnie `restart`. `install --dry-run` pokazuje wygenerowaną
konfigurację bez jej instalowania. Dostępność HTTP sprawdzisz przez
`curl --fail http://127.0.0.1:8000/health` (nie wywołuje fetcha).

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
node --check static/refresh.js
```

Test przeglądarkowy `node tests/browser_refresh.cjs` wymaga modułu Playwright
i jego Chromium. Opcjonalne zmienne `PLAYWRIGHT_MODULE`, `TEST_PYTHON` oraz
`BROWSER_CHANNEL` wskazują niestandardowe środowisko. Test renderuje rzeczywisty
szablon z syntetycznymi danymi, symuluje dwóch klientów i przechwytuje ruch
aplikacji. Testy nie odpytują API gry ani nie modyfikują zapisanych raportów.
