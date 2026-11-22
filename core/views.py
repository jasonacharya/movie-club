from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Prefetch, Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from . import tmdb
from .forms import CommentForm, FeedbackForm, ImportForm, MessageForm, PickForm, SearchForm, StatusForm, WatchedForm
from .models import Comment, Genre, PersonalWatch, Pick, Recommendation, SharedWatch, Title, Watched


def friend(request):
    return next((user for user in request.members if user != request.user), None)


def profile(request, user_id):
    return get_object_or_404(request.user.__class__, pk=user_id, pk__in=[user.pk for user in request.members])


def counts(user):
    totals = dict(Watched.objects.filter(user=user).values("title__media_type").annotate(total=Count("pk"))
                  .values_list("title__media_type", "total"))
    return totals.get("movie", 0), totals.get("tv", 0)


@require_safe
def home(request):
    return redirect("dashboard", request.user.pk)


@require_safe
def dashboard(request, user_id):
    owner = profile(request, user_id)
    movies, series = counts(owner)
    picks = Pick.objects.filter(user=owner).select_related("title")
    viewer_watched = set(Watched.objects.filter(user=request.user, title__pick__user=owner).values_list("title_id", flat=True))
    return render(request, "core/dashboard.html", locals())


@require_safe
def collection(request, user_id):
    owner = profile(request, user_id)
    entries = Watched.objects.filter(user=owner).select_related("title")
    genres = Genre.objects.filter(title__watched__user=owner).distinct().order_by("name")
    q = request.GET.get("q", "").strip()[:150]
    media = request.GET.get("media", "")
    genre = request.GET.get("genre", "")
    sort = request.GET.get("sort", "recent")
    if q:
        entries = entries.filter(title__name__icontains=q)
    if media in Title.Media.values:
        entries = entries.filter(title__media_type=media)
    if genre.isascii() and genre.isdecimal() and len(genre) < 19:
        entries = entries.filter(title__genres=genre)
    sorts = {
        "highest": (F("rating").desc(nulls_last=True), "title__name", "pk"),
        "lowest": (F("rating").asc(nulls_last=True), "title__name", "pk"),
        "title": ("title__name", "pk"),
        "recent": ("-created_at", "-pk"),
    }
    page = Paginator(entries.order_by(*sorts.get(sort, sorts["recent"])), 24).get_page(request.GET.get("page"))
    return render(request, "core/collection.html", locals())


@require_safe
def search(request):
    form = SearchForm(request.GET or None)
    results, error = [], ""
    if form.is_valid():
        try:
            results = tmdb.search(form.cleaned_data["q"])
        except tmdb.TMDBError as exc:
            error = str(exc)
    return render(request, "core/search.html", locals())


@require_POST
def import_title(request):
    form = ImportForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Invalid title selection.")
    try:
        title = tmdb.import_title(form.cleaned_data["media_type"], form.cleaned_data["tmdb_id"])
    except tmdb.TMDBError as exc:
        messages.error(request, str(exc))
        return redirect("search")
    messages.success(request, "Title saved. Choose how you want to use it.")
    return redirect("detail", title.pk)


@require_safe
def detail(request, title_id):
    title = get_object_or_404(Title.objects.prefetch_related("genres"), pk=title_id)
    entries = {entry.user_id: entry for entry in Watched.objects.filter(title=title)}
    ratings = [(member, entries.get(member.pk)) for member in request.members]
    watched = entries.get(request.user.pk)
    other = friend(request)
    already_watched = other is not None and other.pk in entries
    comments = title.comment_set.filter(parent__isnull=True).select_related("author").prefetch_related(
        Prefetch("replies", queryset=Comment.objects.filter(deleted=False).select_related("author"))
    )
    comments = [comment for comment in comments if not comment.deleted or list(comment.replies.all())]
    return render(request, "core/detail.html", locals())


def record_watched(user, title, defaults=None):
    entry, created = Watched.objects.get_or_create(user=user, title=title, defaults=defaults)
    Recommendation.objects.filter(recipient=user, title=title).exclude(status=Recommendation.Status.WATCHED).update(
        status=Recommendation.Status.WATCHED)
    PersonalWatch.objects.filter(user=user, title=title).delete()
    return entry, created


@require_http_methods(["GET", "POST"])
def watched_add(request, title_id):
    title = get_object_or_404(Title, pk=title_id)
    existing = Watched.objects.filter(title=title, user=request.user).first()
    if existing:
        messages.info(request, "This title is already in your collection. You can edit it here.")
        return redirect("watched_edit", existing.pk)
    form = WatchedForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        with transaction.atomic():
            entry, created = record_watched(request.user, title, form.cleaned_data)
        if not created:
            messages.info(request, "This title is already in your collection. You can edit it here.")
            return redirect("watched_edit", entry.pk)
        return redirect("detail", title.pk)
    return render(request, "core/form.html", {"heading": f"Log {title.name}", "form": form})


