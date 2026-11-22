from django.urls import path
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("members/<int:user_id>/", views.dashboard, name="dashboard"),
    path("members/<int:user_id>/collection/", views.collection, name="collection"),
    path("members/<int:user_id>/watchlist/", views.personal_list, name="personal_list"),
    path("search/", views.search, name="search"),
    path("search/save/", views.import_title, name="import_title"),
    path("titles/<int:title_id>/", views.detail, name="detail"),
    path("titles/<int:title_id>/log/", views.watched_add, name="watched_add"),
    path("watched/<int:entry_id>/edit/", views.watched_edit, name="watched_edit"),
    path("watched/<int:entry_id>/delete/", views.watched_delete, name="watched_delete"),
    path("top-five/", views.picks_edit, name="picks_edit"),
    path("recommendations/", views.recommendations, name="recommendations"),
    path("titles/<int:title_id>/recommend/", views.recommend, name="recommend"),
    path("recommendations/<int:entry_id>/message/", views.recommendation_message, name="recommendation_message"),
    path("recommendations/<int:entry_id>/status/", views.recommendation_update, name="recommendation_update"),
    path("recommendations/<int:entry_id>/feedback/", views.recommendation_feedback, name="recommendation_feedback"),
    path("shared/", views.shared_list, name="shared_list"),
    path("titles/<int:title_id>/watchlist/<str:scope>/", views.watchlist_add, name="watchlist_add"),
    path("watchlist/<int:entry_id>/<str:action>/", views.personal_change, name="personal_change"),
    path("shared/<int:entry_id>/watched/", views.shared_watched, name="shared_watched"),
    path("titles/<int:title_id>/discuss/", views.comment_add, name="comment_add"),
    path("titles/<int:title_id>/reply/<int:parent_id>/", views.comment_add, name="comment_reply"),
    path("comments/<int:entry_id>/edit/", views.comment_edit, name="comment_edit"),
    path("comments/<int:entry_id>/delete/", views.comment_delete, name="comment_delete"),
    path("statistics/", views.statistics, name="statistics"),
    path("credits/", TemplateView.as_view(template_name="core/credits.html"), name="credits"),
]
