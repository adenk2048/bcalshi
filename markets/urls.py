from django.urls import path
from . import views

urlpatterns = [
    path("", views.list_markets),

    # suggestions (must precede the <int:market_id> patterns)
    path("suggestions/", views.create_suggestion, name="api-create-suggestion"),
    path("suggestions/me/", views.my_suggestions, name="api-my-suggestions"),
    path("suggestions/<int:suggestion_id>/review/", views.review_suggestion, name="api-review-suggestion"),

    path("<int:market_id>/", views.market_detail),
    path("<int:market_id>/positions/", views.market_positions),

    # superaccount controls
    path("<int:market_id>/resolve/", views.resolve_market_api, name="api-resolve-market"),
    path("<int:market_id>/close/", views.close_market_api, name="api-close-market"),
]