@require_http_methods(["GET", "POST"])
def watched_edit(request, entry_id):
    entry = get_object_or_404(Watched.objects.select_related("title"), pk=entry_id, user=request.user)
    form = WatchedForm(request.POST if request.method == "POST" else None, instance=entry)
    if form.is_valid():
        Watched.objects.filter(pk=entry.pk, user=request.user).update(**form.cleaned_data)
        return redirect("detail", entry.title_id)
    return render(request, "core/form.html", {"heading": f"Edit your entry for {entry.title.name}", "form": form})


@require_POST
def watched_delete(request, entry_id):
    entry = get_object_or_404(Watched, pk=entry_id, user=request.user)
    entry.delete()
    return redirect("detail", entry.title_id)


@require_http_methods(["GET", "POST"])
def picks_edit(request):
    if request.method == "POST":
        with transaction.atomic():
            picks = list(Pick.objects.filter(user=request.user))
            action = request.POST.get("action")
            if action == "add":
                form = PickForm(request.user, [pick.title_id for pick in picks], request.POST)
                if len(picks) < 5 and form.is_valid():
                    Pick.objects.create(user=request.user, title=form.cleaned_data["title"], rank=len(picks) + 1)
                    return redirect("picks_edit")
                messages.error(request, "Choose an eligible title and keep the list to five picks.")
            else:
                index = next((i for i, pick in enumerate(picks) if str(pick.pk) == request.POST.get("pick")), None)
                if index is None:
                    raise Http404
                if action == "replace":
                    form = PickForm(request.user, [pick.title_id for pick in picks], request.POST)
                    if form.is_valid():
                        Pick.objects.filter(pk=picks[index].pk).update(title=form.cleaned_data["title"])
                    else:
                        messages.error(request, "Choose a watched title that is outside your Top 5.")
                    return redirect("picks_edit")
                if action == "remove":
                    picks.pop(index)
                elif action in {"up", "down"}:
                    target = index + (-1 if action == "up" else 1)
                    if 0 <= target < len(picks):
                        picks[index], picks[target] = picks[target], picks[index]
                else:
                    return HttpResponseBadRequest("Unknown Top 5 action.")
                Pick.objects.filter(user=request.user).delete()
                Pick.objects.bulk_create([
                    Pick(pk=pick.pk, user=request.user, title_id=pick.title_id, rank=position)
                    for position, pick in enumerate(picks, start=1)
                ])
                return redirect("picks_edit")
    picks = list(Pick.objects.filter(user=request.user).select_related("title"))
    form = PickForm(request.user, [pick.title_id for pick in picks])
    return render(request, "core/picks.html", locals())


@require_safe
def recommendations(request):
    logged = set(Watched.objects.filter(user=request.user).values_list("title_id", flat=True))
    incoming = request.user.received_picks.select_related("title", "sender")
    unresolved = Q(status="pending") & ~Q(title_id__in=logged)
    pending = incoming.filter(unresolved)
    history = incoming.exclude(unresolved)
    outgoing = request.user.sent_picks.select_related("title", "recipient")
    return render(request, "core/recommendations.html", locals())


@require_http_methods(["GET", "POST"])
def recommend(request, title_id):
    title = get_object_or_404(Title, pk=title_id)
    recipient = friend(request)
    if recipient is None:
        messages.info(request, "The second club account is needed to send a recommendation.")
        return redirect("detail", title.pk)
    form = MessageForm(request.POST if request.method == "POST" else None)
    with transaction.atomic():
        if Watched.objects.filter(user=recipient, title=title).exists():
            messages.info(request, "Already Watched")
            return redirect("detail", title.pk)
        existing = Recommendation.objects.filter(sender=request.user, recipient=recipient, title=title, status="pending").first()
        if existing:
            messages.info(request, "You already have a pending recommendation for this title.")
            return redirect("recommendation_message", existing.pk)
        if form.is_valid():
            Recommendation.objects.create(sender=request.user, recipient=recipient, title=title,
                                          message=form.cleaned_data["message"])
            return redirect("recommendations")
    return render(request, "core/form.html", {"heading": f"Recommend {title.name} to {recipient.username}", "form": form})


@require_http_methods(["GET", "POST"])
def recommendation_message(request, entry_id):
    entry = get_object_or_404(Recommendation, pk=entry_id, sender=request.user)
    form = MessageForm(request.POST if request.method == "POST" else None, instance=entry)
    if form.is_valid():
        Recommendation.objects.filter(pk=entry.pk, sender=request.user).update(message=form.cleaned_data["message"])
        return redirect("recommendations")
    return render(request, "core/form.html", {"heading": f"Edit message for {entry.title.name}", "form": form})


