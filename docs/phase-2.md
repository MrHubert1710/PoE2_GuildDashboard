# Faza 2 — wybór ligi i historia transakcji

Status: implementacja zakończona, odbiór manualny oczekujący.
Faza 1 została odebrana na podstawie testów i walidacji. Faza 3 nie jest rozpoczęta.

## Zakres

Domyślny widok aplikacji prezentuje historię wybranej ligi z lokalnej bazy.
Wybór nie wymaga restartu i nie uruchamia fetchowania. Dotychczasowe widoki
audytu, integralności/importu i możliwości źródeł pozostają w Diagnostyce.

- Lista lig z nazwą, zakresem danych, liczbą zdarzeń i stanem kompletności.
- Filtry konta, skrytki, przedmiotu i dat UTC; przycisk Zastosuj filtry.
- Gracz i przedmiot: wyszukiwanie fragmentu, Unicode casefold, literalne %/_.
  Skrytka: dokładny wybór z zakładek obecnych w historii danej ligi.
- Zakres dat obejmuje całe dni UTC, łącznie z dniem końcowym.
- Sortowanie po dacie, graczu, akcji, skrytce i przedmiocie; kierunek asc/desc.
- Paginacja serwerowa 25/50/100, domyślnie 50 rekordów. Każde sortowanie ma
  dodatkowy, jednoznaczny klucz ID wiersza, aby granice stron były stabilne.
- Zdarzenia pokazują opis przedmiotu i akcję źródłową. Nie przeliczają ilości,
  wyceny, przepływów ani stanu skrytki z przyszłych faz.
- Archiwalne HTML otwierane w osobnej karcie, z zachowaniem ich interakcji.

## URL i stan widoku

Stan zapisuje query string: `league`, `account`, `stash`, `item`, `from`, `to`,
`sort`, `direction`, `page`, `page_size`. Domyślne wartości są pomijane.
Przykład: `?league=<id>&item=Chaos&from=2026-10-01&to=2026-10-22`.

Początkowo wybierana jest pierwsza liga z lokalnej listy uporządkowanej po
nazwie. Jej ID zostaje zapisane w adresie. Nie jest na tej podstawie oznaczana
jako aktywna w grze. Nieznane ID w adresie daje jawny stan, a nie podmianę na
inną ligę. Użytkownik może wybrać poprawną ligę.

Zastosowanie filtrów, zmiana strony, sortowania i ligi tworzą wpis historii
przeglądarki. Back/forward i reload odtwarzają wybór. Zmiana ligi czyści filtry
i wraca na stronę 1. Wyczyść filtry zachowuje ligę i rozmiar strony, resetuje
pozostałe parametry do domyślnych. Strona poza zakresem jest korygowana do
ostatniej istniejącej i aktualizuje URL przez replaceState.

Odśwież widok ponawia odczyt metadanych i wierszy z zachowaniem wybranych filtrów.
Nie jest przyciskiem fetchowania gry. Edycja formularza nie wysyła żądań do
kliknięcia Zastosuj filtry. Nawigacja, sortowanie i paginacja korzystają z
ostatnio zastosowanego zestawu filtrów.

Diagnostyka używa `?view=diagnostics`; powrót przez nawigację aplikacji zachowuje
parametry historii. Nie wymaga Vue Router ani osobnego serwera frontendu.

## API odczytu

### GET /api/leagues

Lista lokalnych lig z liczbami, zakresami czasu, skrytkami, rewizją i metadanymi
zarejestrowanych raportów. Brak lig to poprawna pusta lista. API nie wykrywa
jeszcze nowych lig u dostawców ani nie odczytuje plików CSV przy każdym żądaniu.

### GET /api/leagues/<id>/transactions

Parametry filtrów jak w URL, z pominięciem `league`. Opcjonalny `revision`
wiąże odczyt z metadanymi listy lig. Odpowiedź: league_id, revision, page,
page_size, total, pages, sort, direction i rows. Każdy wiersz zawiera tylko
id, external_id, occurred_at, account, action, stash, item, x, y.

Walidacja obejmuje kierunek i listę kolumn sortowania, ograniczenia paginacji,
długość tekstów, format i kolejność dat. Nieznane/zduplikowane parametry są
odrzucane. Filtry używają parametrów SQL; nazwy kolumn pochodzą z allowlisty.
Nie ma dowolnego SQL, wyszukiwania wildcard ani dostępu do raw_json/sekretów.

