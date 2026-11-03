# Czy dostępność historii dowodzi aktywności ligi?

Sprawdzenie: 2026-11-03. Wynik: **nie potwierdzono takiej równoważności**.
Nie wdrożono automatycznego przełączania active/ended na podstawie samej
dostępności albo braku wpisów historii. To odrębne zagadnienie od analizy
rekonstrukcji przedmiotów w fazie 7C.

## Co potwierdzono

GGG potwierdza migrację postaci i ich przedmiotów z zakończonych lig PoE2
do Standard/Hardcore Early Access. Komunikat o Dawn of the Hunt wskazuje
2025-08-26 jako koniec ligi i opisuje migrację bez wipe'a. Nie mówi o retencji
historii gildii ani o usuwaniu jej w chwili migracji. Samo sformułowanie
o przedmiotach postaci nie stanowi także specyfikacji logów skrytki gildii.

Źródło pierwotne: [GGG na Steam: What Happens When Dawn of the Hunt Leagues End](https://steamcommunity.com/games/2694490/announcements/detail/508463020330975953).
Treść zweryfikowano przez publiczny kanał wiadomości Steam, ponieważ strona
artykułu zwracała pusty szkielet:
[Steam News API, komunikaty GGG sprzed 2025-08-20](https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=2694490&count=5&maxlength=0&enddate=1755648000&feeds=steam_community_announcements).

W publicznym pytaniu o retencję historii gildii odpowiedź pracownika GGG
informuje jedynie o wysłaniu wiadomości prywatnej. Nie podaje okresu retencji
ani zasady usuwania przy końcu ligi. To wątek PoE1; nie stanowi gwarancji PoE2.
[GGG: Guild Stash History Retention Period & Guild Stash API](https://www.pathofexile.com/forum/view-thread/3327311).

## Fakty z bieżącej aplikacji

- Nowo dodane Hardcore ma 10 surowych wpisów pobranych z API GGG, od
  2026-11-03T02:14:54Z do 2026-11-03T02:14:57Z. Potwierdzają operacje w tej
  lidze w tym czasie; nie są odczytem bieżącego statusu ligi.
- Status Hardcore jest unknown, observed_source=local: po dodaniu ligi
  przez Admina aplikacja nie ma obserwacji jej cyklu życia z katalogu GGG.
- Endpoint /api/guild/{id}/stash/history przyjmuje from/end/fromid. Żądanie
  nie wybiera ligi, a odpowiedź zawiera entries/truncated. Nazwa ligi jest
  własnością pojedynczego zdarzenia, nie osobnym statusem odpowiedzi HTTP.
- Wcześniejsza próba minutowego zakresu dała 200 oraz puste entries.
  Nie da się z takiej odpowiedzi wyprowadzić listy aktywnych/zakończonych lig.

Nie znaleziono publicznej specyfikacji GGG, która gwarantuje, że historyczny
wpis przestaje być zwracany po zakończeniu ligi. Nie wykonano obserwacji
tej samej operacji przed i po rzeczywistym zakończeniu ligi. Lokalna kopia
starych logów nie zastępuje takiej próby. Pusta odpowiedź może oznaczać brak
operacji w wybranym zakresie; nie należy z niej wyprowadzać migracji.

## Konsekwencje dla automatyzacji

### Próba pobrania Dawn of the Hunt na polecenie użytkownika

2026-11-03 wykonano trzy sekwencyjne żądania, tym samym zapisanym
POESESSID i dla tej samej skonfigurowanej gildii. Zachowano cooldown.
Nie zmieniano kursora, statusów, ustawień ani danych historii w bazie.

| Zakres UTC | HTTP | Wpisy | truncated |
| --- | --- | --- | --- |
| 2025-04-04 19:00 – 2025-08-26 22:00 (Dawn of the Hunt) | 200 | 0 | false |
| 2026-06-01 – 2026-06-02 (kontrola Runes of Aldur) | 200 | 0 | false |
| 2026-11-03 02:14 – 02:16 (kontrola Hardcore) | 200 | 10 | false |

W lokalnym archiwum są 2442 operacje Runes of Aldur z kontrolnego dnia,
ale API nie zwróciło żadnej operacji z tego zakresu. Runes ma status active
potwierdzony wcześniej przez właściciela. Zatem brak zwracanych starych
operacji nie daje samodzielnego dowodu zakończenia ligi. Możliwa jest m.in.
retencja logów; ta próba nie ustala jej długości ani przyczyny braków.
Nie wykazano również, czy gildia miała operacje podczas Dawn of the Hunt.

Nie udało się uzyskać fragmentu Dawn of the Hunt. Test kontrolny potwierdza,
że sesja i odczyt ostatnich operacji działają. W tej próbie nie wystąpił
błąd autoryzacji ani ucięta odpowiedź wymagająca paginacji.

[Wyniki bez sekretów i danych konta](evidence/ggg-dawn-history-2026-11-03.json).
Surowe odpowiedzi zachowano prywatnie w data/ggg-probes/dawn-2026-11-03/
(pliki 0600, katalog 0700), poza Git. Nie importowano ich do historii.

### Reguły

- Sama obecność dowolnie starej operacji nie nadaje obecnego statusu active.
- Sama nieobecność wpisów, również w udanym fetchu, nie nadaje ended.
- Błąd sesji, limit, awaria albo niepełna paginacja nie zmieniają cyklu życia.
- Istniejący odczyt jawnego statusu/dat z katalogu GGG oraz ręczne ustawienia
  Admina pozostają źródłami statusu; brak tokenu katalogu pozostaje ograniczeniem.
- Pozytywny sygnał świeżej operacji można w przyszłości wykorzystać jako
  osobną obserwację „aktywna w chwili zdarzenia”. Nie powinien udawać
  gwarancji dostępności historycznych logów ani automatycznie kończyć ligi
  po okresie ciszy. Próg świeżości byłby heurystyką, a nie kontraktem GGG.

Do weryfikacji po zakończeniu rzeczywistej ligi: zachować znane ID operacji,
źródłowy czas i dokładny zakres requestu; porównać poprawnie uwierzytelnione,
kompletne odpowiedzi przed i po migracji. Osobno sprawdzić uprawnienia,
retencję oraz wpisy z remove-only tabs w lidze docelowej. Bez takiego dowodu
nie utożsamiać końca ligi z utratą dostępu do logów.
