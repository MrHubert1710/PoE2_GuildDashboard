# Faza 5 — interaktywne wykresy ilościowe

Status: implementacja zakończona i wdrożona, oczekuje odbioru manualnego.
Faza 6 nie jest rozpoczęta.
Poprzednia faza 4b wraz z poprawkami została zaakceptowana przez użytkownika.

## Widoczny rezultat

Podsumowanie, Gracze i Skrytki pokazują wykres Ruchy w czasie nad tabelą raportu.
Każdy wykres dotyczy jednego przedmiotu: dodania, usunięcia i bilans ruchów
w kolejnych przedziałach czasu. Bilans to dodano minus usunięto w przedziale,
a nie bieżąca liczba przedmiotów w gildii. Usunięcia są rysowane poniżej zera.
Nie sumujemy sztuk różnych przedmiotów. Stan skrytek nadal pokazuje odtworzony
stan końcowy, a Historia źródłowe wpisy; nie zastępujemy ich wykresem przepływów.

Wspólne filtry gracza, wielu skrytek, przedmiotu i dat UTC obejmują wykres,
raport i historię. Tryby regex, Aa i pełnych słów mają tę samą semantykę.
Wyłączone w ustawieniach zakładki nie wchodzą do wykresu. Alias łączy surowe
nazwy zgodnie z projekcją; wielokrotny wybór nazwy i aliasu nie dubluje ruchów.
Reguły quantities-v3, w tym opróżnianie slotu przez źródłowy Removed, nie zmieniają się.

Lista przedmiotów pokazuje do 50 najbardziej aktywnych pasujących nazw
(według sumy bezwzględnych ruchów). Pierwsza jest domyślna. Filtr przedmiotu
pozwala znaleźć inne nazwy; jawnie wybrany przedmiot pozostaje w selektorze
również bez pasujących ruchów. Lista nie jest pełnym katalogiem wszystkich
przedmiotów, a tabela raportu pozostaje stronicowana.

Interakcje:

- Tooltip z datą i wartościami w strefie wyświetlania ligi.
- Checkboxy serii, przybliżanie przyciskiem lub kółkiem myszy, przesuwanie
  wewnątrz wykresu i dolny suwak.
- Resetuj widok przywraca cały aktualnie pobrany zakres, zachowując filtry.
- Zastosuj zakres do filtrów zaokrągla zaznaczenie na zewnątrz do pełnych dni
  UTC i aktualizuje wspólne filtry, tabelę i podsumowanie. Nie udaje filtra godzinowego.
- Odśwież wykres ponawia tylko odczyt szeregu. Odśwież widok ponawia cały
  bieżący kontekst. Żadna z tych akcji nie fetchuje GGG ani nie przelicza projekcji.
- Rozwijana tabela danych daje dostęp do wszystkich zwróconych punktów bez
  interakcji z grafiką. Przyciski i checkboxy są obsługiwane klawiaturą.

Wykres przedstawia ustalone ruchy, również oznaczone ruchy wywnioskowane.
Liczba nieustalonych zdarzeń wybranego przedmiotu jest pokazywana oddzielnie;
nie zamieniamy ich nieznanych ilości na pewne zera. Puste przedziały znanych
ruchów są zerowe. Suma wywnioskowanych jednostek jest opisana pod wykresem.

## Stan i cykl życia

chart_item to dokładna nazwa wybranego przedmiotu, chart_from/chart_to to
bezwzględne granice zoomu w milisekundach UTC, chart_series to lista serii.
Stan pozostaje po odświeżeniu, zmianie języka, przejściu między widokami i reloadzie.
Zmiana przedmiotu ma historię Wstecz/Dalej. Zoom i checkboxy zastępują bieżący
wpis URL. Zmiana ligi usuwa kontekst wykresu poprzedniej ligi; powrót przez
Wstecz odtwarza zapisany adres. Puste lub niepoprawne granice wracają do pełnego
zakresu, a poprawny zoom jest przycinany do nowego zakresu danych.

Biblioteka ECharts 6.1.0 jest przypięta w package-lock.json, importowana modułowo
i ładowana jako osobny chunk dopiero po pierwszych danych wykresu. Wejście
bezpośrednio do Historii, Ustawień lub Stanu nie pobiera ECharts ani szeregu.
ResizeObserver obsługuje zmianę szerokości i odkrycie widoku. Instancja jest
zwalniana po odmontowaniu; tooltip jest renderowany w SVG/rich text, bez HTML
z nazw przedmiotów. Przy zmianie filtrów stary wykres jest usuwany do czasu
odpowiedzi. Sekwencjonowanie i anulowanie kontekstu chronią przed spóźnioną
odpowiedzią innej ligi. Błąd wykresu ma własny retry i nie usuwa tabeli raportu.

## Kontrakt API

GET /api/leagues/{league_id}/quantity-series

Parametry: wspólne filtry account/stash/item/from/to i flagi wyszukiwania,
revision, projection_id, series_item (dokładna nazwa), max_points (24–600,
domyślnie 240). Powtarzane stash są dozwolone; pozostałe parametry są pojedyncze.
Stan projekcji missing/stale ma puste dane; GET nie tworzy zadań.
Nieaktualne przypięte identyfikatory zwracają 409, błędne parametry 400.

