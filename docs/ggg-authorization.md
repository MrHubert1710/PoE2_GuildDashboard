# Autoryzacja GGG — analiza i próby odczytu

Data: 2026-11-03. Projekt: Path of Accounting.

## Najważniejszy wynik

Zapisaną sesją POESESSID można odczytać istniejący endpoint historii PoE2.
Ten sam endpoint rozpoznaje nieprawidłowy Bearer i zwraca OAuth invalid_token.
**Nie potwierdzono ani nie wykluczono dostępu prawidłowym tokenem OAuth.**
W środowisku procesu oraz service.env nie ma konfiguracji własnego klienta,
access tokenu ani refresh tokenu. Sesja WWW nie jest tokenem OAuth.

Nie zmieniono adaptera produkcyjnego ani konfiguracji uwierzytelniania.
Nie wykonywano importu historii podczas prób. Nie rozpoczęto eksperymentów
rekonstrukcji logów przewidzianych w fazie 7C.

## Udokumentowane możliwości

GGG ma wspólny serwer OAuth dla PoE1 i PoE2. O wyborze gry decyduje zasób
i parametr realm, nie osobny grant ani osobny serwer autoryzacji.

| Metoda | Przydatność dla aplikacji | Ograniczenie |
| --- | --- | --- |
| Confidential client, Authorization Code + PKCE | Zgoda właściciela konta, sekret klienta i tokeny na backendzie | Wymaga zarejestrowanej aplikacji i właściwych scopes |
| refresh_token | Odnawia dostęp bez ponownego logowania w okresie ważności | Rotacja; termin ważności refresh tokenu nie przesuwa się |
| client_credentials | Serwerowy dostęp, np. service:leagues; token bez określonego terminu wygaśnięcia | Zakres uprawnień klienta; nie stanowi automatycznie dostępu do prywatnej historii |
| Public client + PKCE | Aplikacje lokalne bez sekretu klienta | Bez service:*; dla tego serwera mniej odpowiedni |
| POESESSID | Działa z obecnym endpointem WWW | Ręczne odnawianie sesji; brak udokumentowanego kontraktu OAuth historii |

Rejestracja nowych aplikacji jest obecnie wstrzymana. Dla skrytek gildii
dokumentacja wymienia specjalny scope account:guild:stashes i oznaczenie
PoE1-only. Opisuje stan skrytek, a nie dziennik dodawania/usuwania przedmiotów.
Katalog lig oraz postacie mają udokumentowaną obsługę PoE2. Nie można
wywnioskować obsługi historii gildii z działania innego zasobu PoE2.

## Wykonane próby

Dowody bez sekretów i danych konta:
[ggg-auth-2026-11-03.json](evidence/ggg-auth-2026-11-03.json).

| Żądanie | Autoryzacja | Wynik |
| --- | --- | --- |
| api.pathofexile.com/league?realm=poe2&limit=1 | brak | 401, kod 8 |
| api.pathofexile.com/character/poe2 | brak | 401, kod 8 |
| api.pathofexile.com/guild/stash/Standard | brak | 401, kod 8 |
| api.pathofexile.com/guild/poe2/stash/Forbidden%20Rites | brak | 404, kod 1 |
| www.pathofexile.com/api/guild/{id}/stash/history | brak | 401, kod 8 |
| ten sam endpoint historii | celowo nieprawidłowy Bearer | 401, invalid_token |
| ten sam endpoint historii | zapisana sesja POESESSID | 200, entries=[], truncated=false |

Próby historii obejmowały tylko ostatnią minutę. Pusta odpowiedź 200
potwierdza przyjęcie żądania; nie weryfikuje pełnej paginacji ani kompletności
historii. Dodatkowe powtórzenie negatywnej próby Bearer potwierdziło komunikat
o nieważnym lub wygasłym access tokenie. Wszystkie odpowiedzi były JSON;
nie zaobserwowano strony wyzwania Cloudflare.

401 bez tokenu nie rozstrzyga istnienia zasobu za bramką autoryzacji.
404 wariantu /guild/poe2/... dowodzi wyniku tej jednej trasy; nie dowodzi braku
wszelkich sposobów dostępu OAuth do danych gildii. invalid_token wskazuje
na walidację Bearer (możliwie we wspólnej warstwie WWW), nie potwierdza
przyznawanych uprawnień do historii.

Żądania były sekwencyjne, ograniczone, bez przekierowań. Zachowano cooldown
z nagłówków w istniejącym magazynie limitów. Sekret wysłano wyłącznie jako
Cookie do dotychczasowego endpointu www.pathofexile.com; nie drukowano go,
nie zapisywano odpowiedzi zawierających dane konta ani nie zmieniano
ustawień, zdrowia połączenia, kursora lub historii. Token kontrolny był
celowo sztuczny; nie wykorzystano poświadczeń innych aplikacji.

## Czego nie dało się przetestować

Nie wykonano rzeczywistego Authorization Code, client_credentials ani
refresh_token: brak własnego klienta i tokenów. Wysyłanie pustych danych do
/oauth/token sprawdziłoby jedynie odrzucenie błędnego żądania.

Przy udostępnieniu własnej konfiguracji OAuth następna próba powinna:

1. Zweryfikować ważny token na udokumentowanym zasobie zgodnym z jego scope.
2. Sprawdzić service:leagues z realm=poe2 niezależnie od dostępu do konta.
3. Porównać odczyt skrytek PoE1 ze specjalnym account:guild:stashes oraz
   wskazany wariant PoE2; nie utożsamiać stanu z historią.
4. Wysłać sam prawidłowy Bearer, bez Cookie, do istniejącego endpointu
   historii PoE2. Dopiero wynik pozwoli ocenić zastąpienie sesji.
5. Jeśli działa: sprawdzić odnowienie na przeznaczonym do próby refresh
   tokenie, zapisując obrócony token atomowo. Rotacja unieważnia poprzedni.

Nie należy automatycznie wymieniać tokenu używanego przez inne procesy.
Nie ma obecnie podstaw do obiecywania trwałego OAuth dla historii. Dla
katalogu lig client_credentials pozostaje udokumentowanym kierunkiem.

## Źródła pierwotne

- [GGG: OAuth, scopes i granty](https://www.pathofexile.com/developer/docs/authorization)
- [GGG: zasoby API, realm i skrytki gildii](https://www.pathofexile.com/developer/docs/reference)
- [GGG: rejestracja aplikacji i dostępne zasoby](https://www.pathofexile.com/developer/docs)
