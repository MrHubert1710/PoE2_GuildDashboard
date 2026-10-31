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
Domyślnie instalowana jest **usługa bieżącego użytkownika**, bez `sudo`,
w `~/.config/systemd/user/poe2logger.service` (lub w `XDG_CONFIG_HOME/systemd/user`).
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
systemctl --user status poe2logger --no-pager
systemctl --user stop poe2logger
systemctl --user start poe2logger
systemctl --user restart poe2logger
journalctl --user -u poe2logger -n 100 -f
```

Instalacja włącza usługę w menedżerze użytkownika; osobne `start` uruchamia ją
od razu. Aby startowała także po restarcie serwera przed logowaniem i działała
po wylogowaniu z SSH, włącz linger dla swojego konta:

```sh
loginctl enable-linger "$USER"
loginctl show-user "$USER" -p Linger
```

Wynik powinien zawierać `Linger=yes`. Jeśli polityka serwera wymaga uprawnień
administratora, administrator może jednorazowo wykonać
`sudo loginctl enable-linger NAZWA_UZYTKOWNIKA`. Skrypt nie wywołuje `sudo`
w trybie użytkownika. Polecenia uruchamiaj w zwykłej sesji SSH tego konta,
w której dostępny jest menedżer `systemd --user`.

systemd ponawia
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
możesz dodatkowo zapisać w opcjonalnym `~/.config/poe2logger/environment`
(lub `XDG_CONFIG_HOME/poe2logger/environment`), np.
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

### Opcjonalna usługa systemowa: `--root`

Flaga `--root` przełącza każdą operację na usługę systemową. Może wystąpić
przed lub po poleceniu. Tylko ten tryb korzysta z `sudo`, zapisuje jednostkę
w `/etc/systemd/system/poe2logger.service` oraz odczytuje `/etc/poe2logger.env`.
`--root` wybiera zasięg usługi; sama aplikacja działa jako konto z `--user`.

```sh
python3 service.py install --root --user NAZWA_UZYTKOWNIKA
python3 service.py start --root
python3 service.py status --root
python3 service.py stop --root
python3 service.py restart --root
python3 service.py logs --root
```

Przy przejściu ze starszej usługi systemowej na usługę użytkownika zatrzymaj
i wyłącz poprzedni autostart, aby dwie instancje nie zajmowały tego samego portu:

```sh
sudo systemctl disable --now poe2logger.service
python3 service.py install
python3 service.py start
```

Jeśli używałeś `/etc/poe2logger.env`, przenieś potrzebne ustawienia do pliku
środowiskowego użytkownika. Zmiany właściciela istniejących danych i wyłączenie
starej usługi wykonuje administrator; nowa instalacja nie zmienia ich automatycznie.

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