Odpowiedź ma league_id, metadane projection, timezone, unit=item_count,
items, item, unresolved_events, bounds, bucket_seconds, max_points, totals
oraz points. Granice i timestamp/end punktu to milisekundy UTC; end jest
wyłączne. Punkt zawiera added, removed (dodatnia ilość), net i inferred.
Format nie zawiera opcji ani identyfikatorów ECharts, więc może służyć innemu
rendererowi i zostać rozszerzony o szeregi wartości w osobnej fazie 6.

Backend wybiera przedział od minuty do wielodniowego na podstawie zakresu
oraz limitu. Agreguje w SQL zapisane quantity_movements, po odtworzeniu pełnej
historii przez quantities-v3, a następnie uzupełnia zerami brakujące przedziały.
Liczba punktów nigdy nie przekracza limitu; szerokie zakresy nie powodują
wysyłania całej historii. Granice domyślne obejmują pełne dni UTC z ruchami
wybranego przedmiotu; jawne filtry dni mogą rozszerzyć obszar zerowy.
Sumy punktów są zgodne z raportem dla tego samego przedmiotu i filtrów.

## Podział kodu

- backend/quantity_series.py — walidacja, katalog i ograniczona agregacja SQL.
- frontend/src/composables/useQuantitySeries.ts — odczyt i ochrona odpowiedzi.
- QuantityChart.vue — wybór przedmiotu/serii, URL, przyciski, stany, tabela danych.
- TimeSeriesChart.vue — modułowy ECharts/SVG, tooltip, zoom, resize, dispose.
- QuantityPanel.vue — umieszczenie wykresu przed tabelą gotowego raportu.
- HistoryBrowser/useHistory/browsing — przekazanie projekcji i wspólnego zakresu.

Nie zmieniono schematu SQLite, danych źródłowych, projekcji, ustawień gildii,
workera ani integracji GGG. Nie generujemy HTML ani obrazków wykresów. Wycenę,
snapshoty cen i katalog poe.ninja pozostawiono do fazy 6.

## Weryfikacja i wydajność

```sh
.venv/bin/python -m unittest discover -s tests -q
npm --prefix frontend run test:locales
npm --prefix frontend run build
npm --prefix frontend run test:browser
```

Testy backendu porównują sumy, ograniczenie punktów, zera, izolację lig,
wyłączenie/aliasy skrytek, wyszukiwanie, UTC niezależne od strefy, brak generacji
przez GET, stare identyfikatory, skrajne daty i nieustalone zdarzenia.
Testy przeglądarkowe sprawdzają wybór przedmiotu, tooltip, rzeczywisty zoom
kółkiem i drag, serie, reset, filtr dni, refresh/reload, historię URL, zmianę
ligi, opóźnione odpowiedzi, retry, brak zbędnego ładowania, PL/EN i mobile.

Pomiar na rzeczywistych zapisanych ustawieniach, trzy lokalne odczyty każdego
archiwum, mediana całej odpowiedzi przez Flask test client:

| Liga | Mediana | Punkty | JSON | Przedział |
| --- | ---: | ---: | ---: | ---: |
| Forbidden Rites | 18,4 ms | 144 | 15 197 B | 6 h |
| Runes of Aldur | 102,3 ms | 220 | 22 893 B | 6 h |

To pomiar na tym serwerze, nie gwarancja czasu dla każdego filtra. Sumy punktów
w obu archiwach porównano z odpowiadającym wierszem raportu. Chunk ECharts jest
większy od głównego kodu aplikacji, ale pobierany oddzielnie i tylko do wykresu.

## Odbiór manualny

1. Otwórz /poe2guild/?lang=pl. Pod kartami Podsumowania powinien być wykres.
2. Zmień przedmiot, gracza i skrytki; porównaj sumy z tabelą.
3. Najedź na wykres, użyj kółka, przeciągnij środek i dolny suwak.
4. Wyłącz serię, odśwież widok i przejdź do Graczy/Skrytek — zoom i serie zostają.
5. Zastosuj zakres do filtrów; sprawdź daty UTC i wyniki Historii.
6. Zresetuj zoom, wybierz inną ligę, sprawdź Wstecz/Dalej i reload.
7. Sprawdź PL/EN, telefon oraz rozwijaną tabelę danych.

Źródła API biblioteki: [import modułowy](https://echarts.apache.org/handbook/en/basics/import/),
[zdarzenia i akcje](https://echarts.apache.org/handbook/en/concepts/event/),
[rozmiar i cykl życia](https://echarts.apache.org/handbook/en/concepts/chart-size/).


## Wynik końcowy

127 testów backendu, 64 przeglądarkowe i 16 tłumaczeń zakończone powodzeniem;
build TypeScript/Vite poprawny. Osobny test granicy dnia potwierdza, że wpis
23:59:59.999999 UTC pozostaje w ostatnim przedziale właściwego dnia (bez
zaokrąglenia przez SQLite do następnego dnia).

Publiczny nginx potwierdził na obu archiwach zgodność sum wykresu z tabelą,
zoom i serie po odświeżeniu, wspólne daty po zastosowaniu zakresu, PL/EN,
resize i widok mobilny. Porównanie skrótów wszystkich kolumn 104 534 transakcji
oraz ustawień gildii/lig przed i po wdrożeniu wykazało brak zmian. SQLite
pozostaje w schemacie 3, a projekcje w wersji quantities-v3. Nie ma migracji
ani potrzeby ponownego importu. Kod i zasoby są serwowane przez istniejący nginx.

Po manualnym odbiorze wymagane jest osobne polecenie rozpoczęcia fazy 6.
