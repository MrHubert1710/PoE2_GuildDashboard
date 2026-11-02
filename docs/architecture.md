# Wymagania reworku i decyzje architektoniczne

Stan ustaleń: 2026-11-02. Funkcje poniżej są planem, nie opisem działania
obecnego Hello World. Weryfikować możliwości dostawców przed implementacją
integracji, ponieważ ich dokumentacja i zakres dostępu mogą się zmieniać.

## Zakres zaakceptowany do uwzględnienia w projekcie

1. Automatyczne odświeżanie wyzwalane wejściem na stronę i przycisk ręczny.
2. Interaktywne wykresy: tooltip, zoom, przesuwanie czasu, wybór serii i filtrów.
3. Wybór ligi z listy, bez restartowania aplikacji.
4. Preferowanie oficjalnego uwierzytelniania GGG, z odnowieniem tokenów,
   jeżeli wymagane zasoby i rejestracja klienta są dostępne.
5. Wykrywanie lig i ich cyklu życia; zachowywanie lokalnych archiwów.
6. Wykrywanie kategorii wyceny i zmian struktury odpowiedzi dostawcy.
7. Wiele tłumaczeń interfejsu i wybór języka niezależny od wybranej ligi.

## Rozdzielenie odpowiedzialności

- API odczytuje ostatnią poprawną rewizję danych i nie wykonuje pracy sieciowej
  w żądaniu odczytu raportu. Interfejs osobno zgłasza potrzebę aktualizacji.
- Trwała kolejka SQLite i dedykowany proces roboczy wykonują zadania poza
  procesami Gunicorna. Blokady, lease i deduplikacja obejmują wszystkie procesy.
  Na początek jeden worker; bez obowiązkowego Redis/Celery.
- Adaptery źródeł: historia gildii, metadane lig, katalog kategorii i ceny.
  Każdy deklaruje dostępne możliwości, stan autoryzacji i świeżość danych.
- Osobno normalizacja transakcji, obliczenia ilościowe, wycena i eksport HTML.
- Vue zarządza stanem widoku, a nie poświadczeniami dostawców.

## Odświeżanie

Wejście na stronę pokazuje zapisane dane i zgłasza sprawdzenie aktualizacji
wybranej ligi. Domyślna dotychczasowa polityka: do 2 automatycznych prób/h;
ręczna próba pomija ten limit, ale nie limity dostawcy ani trwające zadanie.
Wiele kart/klientów współdzieli jedno zadanie. Historyczna liga domyślnie nie
pobiera historii ani cen. Backend egzekwuje to niezależnie od przycisków UI.

Pobieranie historii może obejmować całą gildię, więc zakres deduplikacji zadań
wynika z adaptera i konta/gildii, nie zawsze tylko z wybranej ligi.
Pobrane transakcje są rozdzielane do właściwych lig. Obowiązują wspólne limity
źródła. Synchronizacja cen i katalogów ma odrębne terminy świeżości.

UI otrzymuje status zadania i rewizję danych, na początku przez polling.
Aktualizacja nie przeładowuje strony: odświeża odpowiednie dane i zachowuje
ligę, gracza/skrytkę, filtry, sortowanie i zakres czasu. Błąd zachowuje
ostatnią poprawną rewizję i pokazuje komunikat bez sekretów dostawcy.

## Model danych

- Liga: wewnętrzny identyfikator, game/realm, identyfikatory dostawców, nazwa,
  wariant/ruleset, daty i metadane cyklu życia wraz ze źródłem i czasem odczytu.
- Oddzielne pola: status ligi, lokalna polityka archiwizacji, możliwość pobrania
  historii, dostępność cen, stan poświadczeń i znana kompletność lokalnej historii.
- Oddzielna decyzja o tym, które ligi gildia monitoruje. Wykrycie ligi nie
  uruchamia automatycznie pełnego importu wszystkich wariantów.
- Transakcja: liga i gildia/źródło, zewnętrzne ID, data UTC, oryginalna treść,
  znormalizowane pola, identyfikator importu. Deduplikacja w zakresie źródła,
  gildii i ligi. Walidacja rzeczywistego zakresu unikalności ID przed schematem.
- Snapshot ceny: liga ekonomiczna dostawcy, rodzaj feedu, kategoria, przedmiot,
  waluta bazowa, czas pobrania, czas danych jeśli dostępny, rewizja formatu.
- Wycena: identyfikator zestawu cen i wersja algorytmu. Aktualna cena, cena
  historyczna i estymacja są różnymi informacjami. Brak ceny nie oznacza zera.
- Zadania synchronizacji, ich zakres, próby, lease, kursory i błędy.
- Surowe archiwa pozostają odtwarzalnym wejściem; SQLite jest budowane z danych
  starego projektu bez przełączania branchy. Baza i poświadczenia poza Git.

## Wykresy i adresy

Wstępny kandydat: Apache ECharts. Dane wykresów udostępnia API jako szeregi
czasowe niezależne od biblioteki. Zakres i rozdzielczość są parametrami zapytań;
backend agreguje duże historie. Interakcja może sterować filtrem tabeli.
Wybór ligi i filtry w URL, pamięć widoków rozdzielona między ligi.
Eksport `currentday.html`/`lastday.html` pozostaje osobną funkcją i może używać
statycznych wykresów; nie jest źródłem danych interaktywnej aplikacji.

## Język i lokalizacja

