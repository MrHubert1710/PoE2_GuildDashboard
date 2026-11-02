# Faza 4b — reorganizacja frontendu

Status: implementacja zakończona, oczekuje odbioru manualnego.
Zakres został wybrany przez użytkownika jako osobna faza przed wykresami.
Faza 4 jest odebrana; faza 5 nie została rozpoczęta.

## Układ aplikacji

Domyślny widok to Podsumowanie. Panel gildii ma siedem osobnych sekcji:
Podsumowanie, Gracze, Skrytki, Stan skrytek, Historia, Raporty archiwalne
oraz Ustawienia. Na komputerze nawigacja jest po lewej; na telefonie to
przewijany poziomo pasek nad treścią. Wyświetlana jest jedna sekcja naraz.

Nagłówek zawiera wspólny wybór ligi i języka oraz Panel gildii / Diagnostykę.
Zmiana ligi działa także z Diagnostyki. Nagłówek widoku pokazuje nazwę ligi,
wybrany obszar i liczbę zachowanych zdarzeń. Usunięto etykietę fazy z UI.

W widokach danych jest jeden wspólny formularz filtrów: pola w stylu VS Code,
wielokrotny wybór skrytek, daty UTC i Zastosuj/Wyczyść. Ustawienia i archiwa
nie pokazują tych filtrów, ale zachowują ich kontekst do powrotu.
Podsumowanie ma karty liczby zdarzeń, nieustalonych ruchów i zdarzeń
wywnioskowanych oraz tabelę przepływów według przedmiotu. Nie sumuje jednostek
różnych przedmiotów w jedną liczbę. Pozostałe widoki pokazują właściwą tabelę.
Reguły i niepewności obliczeń fazy 4 pozostają bez zmian.

W głównym panelu odświeżanie zajmuje krótki pasek: stan danych, Pobierz historię
i Stan synchronizacji. Daty, heartbeat workera, próby, ograniczenia, lokalna
weryfikacja i szczegóły dostępności źródła są w Diagnostyce. Błędy odczytu
statusu nadal są sygnalizowane również w głównym panelu. Pobieranie archiwum
pozostaje zablokowane. Wejście/zmiana ligi nadal inicjuje automatyczne sprawdzenie
źródła; przełączanie sekcji nie tworzy kolejnych automatycznych zgłoszeń.

Ustawienia ligi/gildii mają własny widok. Można edytować je, przejść do Historii
lub Diagnostyki i wrócić bez utraty niezapisanego formularza. Jawny zapis nadal
używa kontroli wersji z fazy 4 i zleca przeliczenie lokalne. Edytowany formularz
nie jest automatycznie nadpisywany zmianą ustawień w innej karcie; konflikt
zapisu pozostaje jawny.

Odśwież widok ponawia odczyt metadanych, historii i raportu. Nie zleca przeliczenia
ani pobrania gry. Przelicz dane lokalne pozostaje osobną akcją w widokach analizy.

## Nawigacja i stan

section=summary/players/stashes/state/history/archives/settings wskazuje sekcję.
Brak lub błędna sekcja otwiera Podsumowanie. Starsze linki analysis=players,
analysis=stashes i analysis=state nadal otwierają właściwy widok, jeżeli nie ma
poprawnego section. view=diagnostics pozostaje zgodne ze starymi linkami.

URL zachowuje ligę, język, wszystkie filtry, tryby Aa/ab/regex, powtarzane stash,
page/page_size/sort/direction historii i analysis_page raportu. Zmiana rodzaju
raportu zaczyna jego paginację od pierwszej strony; Back/Forward odtwarza stronę
zapisaną w poprzednim wpisie. Historia i raport mają oddzielne numery stron.
Powrót z Diagnostyki odtwarza ostatnią sekcję panelu. Nowe linki są zwykłymi
adresami, więc można otworzyć je w osobnej karcie.

App utrzymuje jedną instancję kontekstu ligi. Przełączenie sekcji lub Diagnostyki
nie odmontowuje formularzy i nie czyści draftów, wierszy ani rozwiniętych podstaw
obliczeń. Zmiana ligi tworzy nowy kontekst elementów zależnych od ligi, zgodnie
z dotychczasową polityką. Nie współdzieli historii ani stanów przedmiotów lig.

Widoki są ukrywane przez v-show. Lista źródłowych zdarzeń nadal ma najwyżej
25/50/100 wierszy, a raport jest stronicowany. Nie ma pobierania całej historii
do przeglądarki. Pierwszy odczyt kontekstu obejmuje również ograniczoną stronę
historii i ustawienia; sekcje korzystają z tych danych przy przełączaniu.
Diagnostyka globalna jest ładowana dopiero przy pierwszym otwarciu i potem
zachowuje wynik. Polling statusu i wykrywanie rewizji działają w tle.

## Podział kodu

- App.vue — nagłówek, język, trwały obszar panelu i osobna Diagnostyka.
- navigation.ts — reaktywny URL, sekcja, zgodność starych linków i nawigacja.
  Zapis filtrów, paginacji i języka powiadamia ten sam mechanizm.
