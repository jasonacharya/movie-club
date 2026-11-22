from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, StepValueValidator
from django.db import models
from django.db.models import Q


class Genre(models.Model):
    name = models.CharField(max_length=80, unique=True)

    def __str__(self):
        return self.name


class Title(models.Model):
    class Media(models.TextChoices):
        MOVIE = "movie", "Movie"
        TV = "tv", "TV Series"

    tmdb_id = models.PositiveBigIntegerField()
    media_type = models.CharField(max_length=5, choices=Media)
    name = models.CharField(max_length=300)
    release_date = models.DateField(null=True, blank=True)
    poster_path = models.CharField(max_length=200, blank=True)
    overview = models.TextField(blank=True)
    genres = models.ManyToManyField(Genre, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tmdb_id", "media_type"], name="unique_tmdb_title"),
            models.CheckConstraint(condition=Q(media_type__in=["movie", "tv"]), name="valid_media_type"),
        ]
        ordering = ["name", "pk"]

    @property
    def poster_url(self):
        return f"https://image.tmdb.org/t/p/w342{self.poster_path}" if self.poster_path else ""

    def __str__(self):
        year = f" ({self.release_date.year})" if self.release_date else ""
        return f"{self.name}{year} · {self.get_media_type_display()}"


class Watched(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.ForeignKey(Title, on_delete=models.CASCADE)
    rating = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(10), StepValueValidator(Decimal("0.5"))])
    review = models.TextField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "title"], name="unique_watched")]


class Pick(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.ForeignKey(Title, on_delete=models.CASCADE)
    rank = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["rank"]
        constraints = [
            models.CheckConstraint(condition=Q(rank__gte=1, rank__lte=5), name="pick_rank_range"),
            models.UniqueConstraint(fields=["user", "rank"], name="unique_pick_rank"),
            models.UniqueConstraint(fields=["user", "title"], name="unique_pick_title"),
        ]


class PersonalWatch(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.ForeignKey(Title, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["user", "title"], name="unique_personal_watch")]


class SharedWatch(models.Model):
    title = models.OneToOneField(Title, on_delete=models.CASCADE)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    watched = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["watched", "-created_at", "-pk"]


class Recommendation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        WATCHED = "watched", "Watched"
        DECLINED = "declined", "Not Interested"

    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_picks")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="received_picks")
    title = models.ForeignKey(Title, on_delete=models.CASCADE)
    status = models.CharField(max_length=8, choices=Status, default=Status.PENDING)
    message = models.TextField(max_length=500, blank=True)
    feedback = models.TextField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["sender", "recipient", "title"],
                condition=Q(status="pending"), name="unique_pending_recommendation"),
            models.CheckConstraint(condition=~Q(sender=models.F("recipient")), name="different_recommendation_users"),
            models.CheckConstraint(condition=Q(status__in=["pending", "watched", "declined"]), name="valid_recommendation_status"),
        ]


class Comment(models.Model):
    title = models.ForeignKey(Title, on_delete=models.CASCADE)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    body = models.TextField(max_length=1000)
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
