import json
import re
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.db import transaction

from .models import Genre, Title


class TMDBError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(path, **params):
    headers = {"Accept": "application/json"}
    if settings.TMDB_READ_TOKEN:
        headers["Authorization"] = f"Bearer {settings.TMDB_READ_TOKEN}"
    elif settings.TMDB_API_KEY:
        params["api_key"] = settings.TMDB_API_KEY
    else:
        raise TMDBError("TMDB credentials are missing. Ask the club administrator to configure them.")

    request = Request(f"https://api.themoviedb.org/3/{path}?{urlencode(params)}", headers=headers)
    try:
        with build_opener(NoRedirect()).open(request, timeout=6) as response:
            data = json.loads(response.read(2_000_000))
    except HTTPError as error:
        if error.code == 404:
            raise TMDBError("TMDB could not find that title.") from None
        if error.code == 429:
            raise TMDBError("TMDB is rate limiting requests. Try again shortly.") from None
        raise TMDBError("TMDB is unavailable. Try again shortly.") from None
    except (URLError, OSError):
        raise TMDBError("Could not connect to TMDB in time. Try again shortly.") from None
    except (ValueError, UnicodeError):
        raise TMDBError("TMDB returned an invalid response.") from None
    if not isinstance(data, dict):
        raise TMDBError("TMDB returned an invalid response.")
    return data


def metadata(data, media):
    name = data.get("title" if media == "movie" else "name")
    if not isinstance(name, str) or not name.strip():
        raise TMDBError("TMDB returned a title without a name.")
    try:
        released = date.fromisoformat(data.get("release_date" if media == "movie" else "first_air_date") or "")
    except (TypeError, ValueError):
        released = None
    poster = data.get("poster_path")
    if not isinstance(poster, str) or not re.fullmatch(r"/[\w.-]{1,190}\.(?:jpg|jpeg|png|webp)", poster, re.ASCII):
        poster = ""
    overview = data.get("overview")
    return {
        "name": name.strip()[:300], "release_date": released, "poster_path": poster,
        "overview": overview.strip()[:3000] if isinstance(overview, str) else "",
    }


def search(query):
    results = fetch("search/multi", query=query, include_adult="false").get("results")
    if not isinstance(results, list):
        raise TMDBError("TMDB returned invalid search results.")
    titles = []
    for item in results:
        if not isinstance(item, dict):
            continue
        media, external_id = item.get("media_type"), item.get("id")
        if media in Title.Media.values and type(external_id) is int and 0 < external_id < 2**63:
            try:
                titles.append(Title(tmdb_id=external_id, media_type=media, **metadata(item, media)))
            except TMDBError:
                continue
    return titles


def import_title(media, external_id):
    existing = Title.objects.filter(media_type=media, tmdb_id=external_id).first()
    if existing:
        return existing
    data = fetch(f"{media}/{external_id}")
    if data.get("id") != external_id:
        raise TMDBError("TMDB returned an invalid title selection.")
    defaults = metadata(data, media)
    with transaction.atomic():
        title, created = Title.objects.get_or_create(media_type=media, tmdb_id=external_id, defaults=defaults)
        if created and isinstance(data.get("genres"), list):
            for genre in data["genres"]:
                name = genre.get("name") if isinstance(genre, dict) else None
                if isinstance(name, str) and name.strip():
                    title.genres.add(Genre.objects.get_or_create(name=name.strip()[:80])[0])
    return title