@require_http_methods(["GET", "POST"])
def recommendation_update(request, entry_id):
    entry = get_object_or_404(Recommendation, pk=entry_id, recipient=request.user)
    form = StatusForm(request.POST if request.method == "POST" else None, instance=entry)
    if form.is_valid():
        status = form.cleaned_data["status"]
        with transaction.atomic():
            entry.refresh_from_db()
            if status != "watched" and (entry.feedback or Watched.objects.filter(user=request.user, title=entry.title).exists()):
                form.add_error("status", "This title has a watched entry or feedback and must stay Watched.")
            elif status == "pending" and Recommendation.objects.filter(
                sender=entry.sender, recipient=request.user, title=entry.title, status="pending"
            ).exclude(pk=entry.pk).exists():
                form.add_error("status", "A newer recommendation for this title is already pending.")
            else:
                Recommendation.objects.filter(pk=entry.pk).update(status=status)
                return redirect("recommendations")
    return render(request, "core/form.html", {"heading": f"Update status for {entry.title.name}", "form": form})


@require_http_methods(["GET", "POST"])
def recommendation_feedback(request, entry_id):
    entry = get_object_or_404(Recommendation, pk=entry_id, recipient=request.user, status="watched")
    form = FeedbackForm(request.POST if request.method == "POST" else None, instance=entry)
    if form.is_valid():
        updated = Recommendation.objects.filter(pk=entry.pk, status="watched").update(feedback=form.cleaned_data["feedback"])
        if not updated:
            raise Http404
        return redirect("recommendations")
    return render(request, "core/form.html", {"heading": f"Feedback on {entry.title.name}", "form": form})


@require_safe
def personal_list(request, user_id):
    owner = profile(request, user_id)
    entries = PersonalWatch.objects.filter(user=owner).select_related("title")
    return render(request, "core/watchlist.html", locals())


@require_safe
def shared_list(request):
    entries = SharedWatch.objects.select_related("title", "added_by")
    return render(request, "core/watchlist.html", {"entries": entries, "shared": True})


@require_POST
def watchlist_add(request, title_id, scope):
    title = get_object_or_404(Title, pk=title_id)
    if scope == "personal":
        with transaction.atomic():
            if Watched.objects.filter(title=title, user=request.user).exists():
                messages.info(request, "You already watched this title.")
            else:
                PersonalWatch.objects.get_or_create(title=title, user=request.user)
                messages.success(request, "In your personal watchlist.")
    elif scope == "shared":
        SharedWatch.objects.get_or_create(title=title, defaults={"added_by": request.user})
        messages.success(request, "In the shared watchlist.")
    else:
        raise Http404
    return redirect("detail", title.pk)


@require_POST
@transaction.atomic
def personal_change(request, entry_id, action):
    entry = get_object_or_404(PersonalWatch, pk=entry_id, user=request.user)
    if action == "watched":
        record_watched(request.user, entry.title)
        return redirect("detail", entry.title_id)
    if action == "remove":
        entry.delete()
        return redirect("personal_list", request.user.pk)
    raise Http404


@require_POST
def shared_watched(request, entry_id):
    updated = SharedWatch.objects.filter(pk=entry_id).update(watched=True)
    if not updated:
        raise Http404
    return redirect("shared_list")


@require_http_methods(["GET", "POST"])
def comment_add(request, title_id, parent_id=None):
    title = get_object_or_404(Title, pk=title_id)
    parent = None
    if parent_id is not None:
        parent = get_object_or_404(Comment, pk=parent_id, title=title, parent__isnull=True, deleted=False)
    form = CommentForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        with transaction.atomic():
            if parent and not Comment.objects.filter(pk=parent.pk, deleted=False).exists():
                raise Http404
            Comment.objects.create(title=title, author=request.user, parent=parent, body=form.cleaned_data["body"])
        return redirect("detail", title.pk)
    heading = f"{'Reply to ' + parent.author.username if parent else 'Discuss'} · {title.name}"
    return render(request, "core/form.html", {"heading": heading, "form": form})


@require_http_methods(["GET", "POST"])
def comment_edit(request, entry_id):
    entry = get_object_or_404(Comment, pk=entry_id, author=request.user, deleted=False)
    form = CommentForm(request.POST if request.method == "POST" else None, instance=entry)
    if form.is_valid():
        Comment.objects.filter(pk=entry.pk, deleted=False).update(body=form.cleaned_data["body"])
        return redirect("detail", entry.title_id)
    return render(request, "core/form.html", {"heading": "Edit your comment", "form": form})


@require_POST
def comment_delete(request, entry_id):
    entry = get_object_or_404(Comment, pk=entry_id, author=request.user, deleted=False)
    Comment.objects.filter(pk=entry.pk).update(body="", deleted=True)
    return redirect("detail", entry.title_id)


@require_safe
def statistics(request):
    totals = [(member, *counts(member)) for member in request.members]
    return render(request, "core/statistics.html", {"totals": totals})
