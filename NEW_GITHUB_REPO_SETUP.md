# Neues GitHub-Repo fuer DocaroApp aufsetzen

Wenn das urspruengliche Remote-Repo nicht mehr existiert, kannst du dieses Repo lokal weiterverwenden und einfach auf ein **neues** GitHub-Repository pushen.

## Voraussetzungen

- Git ist installiert
- Du hast Zugriff auf GitHub (Web + SSH-Key oder PAT)
- Du bist im Repo-Ordner (typisch: `/opt/docaro`)

## 1) Lokalen Status prüfen

```bash
cd /opt/docaro
git status -sb
```

Wichtig:
- Laufzeitdaten unter `data/` sollten **nicht** committed werden. In diesem Repo sind die typischen Runtime-Files bereits in `.gitignore` ausgeschlossen.

## 2) Neues Repo auf GitHub anlegen

Auf GitHub:
- „New repository“
- Name z.B. `DocaroApp`
- **Ohne** README/.gitignore/License initialisieren (damit es wirklich leer ist)

Merke dir die Repo-URL, z.B.:
- SSH: `git@github.com:<ORG_ODER_USER>/DocaroApp.git`
- HTTPS: `https://github.com/<ORG_ODER_USER>/DocaroApp.git`

## 3) Altes Remote ersetzen

Remotes anzeigen:

```bash
git remote -v
```

Falls `origin` auf das alte (gelöschte) Repo zeigt:

```bash
git remote remove origin
```

Neues Remote setzen:

```bash
git remote add origin git@github.com:<ORG_ODER_USER>/DocaroApp.git
```

## 4) Branch-Name und Push

Aktuellen Branch prüfen:

```bash
git branch --show-current
```

Dann pushen:

```bash
git push -u origin HEAD
```

Wenn du auf `main` umstellen willst (optional):

```bash
git branch -M main
git push -u origin main
```

## 5) Deploy auf dem Zielserver (nur Code)

```bash
sudo adduser --system --group --home /opt/docaro docaro || true
sudo -u docaro -H git clone git@github.com:<ORG_ODER_USER>/docaro.git /opt/docaro
```

Dann weiter mit:
- [DEPLOYMENT_LINUX.md](DEPLOYMENT_LINUX.md)
- [DEPENDENCIES.md](DEPENDENCIES.md)

## 6) Daten-Migration (ohne Git)

Siehe Abschnitt „Daten-Migration“ in [DEPLOYMENT_LINUX.md](DEPLOYMENT_LINUX.md).