Odczyt listy i pojedynczej strony działa w transakcji read-only. Token rewizji
łączy tożsamość instancji bazy z rewizjami wejścia ligi. Nowy import lub
odtworzenie bazy może unieważnić token. API zwraca wtedy 409 revision_changed;
UI prosi o odświeżenie bez zerowania filtrów. Nie ma automatycznego pollingu
ani workera z fazy 3. Wymaganie wersji zabezpiecza spójność kolejnych odczytów.

Spóźniona odpowiedź nie może zastąpić danych aktualnej ligi lub filtrów.
Frontend używa AbortController i numeru generacji żądania, a przed przyjęciem
wyniku sprawdza ligę i rewizję. Podczas nowego odczytu stare wiersze są usuwane,
aby nie sugerować, że odpowiadają nowemu kontekstowi.

### GET /archives/<id>

Udostępnia wyłącznie zarejestrowany rekord `archive_files.kind=report`.
Nie przyjmuje ścieżki od klienta. Plik musi pozostać w katalogu danych i mieć
SHA-256 zgodne z rejestrem. Zmieniony plik daje 409, brak/niewłaściwy typ 404.
CSV, baza, cache cen, ustawienia i dowolne pliki `data/` nie są wystawiane.

HTML nie jest wstrzykiwany do Vue. CSP sandbox pozwala na historyczny inline JS
i style, ale nie na same-origin, połączenia sieciowe, formularze i osadzanie
w ramkach. Dzięki temu zakładki, sortowanie i modal wykresu działają, a raport
nie uzyskuje dostępu do API/cookies aplikacji. Link ma noopener/noreferrer.
Raporty zachowują oryginalną treść i wycenę; nie dopisujemy toolbaru odświeżania.

Wszystkie powyższe odpowiedzi mają Cache-Control: no-store. Błąd bazy zwraca
503 bez lokalnych ścieżek. Nieznana liga daje 404, niepoprawne parametry 400.
Poprawne zapytanie bez wyników daje 200 z pustymi rows i total=0.

## Testy i odbiór

Backend: 47 testów Pythona łącznie. Nowe przypadki obejmują izolację lig,
wszystkie filtry, zakresy UTC, stabilność stron, korektę numeru strony,
Unicode/literalne znaki specjalne, walidację i SQL injection, rewizje, puste
bazy/ligi, izolację HTML, brak pliku, checksum mismatch i ścieżkę poza data.

Chromium: 16 scenariuszy łącznie, z 9 dla historii. Używają prawdziwych API
na odrębnej syntetycznej bazie z 60/3 zdarzeniami. Obejmują reload, back/forward,
wyścig spóźnionych odpowiedzi, błędy i retry, brak wyników, mobilny overflow,
bezpieczne wyświetlenie HTML w polu przedmiotu i interaktywny dokument archiwum.
Starsze scenariusze diagnostyczne pozostają uruchamiane z view=diagnostics.

```sh
.venv/bin/python -m unittest discover -s tests -v
npm --prefix frontend run build
npm --prefix frontend run test:browser
```

Sprawdzenie wdrożenia wykorzystuje również rzeczywistą bazę obu lig przez
publiczny prefiks Nginx. Potwierdzono liczby 15 344 / 89 190, filtrowanie Orb,
reload adresu, przełączanie lig oraz zakładki i modal wykresu w prawdziwym
raporcie Forbidden Rites. Dane i schemat z fazy 1 pozostają bez zmian.

Odbiór w przeglądarce:
1. Otwórz http://dyyyl.ovh/poe2guild/ i przełącz obie ligi.
2. Zastosuj gracza, skrytkę, przedmiot i daty. Kliknij nagłówek sortowania,
   zmień stronę/rozmiar strony. Skopiuj adres i sprawdź reload/back/forward.
3. Sprawdź brak wyników dla nieistniejącego przedmiotu i wyczyść filtry.
4. Otwórz currentday/lastday tam, gdzie istnieją, w osobnej karcie.
5. Sprawdź mobilny układ i zakładkę Diagnostyka.

Po zakończeniu fazy praca zatrzymuje się. Faza 3 wymaga osobnego polecenia.
