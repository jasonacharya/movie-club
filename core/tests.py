import json
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from . import tmdb
from .models import Comment, Genre, PersonalWatch, Pick, Recommendation, SharedWatch, Title, Watched


@override_settings(
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
    SECURE_SSL_REDIRECT=False,
)
class ClubTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.alex = users.create_user("alex", password="blue-cinema-89")
        cls.blair = users.create_user("blair", password="red-cinema-82")
        cls.extra = users.create_user("extra", password="another-cinema-80")
        cls.movie = Title.objects.create(name="Long Night", media_type="movie", tmdb_id=21)
        cls.tv = Title.objects.create(name="Short Day", media_type="tv", tmdb_id=21)
        cls.genre = Genre.objects.create(name="Drama")
        cls.movie.genres.add(cls.genre)

    def setUp(self):
        self.client.force_login(self.alex)

    def post(self, route, args=(), **data):
        return self.client.post(reverse(route, args=args), data)

    def get(self, route, *args, **data):
        return self.client.get(reverse(route, args=args), data)

    def test_login_logout_and_private_pages(self):
        self.client.logout()
        for route, args in [("home", ()), ("detail", (self.movie.pk,)), ("search", ()), ("credits", ())]:
            self.assertRedirects(self.get(route, *args), f"/login/?next={reverse(route, args=args)}")
        self.assertEqual(self.get("login").status_code, 200)
        self.assertEqual(self.post("login", username="alex", password="blue-cinema-89").status_code, 302)
        self.assertEqual(self.get("logout").status_code, 405)
        self.assertRedirects(self.post("logout"), "/login/")

    def test_extra_account_denied_and_profiles_are_dynamic(self):
        self.assertContains(self.get("dashboard", self.blair.pk), "blair")
        self.assertEqual(self.get("dashboard", self.extra.pk).status_code, 404)
        self.client.force_login(self.extra)
        self.assertEqual(self.get("home").status_code, 403)
        self.client.logout()
        response = self.post("login", username="extra", password="another-cinema-80")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_csrf_and_post_only(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alex)
        url = reverse("watchlist_add", args=[self.movie.pk, "personal"])
        self.assertEqual(client.get(url).status_code, 405)
        self.assertEqual(client.post(url).status_code, 403)
        self.assertFalse(PersonalWatch.objects.exists())

    def test_watched_validates_rating_and_escapes_review(self):
        for invalid in ("8.2", "10.5", "-0.5"):
            self.assertEqual(self.post("watched_add", [self.movie.pk], rating=invalid).status_code, 200)
        self.assertFalse(Watched.objects.exists())
        self.assertEqual(self.post("watched_add", [self.movie.pk], rating="8.5", review="<script>").status_code, 302)
        entry = Watched.objects.get()
        self.assertEqual(entry.rating, Decimal("8.5"))
        self.assertContains(self.get("detail", self.movie.pk), "&lt;script&gt;")
        self.assertRedirects(self.post("watched_add", [self.movie.pk], rating="1"),
                             reverse("watched_edit", args=[entry.pk]))
        self.assertEqual(Watched.objects.count(), 1)

    def test_watched_permissions_and_shared_title_survive_removal(self):
        own = Watched.objects.create(user=self.alex, title=self.movie)
        other = Watched.objects.create(user=self.blair, title=self.movie, rating=9)
        self.assertContains(self.get("collection", self.blair.pk), "Long Night")
        self.assertEqual(self.post("watched_edit", [other.pk], rating="2").status_code, 404)
        self.assertEqual(self.post("watched_delete", [other.pk]).status_code, 404)
        self.post("watched_delete", [own.pk])
        self.assertTrue(Title.objects.filter(pk=self.movie.pk).exists())
        self.assertTrue(Watched.objects.filter(pk=other.pk).exists())

    def test_local_filters_and_statistics(self):
        Watched.objects.create(user=self.alex, title=self.movie, rating=0)
        Watched.objects.create(user=self.alex, title=self.tv)
        with patch("core.tmdb.fetch", side_effect=AssertionError("unexpected network request")):
            filtered = self.get("collection", self.alex.pk, media="movie", genre=self.genre.pk, q="night", sort="lowest")
            self.assertContains(filtered, "Long Night")
            self.assertNotContains(filtered, "Short Day")
            self.assertContains(filtered, "0.0/10")
            self.assertEqual(self.get("statistics").context["totals"], [(self.alex, 1, 1), (self.blair, 0, 0)])

    def test_collection_pages_preserve_filters(self):
        for index in range(25):
            title = Title.objects.create(name=f"Night {index}", media_type="movie", tmdb_id=100 + index)
            Watched.objects.create(user=self.alex, title=title)
        result = self.get("collection", self.alex.pk, q="Night", sort="title")
        self.assertContains(result, "q=Night&amp;sort=title&amp;page=2")
        self.assertEqual(len(result.context["page"].object_list), 24)

    def test_top_five_limit_repeat_reorder_replace_and_remove(self):
        titles = [self.movie, self.tv] + [
            Title.objects.create(name=f"Movie {index}", tmdb_id=index, media_type="movie")
            for index in range(1, 5)
        ]
        for title in titles:
            Watched.objects.create(user=self.alex, title=title)
        for title in titles:
            self.post("picks_edit", action="add", title=title.pk)
        self.assertEqual(Pick.objects.count(), 5)
        top, second = list(Pick.objects.all())[:2]
        self.post("picks_edit", action="down", pick=top.pk)
        self.assertEqual(Pick.objects.first().pk, second.pk)
        self.post("picks_edit", action="replace", pick=second.pk, title=titles[-1].pk)
        self.assertEqual(Pick.objects.first().title, titles[-1])
        self.post("picks_edit", action="replace", pick=second.pk, title=top.title_id)
        self.assertEqual(Pick.objects.first().title, titles[-1])
        self.post("picks_edit", action="remove", pick=second.pk)
        self.assertEqual(list(Pick.objects.values_list("rank", flat=True)), [1, 2, 3, 4])
        self.assertEqual(self.get("picks_edit").status_code, 200)

    def test_friend_top_five_read_only_and_watched_label(self):
        pick = Pick.objects.create(user=self.blair, title=self.movie, rank=1)
        Watched.objects.create(user=self.alex, title=self.movie)
        self.assertContains(self.get("dashboard", self.blair.pk), "Already Watched")
        self.assertEqual(self.post("picks_edit", action="remove", pick=pick.pk).status_code, 404)

    def test_recommendation_roles_and_status_lifecycle(self):
        self.post("recommend", [self.movie.pk], message="Give it a try.")
        self.post("recommend", [self.movie.pk], message="Duplicate")
        entry = Recommendation.objects.get()
        self.assertEqual(entry.message, "Give it a try.")
        self.assertEqual(self.post("recommendation_update", [entry.pk], status="watched").status_code, 404)
        self.assertEqual(self.post("recommendation_feedback", [entry.pk], feedback="Mine").status_code, 404)
        self.client.force_login(self.blair)
        self.assertEqual(self.post("recommendation_message", [entry.pk], message="Hijack").status_code, 404)
        self.assertEqual(self.post("recommendation_feedback", [entry.pk], feedback="Early").status_code, 404)
        self.post("recommendation_update", [entry.pk], status="watched")
        self.assertContains(self.get("recommendations"), "Add to Watched Collection")
        self.post("recommendation_feedback", [entry.pk], feedback="Loved it.")
        self.post("watched_add", [self.movie.pk], rating="10")
        self.assertContains(self.post("recommendation_update", [entry.pk], status="declined"), "must stay Watched")
        self.client.force_login(self.alex)
        self.assertContains(self.get("recommendations"), "Loved it.")
        self.assertContains(self.get("detail", self.movie.pk), "Already Watched")
        self.post("recommend", [self.movie.pk], message="Already watched")
        self.assertEqual(Recommendation.objects.count(), 1)

    def test_watchlists_sync_only_owned_entries(self):
        self.post("watchlist_add", [self.movie.pk, "personal"])
        self.post("watchlist_add", [self.movie.pk, "personal"])
        item = PersonalWatch.objects.get()
        self.post("watchlist_add", [self.movie.pk, "shared"])
        shared = SharedWatch.objects.get()
        self.assertContains(self.get("personal_list", self.alex.pk), "Long Night")
        self.assertContains(self.get("shared_list"), "Added by alex")
        self.client.force_login(self.blair)
        self.post("watchlist_add", [self.movie.pk, "shared"])
        self.assertEqual(SharedWatch.objects.count(), 1)
        self.assertEqual(self.post("personal_change", [item.pk, "remove"]).status_code, 404)
        self.post("shared_watched", [shared.pk])
        shared.refresh_from_db()
        self.assertTrue(shared.watched)
        self.assertFalse(Watched.objects.exists())
        self.post("recommend", [self.movie.pk], message="Watch it")
        self.client.force_login(self.alex)
        self.post("personal_change", [item.pk, "watched"])
        self.assertFalse(PersonalWatch.objects.exists())
        self.assertTrue(Watched.objects.filter(user=self.alex, title=self.movie).exists())
        self.assertEqual(Recommendation.objects.get().status, "watched")
        self.assertFalse(self.get("recommendations").context["pending"].exists())

    def test_discussion_is_one_level_and_parent_deletion_preserves_reply(self):
        self.post("comment_add", [self.movie.pk], body="What an ending")
        parent = Comment.objects.get()
        self.client.force_login(self.blair)
        self.assertEqual(self.post("comment_reply", [self.tv.pk, parent.pk], body="Wrong title").status_code, 404)
        self.post("comment_reply", [self.movie.pk, parent.pk], body="Agreed!")
        reply = Comment.objects.get(parent=parent)
        self.assertEqual(self.post("comment_reply", [self.movie.pk, reply.pk], body="Nested").status_code, 404)
        self.assertEqual(self.post("comment_edit", [parent.pk], body="Hijack").status_code, 404)
        self.assertEqual(self.post("comment_delete", [parent.pk]).status_code, 404)
        self.client.force_login(self.alex)
        self.post("comment_delete", [parent.pk])
        result = self.get("detail", self.movie.pk)
        self.assertContains(result, "Comment deleted")
        self.assertContains(result, "Agreed!")
        self.assertNotContains(result, "What an ending")

    def test_tmdb_search_import_and_local_deduplication(self):
        with patch("core.tmdb.fetch", return_value={"results": [
            {"id": 59, "media_type": "tv", "name": "Example TV"}, {"id": 31, "media_type": "person", "name": "Actor"}
        ]}) as fetch:
            self.assertContains(self.get("search", q="Example"), "Example TV")
            fetch.assert_called_once_with("search/multi", query="Example", include_adult="false")
        with patch("core.tmdb.fetch", return_value={"id": 59, "name": "Example TV",
                  "first_air_date": "2001-09-01", "genres": [{"name": "Drama"}]}) as fetch:
            result = self.post("import_title", media_type="tv", tmdb_id=59)
            self.assertEqual(result.status_code, 302)
            self.post("import_title", media_type="tv", tmdb_id=59)
            fetch.assert_called_once_with("tv/59")
        title = Title.objects.get(tmdb_id=59, media_type="tv")
        self.assertEqual(title.genres.get(), self.genre)
        self.assertContains(self.get("detail", title.pk), "poster-placeholder.svg")
        self.assertEqual(self.post("import_title", media_type="person", tmdb_id=59).status_code, 400)

    def test_tmdb_error_is_displayed_and_no_results_are_distinct(self):
        with patch("core.tmdb.fetch", side_effect=tmdb.TMDBError("Service unavailable.")):
            self.assertContains(self.get("search", q="Test"), "Service unavailable.")
        with patch("core.tmdb.fetch", return_value={"results": []}):
            self.assertContains(self.get("search", q="Test"), "No movies or TV series found.")

    def test_database_constraints(self):
        for create in (
            lambda: Title.objects.create(media_type="movie", tmdb_id=21, name="Duplicate"),
            lambda: Pick.objects.create(user=self.alex, title=self.movie, rank=6),
            lambda: Recommendation.objects.create(sender=self.alex, recipient=self.alex, title=self.movie),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                create()


@override_settings(TMDB_API_KEY="", TMDB_READ_TOKEN="test-token")
class TMDBTests(SimpleTestCase):
    def test_transport_and_rate_limit_errors_are_sanitized(self):
        for error, message in [
            (URLError("secret diagnostics"), "Could not connect"),
            (TimeoutError("internal"), "Could not connect"),
            (HTTPError("https://example.com/?api_key=secret", 429, "Rate limit", {}, None), "rate limiting"),
        ]:
            with patch("core.tmdb.build_opener") as opener, self.assertRaisesMessage(tmdb.TMDBError, message):
                opener.return_value.open.side_effect = error
                tmdb.fetch("tv/21")

    def test_request_uses_header_and_timeout(self):
        with patch("core.tmdb.build_opener") as opener:
            opener.return_value.open.return_value = BytesIO(json.dumps({"id": 21}).encode())
            self.assertEqual(tmdb.fetch("tv/21"), {"id": 21})
            args, kwargs = opener.return_value.open.call_args
            self.assertEqual(args[0].get_header("Authorization"), "Bearer test-token")
            self.assertNotIn("test-token", args[0].full_url)
            self.assertEqual(kwargs["timeout"], 6)

    def test_invalid_json(self):
        with patch("core.tmdb.build_opener") as opener, self.assertRaisesMessage(tmdb.TMDBError, "invalid response"):
            opener.return_value.open.return_value = BytesIO(b"not json")
            tmdb.fetch("tv/21")