- HistoryBrowser.vue — właściciel kontekstu ligi i złożenie widoków.
- WorkspaceNavigation.vue — nawigacja sekcji.
- HistoryFilters.vue — wspólny formularz, z TextFilter i StashFilter.
- HistoryTable.vue — źródłowa historia, interpretacje, sortowanie i paginacja.
- QuantityPanel.vue — prezentacja pojedynczego widoku raportu.
- composables/useQuantityReport.ts — odczyt, paginacja, polling obliczeń i retry.
- QuantitySettings.vue — osobny formularz konfiguracji ligi i gildii.
- ArchiveReports.vue — zachowane, izolowane dokumenty HTML.
- RefreshPanel.vue — kompaktowy pasek i szczegóły przeniesione do Diagnostyki.
- composables/useApiRequest.ts — wspólny timeout, anulowanie po opuszczeniu
  kontekstu i stabilne błędy odczytu. Spóźnione odpowiedzi nie zastępują nowej ligi.

Nie dodano Vue Router ani zewnętrznego store: obecne płaskie sekcje używają
jednego mechanizmu query string i lokalnych composables. Nawigacja nie przechowuje
danych biznesowych; te pozostają w kontekście ligi. Układ jest przygotowany do
osadzenia wykresów w widokach danych w osobnej fazie 5.

## Granice fazy

Zmiany dotyczą frontendu, tłumaczeń, testów i dokumentacji. API, algorytm ilościowy,
baza SQLite w schemacie 3, worker, źródłowe dane i zapisane projekcje nie wymagają
migracji. Nie dodano wykresów, wyceny, fetchera GGG ani nowego generatora HTML.
Stary projekt nie został zmodyfikowany. Build Vite jest serwowany przez istniejący
Flask/nginx; zmiana frontendu nie wymaga restartowania usług.

## Walidacja

```sh
npm --prefix frontend run test:locales
npm --prefix frontend run build
npm --prefix frontend run test:browser
.venv/bin/python -m unittest discover -s tests -q
```

Wynik końcowy: 110 testów backendu, 52 testy przeglądarkowe i 16 testów
tłumaczeń zakończone powodzeniem; build TypeScript/Vite poprawny. Kontrola
przez publiczny nginx objęła siedem sekcji, niezapisane formularze, Diagnostykę,
zmianę ligi, PL/EN i szerokość 390 px. Brak błędów JavaScript i poziomego
przepełnienia dokumentu. Sprawdzono rzeczywiste archiwa Forbidden Rites
(15 344 zdarzenia) i Runes of Aldur (89 190 zdarzeń), bez zapisu ustawień.

Regresja obejmuje dotychczasowe filtrowanie, obliczenia, kolejkę, URL, języki,
archiwa i izolację lig. Dotychczasowe testy wchodzą teraz jawnie do właściwego
widoku; nowy workspace.spec.ts sprawdza domyślne Podsumowanie i rozdzielenie
sekcji, drafty filtrów/ustawień, rozwinięte zdarzenia, powrót z Diagnostyki,
zmianę ligi w Diagnostyce, stare linki, Back/Forward, języki, mobile, brak
ponownych automatycznych zgłoszeń oraz odświeżenie raportu bez przebudowy danych.

## Odbiór manualny

1. Otwórz http://dyyyl.ovh/poe2guild/?lang=pl — domyślnie Podsumowanie.
2. Przejdź przez Gracze / Skrytki / Stan skrytek / Historia. Ustaw filtry,
   zmień stronę historii i sprawdź powrót oraz Wstecz/Dalej.
3. Rozwiń podstawę obliczenia zdarzenia, przejdź do innego widoku i wróć.
4. Wpisz niezapisany filtr, odwiedź Ustawienia i Diagnostykę; po powrocie
   formularz powinien zachować treść. To samo dotyczy niezapisanych ustawień.
5. Otwórz Stan synchronizacji, sprawdź lokalną weryfikację i zmień ligę
   w nagłówku. Powrót do Panelu gildii powinien pokazać wybraną ligę.
6. Sprawdź Raporty archiwalne, PL/EN i szerokość mobilną.

Po odbiorze fazy 4b kolejny osobny zakres to faza 5: interaktywne wykresy.


## Poprawki po odbiorze układu — ustawienia skrytek

W Ustawieniach każdy wiersz skrytki łączy checkbox uwzględniania w analizie,
status Uwzględniana/Pomijana i pole Nazwa w analizie. Można bezpośrednio
odznaczyć skrytkę przy włączonym domyślnym „Analizuj wszystkie skrytki”;
pozostałe pozostają zaznaczone. Ta opcja pozwala też ponownie włączyć wszystkie.
Zmiany wymagają jawnego zapisu i przeliczają projekcję, zachowując źródłowe logi.

Zmiana nazwy przenosi wybór analizy na nową nazwę. Checkboxy nadal działają
przy skrytkach pomijanych, a pole nazwy pozostaje edytowalne. Nazwy połączone
wspólnym aliasem mają wspólny wybór, tak jak wspólne odtwarzane współrzędne.
Formularz pokazuje także nazwy skonfigurowane w gildii nieobecne w tej lidze;
zapis nie usuwa ich aliasów. Używa dotychczasowego target_stashes i stash_aliases,
bez migracji schematu lub zmiany API. Zakres zapisu liga/gildia pozostaje dostępny.

Test przeglądarkowy sprawdza wyłączenie, zmianę nazwy pomijanej skrytki,
zachowanie 60 źródłowych zdarzeń, ponowne włączenie i zmianę nazwy aktywnej
skrytki, zapis/reload oraz szerokość mobilną. Końcowa regresja: 54 testy
przeglądarkowe, 113 backendu, 16 tłumaczeń i build zakończone powodzeniem.
