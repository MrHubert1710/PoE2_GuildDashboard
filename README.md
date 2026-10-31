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
