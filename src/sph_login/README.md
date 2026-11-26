# sph-login

Eigenständig installierbares Python-Paket für Schulportal-Hessen-Anmeldungen.
Es stellt eine HTTP-Sitzung und einen optionalen Browser-Adapter bereit. Aufgaben
(Kalender, Nachrichten, Moodle usw.) bleiben beim aufrufenden Projekt.
Python >= 3.11; nur `httpx` ist erforderlich.

## Installation als Abhängigkeit

Aus diesem Checkout:

```sh
pip install /pfad/material-datenbank/src/sph_login
```

Aus Git, z. B. in einer requirements.txt (für reproduzierbare Builds einen Commit
statt `main` einsetzen):

```text
sph-login @ git+<Repository-URL>@<Commit>#subdirectory=src/sph_login
```

Das Paket ist nicht auf PyPI veröffentlicht. Das Hauptprojekt deklariert
`sph-login` als Abhängigkeit und bündelt dessen Dateien nicht. Im Checkout beide
Pakete zusammen installieren, damit pip die lokale Abhängigkeit auflösen kann:

```sh
pip install -e src/sph_login -e '.[dev]'
```

`inv setup` führt diese gemeinsame Installation ebenfalls aus. Andere Projekte
benötigen ausschließlich `sph-login`; die Material-Datenbank ist dafür nicht nötig.

## Eine Anmeldung, mehrere Aufgaben

```python
import os
from pathlib import Path
from sph_login import Credentials, SphSession

credentials = Credentials(os.environ["SPH_SCHOOL_ID"], os.environ["SPH_USERNAME"],
                          os.environ["SPH_PASSWORD"])
with SphSession(credentials, state_path=Path.home() / ".cache/my-project/sph.json") as sph:
    sph.login()  # bereitet SSO-Cookies vor, ggf. aus dem Cache
    sph.connect_lanis()  # optionaler LANiS-Adapter; prüft den LANiS-Zugriff
    response = sph.client.get("https://start.schulportal.hessen.de/startseite.php?a=ajax&f=apps")
    response.raise_for_status()
    # Weitere projektspezifische Aufgaben über denselben Client.
    sent = sph.keepalive()  # optional; frühestens alle 60 s
    # True = Anfrage gesendet; kein Beleg für eine verlängerte Sitzung.
```

`login()` öffnet keine LANiS-Sitzung. Ein vorhandener SSO-Cookie ist nur ein
Anmeldekandidat: Die jeweilige Zielanwendung muss den Loginstatus bestätigen.
Auch Cache-Kandidaten werden dort geprüft; es gibt keinen impliziten LANiS-Test.
`connect_lanis()` ist nur für LANiS-Aufgaben nötig und verwirft bei einem fehlenden
LANiS-`sid` die SSO-Cookies nicht.

Keine globalen Clients, keine Hintergrundthreads und keine automatischen
Wiederholungen von Aufgaben. Nach Ablauf entscheidet der Aufrufer, ob er
`login(force=True)` ausführt und welche Aufgabe gefahrlos wiederholbar ist.
`close()` schließt nur lokale Verbindungen; es meldet nicht alle Geräte ab.

## Browser und Moodle

```python
with SphSession(credentials) as sph:
    sph.login()
    sph.install_in_browser(page.context)  # bestehender Playwright-Kontext
page.goto("https://mo1234.schulportal.hessen.de/course/view.php?id=42")
# Zielanwendung beendet ihren SSO-Ablauf; anschließend ihren Loginstatus prüfen.
```

Playwright ist für reine HTTP-Aufgaben nicht nötig. Der Adapter erhält Domain,
Pfad, Secure, HttpOnly, SameSite und Ablauf der Cookies. Ein LANiS-`sid` ersetzt
keine Moodle-Sitzung. Keepalive betrifft LANiS, nicht Moodle.

Course-Sync verwendet standardmäßig diesen HTTP-Weg, sobald der Moodle-Login zum
Schulportal führt. `COURSE_SYNC_SPH_LOGIN_METHOD=browser` wählt die bisherige
Formularanmeldung. Wenn Moodle einen vorbereiteten SSO-Cookie ablehnt, wird
vor Beginn der Aufgaben einmal mit Passwort erneuert. Bei erforderlicher
Interaktion übernimmt der sichtbare Browser die noch vorhandenen Cookies und
wartet bis zu fünf Minuten auf den Abschluss; Zugangsdaten werden dabei nicht
erneut in das Formular geschrieben. Headless bricht mit `InteractionRequired` ab.
HTTP 401/403 beim Passwort-Login ist ein Authentifizierungsfehler, kein MFA-Signal.
Schul-ID: aus `mo<id>.schulportal.hessen.de` oder dem `i`-Parameter der Loginseite.
Course-Sync teilt die SPH-Sitzung pro Schule/Benutzer über
`$XDG_CACHE_HOME/sph-login/` (Standard `~/.cache/sph-login/`) auch zwischen Kursen.
Die vorhandenen `MOODLE_*`-Zugangsdaten und Browser-Storage-States bleiben nutzbar.
Für eigene Browser-Adapter: `InteractionRequired.continuation_url` enthält ggf.
das Ziel des nächsten Schritts. Pending-Cookies vor dem Schließen über
`install_in_browser()` übernehmen. Weiterleitungs-URLs können Tokens enthalten
und dürfen nicht geloggt werden.

`keepalive()` betrifft nur LANiS. `False` heißt: wegen des Intervalls übersprungen.
`True` heißt: Anfrage ohne erkannten Fehler gesendet, nicht nachgewiesene
Sitzungsverlängerung. HTTP-/HTML-Fehler und explizite JSON-Fehler (`success=false`,
`ok=false`, `error`) lösen `AuthenticationError` aus. Das vollständige reale
Antwortprotokoll ist noch nicht verifiziert.

Remote-Moodle-Aufgaben weiterhin ausschließlich über die vorgesehenen `inv kurse.*`-Tasks ausführen.

## Grenzen und Sitzungsdaten

Unterstützt den normalen Schulbezug-Login unter `login.schulportal.hessen.de`.
MFA, Captchas und Gerätefreigaben werden nicht automatisiert. Keine automatische
30-Tage-Geräteregistrierung: deren zusätzlicher Ablauf ist bisher nicht live
validiert. Auch dieser HTTP-Ablauf ist zunächst durch simulierte Antworten geprüft.
Die von den Vorbildprojekten verwendeten internen Endpunkte können sich ändern.

Sitzungsdateien enthalten Zugriffscookies, kein Passwort. Sie werden atomar mit
Dateirechten 0600 geschrieben und an Schule und Benutzer gebunden. Außerhalb des
Repos und außerhalb synchronisierter Ordner ablegen. Cookies und Passwörter nicht
loggen. HTTP-Weiterleitungen beim Login sind auf HTTPS-Schulportal-Hosts begrenzt.
Fehler enthalten keine Antwortkörper oder Weiterleitungstokens.

Vorbild für das Protokoll (eigene Implementierung):
[dewenni/lanis](https://github.com/dewenni/lanis/blob/main/app/lib/lanisapi/helpers/authentication.py)
und [liblanis-for-python](https://github.com/lanis-mobile/liblanis-for-python/blob/master/src/liblanis/core/session.py).
