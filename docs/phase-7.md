# Faza 7A + 7B — katalog lig i pobieranie historii gildii

Status: połączone na polecenie użytkownika; implementacja przygotowana do
odbioru manualnego. Analiza logów na żywo (7C) nie została rozpoczęta.
Data: 2026-11-03.

## Wynik w przeglądarce

System settings zawiera Połączenie GGG oraz Katalog lig. Sekcje i wszystkie
ich endpointy wymagają zalogowania administratora; zapis wymaga CSRF i HTTPS
w produkcji. Publiczne widoki korzystają z danych już dodanych do aplikacji.

Połączenie GGG ma GUILD_ID, maskowane SESSION_ID (wartość POESESSID), włącznik
pobierania oraz możliwość usunięcia zapisanej sesji. Puste pole sesji zachowuje
poprzednią wartość. Po zapisie pole jest czyszczone; odczyty zwracają tylko
informację, czy sekret istnieje. Nie ma przycisku logowania do trade2 ani
importowania cudzych cookies. Strona nie może odczytywać cookies innej domeny.
Wartość trzeba wkleić ręcznie z narzędzi przeglądarki po zalogowaniu do trade2.

Konfiguracja nie potwierdza dostępu: najpierw widnieje status niezweryfikowany.
Fetch history sprawdza rzeczywiste żądanie. Odmowa dostępu zatrzymuje dalszy
autofetch do aktualizacji ustawień. Sesja może wygasnąć i wymaga ręcznej zmiany;
nie jest to automatycznie odnawiany token OAuth. Istniejące konto Admin i jego
hasło pozostają niezależne od sesji GGG.

Przy pierwszym zapisie należy powiązać połączenie z istniejącym archiwum tej
samej gildii. Przy jednym archiwum wybór jest automatyczny, przy wielu jest
widoczny selektor. Powiązanego archiwum nie można przepisać na inny GUILD_ID.
Sekret pozostaje na serwerze w data/auth/providers.sqlite, z uprawnieniami 0600;
pliku nie ma w Git. Kopia całej instalacji powinna obejmować również ten plik
oraz osobne data/auth/admin.sqlite, przechowywane jako sekrety.

## Dodawanie, monitorowanie i status ligi

Automatyczne wykrywanie tworzy kandydatów w katalogu administratora. **Nie
tworzy lig w publicznej aplikacji.** Wyłącznie Admin dodaje wybraną ligę z
katalogu albo wpisuje jej nazwę ręcznie (PoE 2, PC). Ponowienie dodania jest
idempotentne. Mapowanie ID dostawców, game, realm i wariantów jest zachowane.
Nie łączymy lig przez podobne nazwy i nie dziedziczymy stanów przedmiotów.

Monitorowanie steruje pobieraniem historii i cen. Wyłączenie monitorowania
nie usuwa danych ani nie ukrywa archiwum przed odczytem. Niezależnie można
ustawić oznaczenie lokalnego archiwum oraz ręczny status ligi w grze. Zmiana
polityki ma wersję; równoczesny zapis ze starym formularzem daje 409.

Lokalne archiwum nie oznacza końca ligi w grze. Runes of Aldur i Forbidden
Rites zostały potwierdzone przez właściciela jako nadal aktywne. Ich status
zapisano jako obserwację właściciela (observed_source=user, data
potwierdzenia), a nie jako odczyt GGG. Późniejsze potwierdzone dane GGG mogą
go zaktualizować. Ręczne ustawienie administratora ma pierwszeństwo do czasu
ponownego wybrania Automatycznie. Pole ze statusem ze źródła pokazuje też
pochodzenie i datę, aby nie przypisywać tej wiedzy niewykonanemu żądaniu GGG.

Katalog poe.ninja wskazuje dostępność ekonomii. Nie stanowi dowodu aktywności
ani zakończenia ligi w grze. Brak na liście cen, błąd sieci i pusty/błędny
katalog nie archiwizują żadnej ligi i nie kasują wcześniejszej wiedzy.

Opcjonalny adapter oficjalnego katalogu używa GET /league z realm=poe2,
paginacją oraz service:leagues. Odczytuje main/event i sprawdza znane ligi
nieobecne na liście przez endpoint szczegółów. Jawne daty końca oraz status
bieżącej ligi stanowią dowód; sama nieobecność nie oznacza zakończenia.
Konfiguracja serwera: POA_GGG_LEAGUES_TOKEN, POA_GGG_CLIENT_ID i POA_GGG_CONTACT.
Sekrety nie są przekazywane do Vue. Przy braku konfiguracji nie wykonujemy
żądań bez autoryzacji. POESESSID nie zastępuje tokenu tego katalogu.

