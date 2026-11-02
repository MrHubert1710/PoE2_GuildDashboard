# Faza 5b — administracja i logowanie

Status: implementacja i wdrożenie zakończone; oczekuje odbioru manualnego.
Pierwszy start tworzy konto `admin` z hasłem `kalandra`, jeżeli konto nie istnieje.
Istniejące konto i jego hasło pozostają bez zmian.

Zakres: lokalna tożsamość administratora, kontrola dostępu do diagnostyki
oraz wspólnej konfiguracji skrytek. Login Admin jest niezależny od konta GGG.

## Dostęp

- Przycisk **Player / Admin** w nagłówku otwiera modal logowania/wylogowania.
- Player ogląda raporty i konfiguruje lokalne preferencje. Nie widzi nawigacji
  Workspace/Diagnostics ani ustawień serwera. Nie może odczytać ich przez API.
- Admin widzi diagnostykę, a w Ustawieniach dodatkową sekcję serwera: aliasy
  i włączanie/wyłączanie skrytek dla ligi lub gildii. Publiczne widoki nadal
  respektują tę konfigurację. Logowanie nie zmienia filtrów URL ani preferencji.
- Wylogowanie odmontowuje komponenty administracyjne i unieważnia sesję na
  serwerze. Odtworzenie poprzedniego cookie nie przywraca dostępu.
- Odczyt historii, autofetch i ręczne pobieranie pozostają publiczne.
  Lokalna weryfikacja danych wymaga administratora. Publiczny polling nie
  udostępnia szczegółów weryfikacji ani statusu procesu workera.

## Domyślne konto, instalacja i zmiana hasła

Konto początkowe: **admin / kalandra**. Jest tworzone przy inicjalizacji
magazynu uwierzytelniania; baza zawiera wyłącznie hash tego hasła oraz flagę
używania hasła domyślnego. Restart ani ponowna instalacja nie nadpisują konta.

Interaktywne `./poe2guild install` po instalacji trasy nginx pyta o nowe hasło
konta admin. Pusty Enter pomija zmianę z komentarzem **not recommended**.
Jeżeli hasło jest już zmienione, instalator pozostawia je bez pytania.
Bez terminala instalacja pomija pytanie i podaje komunikat **not recommended**;
`--dry-run` oraz `uninstall` nie dotykają kont. Konfiguracja hasła działa jako
właściciel katalogu aplikacji, nawet gdy nginx jest konfigurowany przez root.

Jeśli hasło domyślne nadal obowiązuje, wejście na stronę otwiera popup jego
zmiany. Można go zamknąć lub wybrać „Later (not recommended)”; ponowne wejście
przypomni o zmianie. Formularz wymaga obecnego hasła i dwukrotnego podania
nowego (minimum 12 znaków). Zmiana wymaga uwierzytelnienia konta admin,
HTTPS i tokenu CSRF. Po zmianie wszystkie jego sesje są unieważniane,
użytkownik loguje się nowym hasłem, a popup przestaje pojawiać się automatycznie.
Publiczny status udostępnia wyłącznie flagę `default_password`, bez hasha.

## Odzyskiwanie dostępu z terminala

Jako konto aplikacji, bez sudo:

```sh
/home/nginx-http/poe2guild/poe2guild admin
```

Polecenie pyta interaktywnie o nazwę i dwukrotnie o hasło (minimum 12 znaków).
Hasło nie trafia do argumentów procesu, stdout, konfiguracji ani repozytorium.
Powtórzenie dla istniejącej nazwy ustawia nowe hasło i unieważnia wszystkie
sesje tego administratora. Nie ma publicznej rejestracji.

Osobna baza `data/auth/admin.sqlite` zawiera hashe haseł Werkzeug/scrypt,
SHA-256 losowych tokenów sesji, terminy ważności oraz liczniki prób. Plik ma
uprawnienia 0600, nowy katalog 0700. Jest ignorowany przez Git. Kopia historii
lig nie zawiera kont administratorów; kopię auth trzeba wykonywać osobno.

Sesja wygasa po 8 godzinach, przeżywa restart aplikacji i jest odwoływalna.
Cookie: HttpOnly, SameSite=Strict, Secure pod HTTPS, ścieżka `/poe2guild`.
Logowanie wymaga HTTPS. Wyjątek HTTP jest jawnie włączony wyłącznie w
izolowanym serwerze testowym. Aplikacja ufa pojedynczemu lokalnemu nginx;
nie wolno wystawiać jej portu Gunicorna bezpośrednio do internetu.

