# Faza 2a — języki interfejsu

Status: odebrana przez użytkownika poleceniem przejścia do fazy 3.
Faza 2 została odebrana poleceniem przejścia dalej.
Dalszy zakres opisuje [phase-3.md](phase-3.md).

## Rezultat

Historia i Diagnostyka mają tłumaczenia English / Polski, wybierane w nagłówku.
Tłumaczone są także filtry, puste stany, błędy, statusy lig, tooltipy, etykiety
aria, diagnostyka importu i opis ustaleń dotyczących integracji. Te ostatnie są
mapowane po stabilnych ID dostawców, bez zmiany zapisanych wyników audytu.

Kolejność wyboru: obsługiwany `lang` z URL → zapisana preferencja
`localStorage['poe2guild.language']` → obsługiwany język przeglądarki → English.
Dla regionalnego języka przeglądarki można użyć bazowego języka, np. pl-PL → pl.
Nieobsługiwany/usunięty kod przechodzi przez tę samą kolejność fallbacku.
Wybrany kod jest zapisywany w URL i preferencji. Gdy przeglądarka blokuje
localStorage, nadal działają URL, przełączanie i reload.

Przełączanie działa bez przeładowania, zapytań do API i importu. Zachowuje ligę,
zastosowane filtry, niewysłany formularz, sortowanie, stronę, wiersze i otwarte
szczegóły Diagnostyki. Back/forward pomiędzy językami nie odczytuje ponownie
transakcji. Serializer filtrów zachowuje `lang`; API transakcji go nie otrzymuje.
Zmiana parametrów biznesowych nadal odczytuje odpowiednie dane.

Liczby, daty i liczba mnoga korzystają z Intl. Daty nadal pokazują UTC,
a wartości filtrów pozostają YYYY-MM-DD. Aktualizowane są `html.lang` i tytuł
karty. Konta, skrytki, nazwy lig i surowe nazwy przedmiotów pozostają źródłowe.
Zastane HTML pozostają w oryginalnym języku.

## Implementacja i dodawanie tłumaczeń

Niewielka warstwa w `frontend/src/i18n.ts` używa reaktywności Vue i standardowego
Intl, bez dodatkowej zależności. Obsługuje proste parametry i formy liczby mnogiej;
nie jest parserem ICU MessageFormat i nie interpretuje HTML. Wszystkie komunikaty
i parametry są renderowane jako tekst przez Vue. Jeśli przyszły zakres wymaga
złożonej składni lub komponentów wewnątrz tłumaczeń, należy rozszerzyć tę warstwę
lub zastąpić jej wnętrze biblioteką i18n, zachowując API i kontrakt plików.

Jedynym źródłem języków są `frontend/src/locales/*.json`. Vite odkrywa pliki
przez import.meta.glob; kod opcji pochodzi z nazwy, etykieta z nativeName.
Nie ma osobnego rejestru w komponentach ani endpointu języków. Przykład:

```json
{
  "nativeName": "English",
  "messages": {
    "greeting": "Hello {name}",
    "itemCount": {
      "one": "{count} item",
      "other": "{count} items"
    }
  }
}
```

Aby dodać język:

1. Skopiuj en.json jako plik z kanonicznym kodem BCP 47, np. de.json lub pt-BR.json.
2. Ustaw nativeName na nazwę własną języka i przetłumacz wszystkie messages.
3. Zachowaj klucze i nazwy parametrów. Dla liczby mnogiej dobierz formy
   zero/one/two/few/many/other według Intl.PluralRules; other jest obowiązkowe.
   Każda forma musi mieć ten sam zestaw parametrów; parametr count steruje wyborem.
4. Uruchom testy i build. Wdrożony build automatycznie doda opcję przełącznika.

Usunięcie pliku i rebuild usuwa opcję. Samo dopisanie pliku na serwerze nie zmienia
już zbudowanego frontendu. en.json jest obowiązkowy i wyznacza klucze oraz parametry.
Walidator `frontend/scripts/locale-catalog.mjs`, wywoływany przez Vite przed
budowaniem, blokuje niepoprawny JSON, locale, metadane, puste komunikaty,
brakujące/dodatkowe klucze i różne parametry/formy. Runtime ma dodatkowy fallback
brakującej wiadomości do angielskiego; nie zastępuje on walidacji builda.

Nowe funkcje faz 3–8 muszą od razu dodawać komunikaty we wszystkich plikach.
W komponencie używaj `t('key', { count: value })`, a nie sklejanych fragmentów zdań.
Błędy przechowuj jako kody, aby ich treść reagowała na język bez ponawiania żądania.
Przykłady pełnych zdań i polskich form one/few/many/other są w istniejących plikach.

## Walidacja

```sh
export PATH=/home/nginx-http/.local/bin:$PATH
npm --prefix frontend run test:locales
npm --prefix frontend run build
npm --prefix frontend run test:browser
.venv/bin/python -m unittest discover -s tests -q
```

- 16 testów katalogów/formatowania: odkrywanie i dodawanie/usuwanie plików,
  nativeName, błędy schematu, brak lub błędy English, parytet kluczy/parametrów,
  fallback, liczby mnogie i liczby PL/EN.
- 26 testów Chromium, w tym 9 scenariuszy i18n: priorytety wyboru, odmowa storage,
  URL/reload/back/forward, brak dodatkowych żądań, zachowanie kontekstu, tłumaczenie
  błędów i opisów integracji, rozwinięte szczegóły, etykiety dostępności,
  UTC przy innej strefie przeglądarki oraz układ mobilny 360 px dla PL/EN.
- 47 testów backendu. Baza, importer, archiwa i API nie wymagają zmian schematu.

Testy przeglądarkowe korzystają z tymczasowej syntetycznej bazy, bez otwierania
produkcyjnej bazy i bez połączeń z dostawcami. Zrzuty mobilne są w ignorowanym
frontend/test-results/. Lista opcji jest porównywana z rzeczywistymi plikami locale.
Dodatkowy smoke test publicznego adresu przez nginx potwierdził przełączenie
EN/PL, zachowanie ligi i otwartych szczegółów, brak żądań API przy zmianie
języka oraz brak błędów JavaScript. Usługa na porcie 9002 zgłasza health OK.

## Odbiór w przeglądarce

1. Otwórz http://dyyyl.ovh/poe2guild/?lang=en i sprawdź English w nagłówku.
2. Ustaw ligę, filtry i stronę, następnie przełącz na Polski. Kontekst i wyniki
   powinny pozostać, a teksty i daty przełączyć się od razu.
3. Sprawdź reload oraz Wstecz/Dalej po zmianie języka.
4. W Diagnostyce rozwiń szczegóły plików/importu i zmień język; szczegóły pozostają otwarte.
5. Sprawdź szerokość mobilną. Archiwalny raport otwiera się w swoim oryginalnym języku.

Po odbiorze kolejna osobna faza to 3: worker i odświeżanie. Jej rozpoczęcie
wymaga nowego polecenia użytkownika.