Dokumentacja sprawdzona 2026-11-03:
[GGG — katalog lig](https://www.pathofexile.com/developer/docs/reference#leagues),
[GGG — rejestracja i autoryzacja](https://www.pathofexile.com/developer/docs),
[poe.ninja — katalog ekonomii](https://poe.ninja/docs/api).
Oficjalny dostęp do historii gildii PoE 2 nie jest tu deklarowany.

## Jak pobierana jest historia

Na wyraźne polecenie użytkownika przeniesiono sesyjny adapter z poprzedniej
aplikacji. Korzysta z tego samego adresu strony GGG:
https://www.pathofexile.com/api/guild/<guild_id>/stash/history
z parametrami from/end i fromid oraz nagłówkiem Cookie: POESESSID. Nie jest to
udokumentowany endpoint OAuth. Weryfikacja prawdziwej sesji i aktualnego formatu
odpowiedzi należy do odbioru manualnego; testy izolowane nie zastępują tej próby.

- Jedno źródło/kolejka dla całej gildii, wspólne dla wszystkich lig i klientów.
- Pierwszy fetch pobiera całą dostępną historię: od teraz wstecz, do end=0.
  Duplikaty istniejących archiwów nie są dodawane drugi raz.
- Następne przebiegi obejmują okres od teraz do poprzedniego punktu kontroli
  z sześciogodzinnym zakładem. Paginacja korzysta z ostatniego czasu i ID.
- Kursor zatwierdzamy razem z importem i surowymi odpowiedziami, dopiero po
  poprawnym zakończeniu stron. Błąd, konflikt, zmiana konfiguracji lub utrata
  lease nie mogą przesunąć kursora ani częściowo podmienić historii.
- Zakładamy odpowiednią semantykę from/end zgodną ze starym fetcherem. Bardzo
  opóźnione wpisy oraz nietypowe odpowiedzi wymagają eksperymentów w 7C.
- Każda liga jest odrębna. Nowe wpisy trafiają do właściwej dodanej,
  monitorowanej ligi. Nieznane lub niemonitorowane ligi pozostają oczekujące.
  Ich surowe wpisy są przechowywane, a Admin może później dodać ligę.
- Po imporcie zmienionych lig worker odtwarza ich ilości i wyceny. Ceny
  zachowują dotychczasową politykę: historia 24 h, obserwacje 1 h, ETag.

Autofetch historii po otwarciu strony i przycisk Fetch history pozostają.
Automatyczne próby: najwyżej 2/h dla źródła, świeżość 30 min. Ręczna próba
współdzieli kolejkę i cooldown. Kolejne strony respektują Retry-After oraz
X-Rate-Limit; stan oczekiwania jest zapisany poza procesem. Przekierowania
żądań z sekretami są blokowane. Nie ma automatyzacji logowania do GGG.

Bezpieczniki pojedynczego przebiegu: 200 stron, 16 MiB odpowiedzi na stronę,
30 s timeout żądania; powtórzony kursor lub błędny format przerywa import.
Osiągnięcie limitu nie jest uznawane za pełną historię. Pusta odpowiedź również
nie dowodzi kompletności: history_complete nie jest automatycznie potwierdzane.
Statusy postępu i błędy są widoczne w połączeniu GGG i diagnostyce.

## Przechowywanie i odtwarzanie

Schemat 11 (migracje 010–011):

- league_catalog_entries: kandydaci, warianty, ID, obserwacje i obecność w źródle;
- catalog_observations: payloady katalogu oraz dowody statusu;
- league_catalog_sources / league_catalog_http_cache: trwały stan źródeł i cache;
- league_policies: ręczny status i wersja konfiguracji;
- leagues: monitorowanie oraz status obserwowany, jego źródło i data;
- guild_history_pages: oryginalne odpowiedzi JSON z SHA-256 i parametrami stron;
- guild_history_events: oryginalny wpis API i jego reprezentacja zgodna z
  dotychczasowym importerem, z odnośnikiem do transakcji lub stanem oczekującym;
- source_cursors: punkt kontroli całego źródła historii gildii.

transactions.raw_json nadal przechowuje zgodny z dotychczasową walidacją
zestaw pól CSV. Pełne, oryginalne pola API są w guild_history_events.raw_json
oraz guild_history_pages.payload_json. Nie modyfikujemy historycznych rekordów
w razie konfliktu. Różne zapisane formaty separatora ilości mogą być uznane za
ten sam wpis tylko przy zgodności czasu, konta, akcji, skrytki, pozycji i ilości.

Offline rebuild zachowuje pobrane transakcje, surowe strony/wpisy, pozycje
oczekujące, kursor, katalog, polityki oraz ligi dodane przez Admina. Remapuje
odnośniki do transakcji odtworzonych z CSV, bez zmiany tożsamości gildii.
Nieodtwarzalny konflikt lub zmiana ID źródła zatrzymuje przebudowę zamiast
odrzucać dane. Projekcje ilościowe/wyceny nadal są danymi pochodnymi.

Katalog odświeża wspólny worker: sprawdza potrzebę raz na minutę, z minimalnym
odstępem 1 h między zadaniami. To osobny harmonogram katalogu; nie zmienia
polityki wyzwalania pobierania cen. POA_CATALOG_ENABLED=0 wyłącza to zadanie.
W testach nie ma żadnego ruchu do zewnętrznych źródeł.

## Weryfikacja techniczna

- 210 testów backendu: zaliczone. Po końcowych zmianach ponownie zaliczono
  49 testów kolejki, połączenia, katalogu i autoryzacji.
- 95 scenariuszy Chromium: zaliczone po korekcie istniejącego tekstu limitów
  (94 zaliczone w pełnym przebiegu, poprawiony scenariusz i nowe panele
  ponownie sprawdzone w zestawie 8 testów).
- 16 testów tłumaczeń, kontrola typów oraz build produkcyjny: zaliczone.
- Pokryte: paginacja, raw JSON, duplikaty archiwów, konflikty, brak częściowego
  importu i przesunięcia kursora, odnowienie konfiguracji podczas fetchu,
  401/403, Retry-After, oczekujące ligi, Admin/CSRF oraz offline rebuild.
- Testy sesji korzystają z canary i atrap odpowiedzi, bez żądań GGG na realnym
  koncie. Prawdziwe połączenie jest świadomie pozostawione do odbioru w GUI.
- Dodatkowy import offline wszystkich 104 534 istniejących wpisów, w 21
  stronach na kopii bazy: 4,53 s, zero nowych transakcji, 104 534 duplikaty;
  zachowano surowe odpowiedzi. Test nie wykonywał żądań zewnętrznych.
- Wdrożono schemat 11 i zrestartowano web/worker. Katalog poe.ninja zawiera
  sześciu kandydatów, publiczna lista nadal dwie ligi. GGG poprawnie zgłasza
  brak tokenu katalogu; sesja historii pozostaje nieskonfigurowana.
- Po migracji SHA-256 transakcji, istniejących cen oraz historycznych wycen
  są identyczne z wartościami sprzed wdrożenia. Ustawienia lig i gildii
  zachowane. SQLite quick_check: ok; zero naruszeń foreign keys. Anonimowe
  odczyty obu nowych paneli API dają 401; publiczna strona HTTPS działa.

## Odbiór manualny i granica fazy

1. Zalogować Admina, otworzyć System settings i zapisać poprawne GUILD_ID oraz
   SESSION_ID. Hasła ani sesji nie wklejać do rozmowy.
2. Włączyć pobieranie. Sprawdzić brak zwracanej wartości SESSION_ID po reloadzie.
3. Użyć Fetch history w nagłówku. Obserwować stan, strony i ewentualną odmowę
   dostępu. Pierwszy przebieg może pobrać wiele stron.
4. Porównać nowe wpisy i ligi; ponowienie nie może podwajać operacji. Nieznane
   ligi mają pozostać oczekujące, dopóki Admin nie doda ich do aplikacji.
5. W katalogu sprawdzić kandydatów, dodanie ligi, monitorowanie i ręczny status.
   Tryb Automatycznie wykorzystuje źródło statusu, nie obecność na liście cen.
6. Sprawdzić, że niezalogowany klient nie widzi konfiguracji i nie może jej
   odczytać ani zmieniać przez bezpośrednie API.

Po odbiorze zatrzymujemy się. Następne 7C wymaga osobnego polecenia i uzgodnienia
kontrolowanych operacji w grze. Symulacja stasha pozostaje opcjonalną fazą 9,
po rozwiązaniu problemów interpretacji logów.