CSRF: token podwójnego przesłania w cookie i nagłówku `X-CSRF-Token`, kontrola
Origin, rotacja przy logowaniu. Dotyczy login/logout i mutacji administracyjnych.
Odczyty API mają `Cache-Control: no-store`. Po 10 próbach na adres w ciągu
15 minut logowanie zwraca 429; udany login czyści licznik. Limit jest wspólny
dla procesów i przeżywa restart. Odpowiedzi błędu nie rozróżniają nieznanej
nazwy od niepoprawnego hasła. Hasła ani tokeny nie są zapisywane w logach.

## HTTPS

Instrukcja i procedura odnowienia: [https.md](https.md). Nginx przekazuje
`X-Forwarded-Proto $scheme`; instalator tras uzupełnia ten nagłówek również
w istniejącej lokalizacji i obsługuje dodatkowy blok przekierowania Certbota.
Konfiguracja systemowa wymaga root. Administrator potwierdził udaną instalację
trasy oraz `certbot renew --dry-run`.

## Granice

Nie dodano edycji GUILD_ID/SESSION_ID w przeglądarce: adapter oficjalnej
synchronizacji nie jest jeszcze wdrożony. Konfiguracja połączenia i magazyn
tokenów GGG należą do 7B, po potwierdzeniu wspieranego flow. Nie udostępniamy
pozornego formularza sekretów, który nie miałby działającego odbiorcy.
Ta faza nie zmienia danych lig, algorytmu ilościowego ani cen.

## Odbiór manualny

1. Otworzyć stronę przez HTTPS w prywatnym oknie. Status Player, brak
   Workspace/Diagnostics, w Ustawieniach tylko lokalne preferencje.
2. Zmienić domyślne hasło w automatycznym popupie (obecne: `kalandra`),
   następnie kliknąć Player i zalogować się nowym hasłem. Status Admin, pojawiają się
   nawigacja diagnostyki i konfiguracja skrytek w Ustawieniach.
3. Odświeżyć stronę: sesja pozostaje. W drugiej niezalogowanej przeglądarce
   dostęp administracyjny nadal jest zablokowany.
4. Sprawdzić zmianę aliasu/wyłączenie skrytki, tak jak wcześniej, oraz lokalne
   preferencje prezentacji. Zmiany wspólnej konfiguracji dotyczą wszystkich.
5. Wylogować się: znika diagnostyka i ustawienia serwera; bezpośrednie API
   `/api/database-status` i `/api/leagues/<id>/quantity-settings` zwracają 401.

Po zakończeniu fazy zatrzymujemy się do ręcznej weryfikacji. Następna jest 5c,
przed którą trzeba uzgodnić wygląd symulacji stasha.

## Weryfikacja — 2026-11-02

- 158 testów backendu, w tym bootstrap, migracja istniejącego konta, pominięcie
  zmiany przy instalacji, CSRF, unieważnienie sesji i wyścig logowania ze zmianą hasła.
- Bazowa faza: 85 testów Chromium pełnej regresji. Rozszerzenie domyślnego
  konta: 8 testów logowania i lokalnych ustawień; po korekcie szerokości popupu
  ponownie 3 testy logowania, w tym pomiar jego granic na mobilnym ekranie.
- 16 testów katalogów tłumaczeń; build Vue/TypeScript i testy launchera przechodzą.
- Publiczny HTTPS: poprawny certyfikat, `login_available=true`, cookie Secure /
  HttpOnly / SameSite=Strict; prywatne endpointy bez sesji zwracają 401.
- HTTP przekierowuje na HTTPS. `certbot.timer`: enabled i active; operator
  potwierdził bezbłędny `certbot renew --dry-run`.
- Web i worker zrestartowane, health OK. Porównanie przed/po: identyczne
  ustawienia gildii/lig i wszystkie 104 534 transakcje. Stara usługa bez zmian.

Zmianę hasła w GUI sprawdzono na izolowanym serwerze testowym. W produkcji
potwierdzono logowanie admin / kalandra przez HTTPS i wylogowano sesję
weryfikacyjną. Pozostawiono użytkownikowi wybór i zapis nowego hasła.
