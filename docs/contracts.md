# Kontrakty modułów — faza 0

Definicje typów i Protocol: `backend/contracts.py`. To granice modułów; faza 3 implementuje kolejkę
i worker, pozostałe integracje powstają w następnych fazach. Sam opis capabilities nie jest
potwierdzeniem dostępności źródła. Stan researchu zapisuje
`backend/provider_findings.json` z datą i źródłem informacji.

| Moduł | Odpowiedzialność | Kontrakt |
| --- | --- | --- |
| LeagueCatalog | Metadane i zewnętrzna tożsamość ligi | `list_leagues()` |
| GuildHistorySource | Jedna strona surowych zdarzeń | `fetch_page(scope, cursor)` |
| PriceCatalog | Kategorie i wskazanie formatu feedu | `list_categories(league)` |
| PriceSource | Odpowiedź cenowa lub potwierdzenie braku zmian | `fetch(league, category, etag)` |
| ReportService | Ostatnia poprawna lub wskazana rewizja | `get_report(league_id, revision)` |
| JobQueue | Współdzielenie zadań i wyłączna dzierżawa | `enqueue`, `claim`, `renew`, `complete`, `fail` |
| CredentialStore | Backendowy zapis poświadczeń i rotacja | `get`, `compare_and_swap` |

## Wspólne zasady

- `AdapterCapabilities` opisuje funkcje zaimplementowane i możliwe do użycia;
  domyślna wartość każdej flagi to false. Udokumentowane API nie wystarcza,
  aby włączyć flagę: potrzebny jest adapter i wymagane uprawnienia.
- `CachePolicy` określa minimum między odczytami, conditional requests i
  respektowanie nagłówków. Manual fetch nie obchodzi zasad dostawcy.
- `LeagueReference` zachowuje game/realm i provider ID. Przyszłe wewnętrzne
  ID ligi i mapowanie dostawców należą do repozytorium danych z fazy 1.
- Adaptery nie mutują globalnej aktywnej ligi. Wszystkie daty zdarzeń są aware
  i normalizowane do UTC. Surowe pola pozostają zachowane obok normalizacji.

## Historia

`SyncScope(provider, owner, resource)` wyznacza rzeczywisty zakres zadania.
Przykład: historia jednej gildii, niezależnie od liczby przeglądanych lig.
To również jednostka deduplikacji zadań; limity dostawcy mogą obejmować jeszcze
szerszy zakres, np. całego klienta OAuth.

Kursor jest nieinterpretowanym stringiem adaptera. `HistoryPage.next_cursor=None`
oznacza koniec przebiegu paginacji. Nie dowodzi kompletności historii ligi.
Zakres czasu i zakładka muszą być częścią stanu przebiegu/kursora adaptera.
Nie utrwalać nowego kursora bez zatwierdzenia odpowiadających mu danych.

Tożsamość zdarzenia będzie obejmowała dostawcę, właściciela źródła i ligę.
Audyt obecnych plików nie jest dowodem globalnej unikalności ID w API.
Identyczne ID z różną treścią wymaga zgłoszenia konfliktu lub jawnej polityki
korekt; nie wolno po prostu zachować pierwszego rekordu bez informacji.

## Ceny i raport

`PriceCategory.feed` i `schema_version` kierują do odpowiedniego parsera;
etykieta wyświetlana nie stanowi tożsamości przedmiotu ani kategorii.
`PriceFetchResult.not_modified=True` jest odpowiednikiem conditional 304:
korzystamy z wcześniejszego snapshotu, nie tworzymy pustej listy cen.
Nieznany format, brak kategorii, pusty poprawny feed i awaria są różnymi stanami.

`ReportSnapshot` zawiera identyfikator ligi, rewizję i wersję algorytmu.
Żądanie konkretnej rewizji nie może po cichu zwrócić innej. Brak snapshotu
powoduje jawny stan oczekiwania/braku danych. Wycena w dalszych fazach
identyfikuje również zestaw cen i metodę estymacji.

## Zadania i sekrety

`enqueue` zwraca queued/coalesced/limited/unavailable i istniejące lub nowe ID.
Wybór auto/manual jest wejściem polityki limitów, nie uprawnieniem do obejścia
limitów źródła. Kończenie i odnawianie zadania wymaga aktualnego fencing tokenu.
Stary worker po wygaśnięciu dzierżawy nie może opublikować wyniku.

`StoredCredential` ma osobną rewizję oraz daty ważności access/refresh tokenów.
Tokeny są pominięte w repr i nie są serializowane do API ani logów. Przy rotacji
magazyn przyjmuje zmianę wyłącznie dla oczekiwanej rewizji. Sam CAS nie zastępuje
blokady wokół wywołania odnowienia; inaczej dwa procesy mogłyby użyć tego samego
refresh tokenu. Wygaśnięcie i cofnięcie zgody wymagają ponownej autoryzacji.

## Błędy

Implementacje będą rozróżniały: niedostępność funkcji, brak uprawnień,
wygaśnięcie poświadczeń, cooldown/rate limit, chwilowy błąd sieci,
nieobsługiwany format, konflikt danych i brak wskazanej rewizji.
Adapter nie zwraca pustej historii lub katalogu w zastępstwie błędu.
Publiczny komunikat nie zawiera treści poświadczeń ani surowego requestu.

## Implementacja kolejki w fazie 3

`backend/jobs.py` udostępnia Queue: enqueue(league_id, kind, trigger), claim, renew,
complete(lease, publish) i fail. Fasada rozwiązuje serwerowy zakres źródła oraz
politykę ligi; klient nie podaje ownera. complete publikuje przygotowane dane
i kursor w tej samej transakcji co wynik zadania, pod warunkiem ważnego lease.
`backend/contracts.py:JobQueue` odzwierciedla tę sygnaturę. Szczegóły, polityki
czasowe i API: [phase-3.md](phase-3.md).