Planowana osobna faza 2a wprowadzi PL/EN i rozszerzalne katalogi tłumaczeń.
Angielski (en) jest językiem domyślnym, bazą słowników oraz fallbackiem
brakujących tłumaczeń. en.json musi być obecny i poprawny; walidacja innych
języków porównuje ich klucze i parametry z angielskim słownikiem.
Lista języków wynika z plików `frontend/src/locales/*.json`, bez dodatkowego
rejestru w kodzie. Nazwa pliku określa kod locale, metadane nativeName — nazwę
opcji, a messages — tłumaczenia. Build odkrywa i waliduje pliki. Nowy język
staje się dostępny po przebudowaniu i wdrożeniu; usunięcie pliku usuwa opcję
i wymaga fallbacku dla wcześniejszych preferencji/URL. Nie ma runtime skanowania
katalogu serwera przez statyczny frontend.
Język interfejsu jest preferencją użytkownika/przeglądarki i elementem URL,
nie właściwością ligi ani zdarzenia. Nie duplikować transakcji ani wyceny
w bazie dla poszczególnych języków.

API zwraca stabilne kody i wartości źródłowe; etykiety i komunikaty tłumaczy UI.
Nazwy źródłowe przedmiotów i lig nie mogą stać się kluczami tłumaczeń ani
zależeć od wyboru języka. Ewentualne lokalizowane nazwy dostawców mapować po ID.
Nazw użytkowników i skrytek oraz surowych zdarzeń nie tłumaczyć.

Daty/liczby/liczebniki formatować według locale; UTC w API i semantyka filtrów
pozostają stałe. Locale i strefa czasu to odrębne ustawienia. Przełączenie języka
zachowuje filtry, ligę, stronę i stan widoku. Serializer query string nie może
usuwać lang podczas nawigacji lub zastosowania filtrów.

Wszystkie kolejne fazy korzystają z tych samych katalogów, również teksty
wykresów, statusów synchronizacji i nowo generowanych eksportów HTML.
Zastane raporty historyczne pozostają w oryginalnym języku.

## GGG: zweryfikowane możliwości i ograniczenia

- GGG dokumentuje OAuth 2.1. Dla aplikacji serwerowej preferowany confidential
  client, HTTPS callback i sekrety przechowywane wyłącznie na backendzie.
- Odnowienie access tokenu nie przedłuża ważności refresh tokenu. Jego wymiana
  rotuje token i unieważnia poprzedni, więc wymaga synchronizacji workerów.
- Tokeny client_credentials nie mają ustalonego terminu wygaśnięcia, ale
  działają tylko dla przyznanych zasobów; nie zastępują automatycznie sesji WWW.
- Publiczna referencja opisuje Guild Stashes jako PoE1-only i nie dokumentuje
  historii transakcji gildii PoE2. Nie zakładać, że stary endpoint obsłuży Bearer.
- Rejestracja nowych aplikacji jest obecnie wstrzymana. Dostęp do zasobów
  historii należy potwierdzić z GGG przed wdrażaniem oficjalnego fetchera.
- Metadane lig: `GET /league?realm=poe2`, scope `service:leagues`.

Źródła:
- https://www.pathofexile.com/developer/docs
- https://www.pathofexile.com/developer/docs/authorization
- https://www.pathofexile.com/developer/docs/reference

## Wykrywanie lig i kategorii

Łączyć lokalny rejestr archiwów z metadanymi GGG, gdy dostępne, oraz listą
aktywnych lig ekonomicznych poe.ninja. Są to różne katalogi i różne możliwości.
Brak ligi na liście cen nie dowodzi zakończenia ligi ani braku historii gildii.
Błąd sieci nie zmienia ligi w archiwalną; brak w odpowiedzi nie usuwa jej z bazy.
Zachować stan nieznany, źródła ustaleń i możliwość ręcznej korekty.

poe.ninja publikuje `GET /poe2/api/economy/leagues`. Dokumentacja wymienia
kategorie i odrębne feedy exchange/stash item; nie opisuje endpointu katalogu
kategorii. Nie obiecywać niezawodnego pełnego autodiscovery na tej podstawie.
Przy implementacji najpierw sprawdzić, czy pojawił się wspierany katalog.
W przeciwnym razie: adapter odczytujący opublikowaną listę kategorii z walidacją,
wersjonowany ostatni poprawny katalog i raportowanie zmian/błędów odkrywania.
Nie skanować losowych nazw endpointów ani korzystać z API builds/profiles.

Katalog kategorii: ID dostawcy, etykieta, rodzaj feedu, parser, daty obserwacji
i dostępność per liga. Nie wiązać UI z nazwami kategorii dostawcy. Przedmioty
i ich identyfikatory mogą zmieniać przypisanie; nie łączyć ich wyłącznie po
etykiecie kategorii. Zmiana formatu wymaga adaptera, nie tylko nowej nazwy.
Nie usuwać starych cen ani historii kategorii po ich zniknięciu z katalogu.
Cache, ETag i harmonogramy są wspólne dla użytkowników; awaria katalogu
zachowuje ostatni poprawny zestaw. Ręczny fetch nie obchodzi cache dostawcy.

Źródła:
- https://poe.ninja/docs/api
- https://echarts.apache.org/handbook/en/concepts/event/

## Kolejność portowania

Szczegółowa kolejność, zależności i kryteria odbioru są utrzymywane w
[implementation-plan.md](implementation-plan.md). Worker i kontrakt
odświeżania powstają przed integracją GGG i są testowane na adapterze lokalnym;
ich wdrożenie nie wymaga dostępu do zewnętrznego źródła historii.

Nie uzależniać implementacji odczytu archiwów od uzyskania dostępu OAuth.
