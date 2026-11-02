# Faza 5a — preferencje lokalne i wspólny stan URL

Status: zaimplementowana; oczekuje odbioru manualnego. Fazy 5b i dalsze nie
zostały rozpoczęte.

## Zasada rozdzielenia

Każdy klient ma własny język, strefę czasu, format 12/24 h, kolory, domyślny
widok oraz stan zwinięcia paneli. Ustawienia są w sekcji „Twoje preferencje”.
Zmiana prezentacji nie wykonuje PUT ustawień ligi ani POST przeliczenia ilości.

Filtry i liga pochodzą wyłącznie z URL. Nie zapisujemy ich w localStorage,
nie zapamiętujemy ostatniej ligi i nie nakładamy ukrytych filtrów na link.
Współdzielony URL wskazuje te same rekordy niezależnie od preferencji klienta.

Granice czasu w URL mają format `2026-01-01T12:00:00.000Z` (ISO 8601 UTC).
`from` jest włączny, `to` wyłączny. Wykres synchronizuje dokładne instancje czasu
z tymi filtrami. Daty w formularzu są lokalnym edytorem ich granic; nie tracimy
precyzji, jeśli użytkownik zmienia tylko gracza lub przedmiot. Samo przełączenie
strefy czasu nie zmienia URL ani zakresu danych. Legacy URL z samym dniem jest
normalizowany do UTC: from na początek dnia, to na początek następnego dnia.

Przykład: lokalny dzień 2026-03-29 w Europe/Warsaw daje zakres
2026-03-28T23:00:00.000Z do 2026-03-29T22:00:00.000Z, czyli 23 godziny.

## Przechowywanie i migracja

Magazyn `path-of-accounting.preferences.v1` ma wersję 1 i zawiera tylko
language, timezone, hourFormat, defaultView, colors i panels. Nie zawiera
filtrów, ligi, sekretów ani konfiguracji źródła.

Pierwsze uruchomienie przejmuje wcześniejszy język i kolory z kluczy
poe2guild.language / poe2guild.chart-colors.v1. Dotychczasowe ustawienia
wyświetlania ligi są jednorazowym punktem startowym; potem klient wybiera
własne wartości. Nie przepisujemy starych konfiguracji na serwerze.
Bez wybranego lub zachowanego języka domyślny jest angielski.

Nieprawidłowy JSON i nieznane wartości są walidowane i zastępowane domyślnymi.
Gdy localStorage jest faktycznie zablokowany, interfejs pokazuje status i działa
w pamięci karty. URL nadal pozwala odtworzyć filtry. Zwinięcie panelu jest
zapisywane bezpośrednio przy kliknięciu; można od razu przeładować stronę.

## Zakres serwera i API

Aliasy oraz ignorowane zakładki nadal są wspólne dla wszystkich. Są pokazane
osobno jako „Ustawienia skrytek serwera”; faza 5b przeniesie je do administracji.
Dotychczasowe serwerowe timezone/hour_format są zachowane dla zgodności starej
konfiguracji, ale edycja lokalnych preferencji ich nie zmienia.

Odczyty transactions, quantities i quantity-series przyjmują timezone jako
parametr prezentacji odpowiedzi. Dla timestampów UTC nie wpływa on na granice
zapytań. Projekcje nadal identyfikuje serwerowy hash i wersja quantities-v3.
Nie ma migracji bazy ani zmiany surowych danych.

## Dodatkowe zmiany interfejsu

- Nagłówek i filtry są poza obszarem przewijania. Układ zajmuje wysokość
  okna, a przewija się wyłącznie zawartość zakładki pod filtrami. Nie przechodzi
  ona pod rozwinięty pasek. Dotyczy to desktopu i telefonu.
- Filtry zwijają się do kompaktowego przycisku po prawej stronie. Stan jest
  lokalny; zwijanie nie zmienia URL ani wyników. W ustawieniach/archiwach
  filtry są ukryte. Widok diagnostyki ma osobny obszar przewijania.
- Popup kolorów zawiera koło barw, nasycenie, jasność i pole HEX. Wszystkie
  kontrolki aktualizują linię, tooltip i miniatury; mają obsługę klawiatury.

## Walidacja i odbiór

142 testy backendu, 81 przeglądarkowych i 16 tłumaczeń przeszły. Build
TypeScript/Vite jest poprawny. Testy potwierdzają:

- identyczne rekordy i granice UTC w dwóch niezależnych klientach mimo różnych
  stref i formatów zegara, bez zapisu konfiguracji ani nowej projekcji;
- lokalne preferencje, migrację kolorów, obsługę błędnego/zablokowanego storage,
  brak zapisu filtrów i ostatniej ligi oraz zachowanie precyzji przy zmianie gracza;
- poprawną konwersję lokalnego dnia przy zmianie czasu letniego, reload i URL;
- koło barw, nasycenie, jasność, pole HEX i zachowanie koloru po reloadzie;
- nieruchomy nagłówek i filtry, osobny obszar scrollowania pod nimi oraz
  zwijanie do prawej krawędzi na szerokościach 1280, 1000 i 390 px;
- zgodność wcześniejszych wykresów, tabel, aliasów, wyłączeń i synchronizacji.

Testy gestów czekają na powrót zarówno pozycji, jak i szerokości zaznaczenia
miniatury. Zapobiega to rozpoczęciu kolejnego automatycznego gestu w środku
animacji powrotnej i fałszywemu wynikowi testu.

Publiczny nginx sprawdzono w dwóch niezależnych profilach Chromium: wspólny
URL UTC daje te same identyfikatory rekordów, a formaty dat są różne.
Zweryfikowano zwijanie, przewijanie tylko treści, koło barw i mobile bez błędów
JavaScript. Hash wszystkich źródłowych transakcji oraz konfiguracje lig/gildii
pozostały identyczne przed i po weryfikacji.

Do odbioru ręcznego: preferencje na dwóch przeglądarkach, ten sam link UTC,
zwijanie filtrów po prawej i scroll treści pod nimi, picker kolorów. Po odbiorze
następna jest faza 5b — administracja i logowanie. Nie została rozpoczęta.
