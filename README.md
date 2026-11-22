# Movie Club

Movie Club is a private, two-person Django app for logging movies and TV series, comparing ratings, and deciding what to watch next. It uses SQLite, one Django app, Django templates, and plain CSS. Gunicorn runs the production app. WhiteNoise serves its static assets.

## Run locally

Use Python 3.10 or newer supported by Django 5.2 LTS, preferably a current Python 3.12 or newer maintenance release.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
export DJANGO_DEBUG=True
python manage.py migrate
python manage.py createsuperuser --username first-friend
python manage.py createsuperuser --username second-friend
python manage.py runserver
```

Open http://127.0.0.1:8000 and sign in. The Django management command prompts for passwords. A user can change a password through `python manage.py changepassword USERNAME` on the server. The first two active accounts by creation order are the club members. Create only the two intended club accounts. Membership and the friend recipient are derived from the database.

Set `TMDB_READ_TOKEN` to your TMDB API Read Access Token or `TMDB_API_KEY` to your v3 key before starting Django. An existing local collection works without credentials. Search and first-time imports require access to TMDB. Use a private environment file or enter credentials through your shell's secret input mechanism. [.env.example](.env.example) lists the supported production settings.

## Use the club

Open **Find a Title**, search TMDB, and select a movie or TV series. Its title page offers actions to log it as watched, recommend it, or add it to a watchlist. Each user can leave an optional half-point rating and a review. Personal dashboards show watch counts, collections, watchlists, and Top 5 picks. Select Top 5 picks from your watched collection.

Marking a personal watchlist entry as watched creates a personal watched entry and removes the watchlist entry. Completing a shared watchlist entry changes its shared status only.

Logging a title in your collection marks all your incoming recommendations for that title as Watched and preserves their messages and feedback. You can also mark a recommendation Watched separately and log the title later. Removing a collection entry preserves the recommendation's viewing history. Deleting a parent comment preserves existing replies beneath a deleted-comment notice.

## Deploy on a home Linux server

These instructions assume a systemd host, a Cloudflare-managed hostname, and `cloudflared` running on the same host as Gunicorn. Substitute your own dedicated hostname for `club.example.com`.

1. Create a dedicated unprivileged `movieclub` service account. Copy or clone this project to `/srv/movieclub`, owned by that account. Create a private data directory such as `/srv/movieclub/data` owned by `movieclub` and writable only by it.
2. As `movieclub`, create the virtual environment and install the requirements as in the local setup. Use the absolute interpreter path `/srv/movieclub/.venv/bin/python` for subsequent commands, or activate the environment.
3. Create `/etc/movieclub.env` based on `.env.example`. Keep the file readable only by its owner and the service group, for example `root:movieclub` with mode `0640`. Generate a secret using `python -c 'import secrets; print(secrets.token_urlsafe(48))'`. Set `DJANGO_DEBUG=False`, the secret key, `DJANGO_ALLOWED_HOSTS=club.example.com`, `DJANGO_CSRF_TRUSTED_ORIGINS=https://club.example.com`, `DJANGO_DB_PATH=/srv/movieclub/data/club.sqlite3`, and a TMDB credential. Optionally set `DJANGO_TIME_ZONE` to a valid IANA time zone. Use shell-compatible assignments without spaces around the equals sign.
4. In a shell as `movieclub`, from `/srv/movieclub` with the virtual environment active, run the following. Create each of the two users during the first deployment.

   ```sh
   umask 077
   set -a
   . /etc/movieclub.env
   set +a
   python manage.py check --deploy --fail-level WARNING
   python manage.py migrate
   python manage.py collectstatic --noinput
   python manage.py createsuperuser --username first-friend
   python manage.py createsuperuser --username second-friend
   ```

5. Install [the service file](deploy/movieclub.service) as `/etc/systemd/system/movieclub.service`. Adjust paths if your checkout differs. Run `sudo systemctl daemon-reload` and `sudo systemctl enable --now movieclub`. Use `sudo journalctl -u movieclub` to inspect startup errors.
6. [Set up Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/get-started/). Add a published application route for `club.example.com`, with service URL `http://127.0.0.1:8000`. Keep Gunicorn bound to loopback and have only trusted local processes reach that port. Django uses the proxy's `X-Forwarded-Proto` header to recognize HTTPS. Preserve the public Host header and bypass browser-page caching at Cloudflare for this hostname. Public clients should use `https://club.example.com/login/`. No inbound router port forward is needed.
7. From a browser outside the server, verify that an anonymous visitor lands at login, both accounts can sign in, forms submit over HTTPS, TMDB search and import work, and logout returns to login. Check that a friend can browse the other profile and can edit their own entries.

### Backup and updates

Keep backups of the SQLite database and environment file in private, separate storage. Use SQLite's online backup for a running site, for example `sqlite3 /srv/movieclub/data/club.sqlite3 ".backup '/private/backup/club.sqlite3'"`. To restore, stop the service, back up the current database, restore the backup to the configured path with matching ownership, then start the service. Check the restored database with `PRAGMA integrity_check;` before resuming writes.

Before updating, back up the database. Install updated dependencies, run the tests, stop the service for migrations, apply migrations, collect static assets, and restart the service. Check the service log and the HTTPS sign-in page.

## Verification

```sh
DJANGO_DEBUG=True python manage.py test
DJANGO_DEBUG=True python manage.py makemigrations --check --dry-run
```

Tests use an isolated SQLite database and stub TMDB responses. The production deployment check uses real production settings and the configured environment.

The Credits page includes the [TMDB API attribution](https://developer.themoviedb.org/docs/faq). The unmodified TMDB logo by Travis Bell is included from its [Wikimedia Commons archive](https://commons.wikimedia.org/wiki/File:Tmdb.new.logo.svg), which records the original asset URL and distribution license.
