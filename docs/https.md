# HTTPS na dyyyl.ovh

Logowanie administratora wymaga HTTPS. Konfigurację nginx i certyfikaty zmienia
root; konto aplikacji `nginx-http` nie ma dostępu sudo bez hasła.

Administrator systemu uruchamia interaktywnie:

```sh
sudo apt-get install certbot python3-certbot-nginx
sudo /home/nginx-http/poe2guild/scripts/install-https.sh
```

Skrypt sprawdza nginx, zapisuje kopię `/etc/nginx` w prywatnym katalogu
`/var/backups/poe2guild-https.*`, następnie używa wtyczki nginx Certbota dla
`dyyyl.ovh`, włącza przekierowanie HTTP → HTTPS i sprawdza odnowienie certyfikatu.
Certbot pyta o konto ACME i zgodę na regulamin; te decyzje podejmuje operator.
Porty 80 (weryfikacja i przekierowanie) i 443 muszą być osiągalne z internetu.
Po instalacji sprawdzić również pozostałe usługi domeny oraz harmonogram
odnawiania (`systemctl status certbot.timer` albo harmonogram pakietu).

Nginx musi przekazywać `X-Forwarded-Proto $scheme` do aplikacji. Zmiana trasy
jest częścią fazy 5b. Backend ufa pojedynczemu lokalnemu proxy i pozostaje
przypięty do `127.0.0.1:9002`.

W razie problemów sprawdzić `sudo nginx -t` oraz log Certbota. Certbot wspiera
`sudo certbot --nginx rollback`; kopia konfiguracji pozostaje dodatkowym punktem
odtworzenia. Nie odtwarzać całego archiwum bez sprawdzenia późniejszych zmian.

Źródło: [oficjalna dokumentacja Certbot — nginx i odnawianie](https://eff-certbot.readthedocs.io/en/stable/using.html).
