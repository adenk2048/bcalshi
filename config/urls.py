"""URL configuration for Bcalshi.

Pages render templates; everything under /api/ is JSON and lives in the
owning app's urls.py.
"""
from django.contrib import admin
from django.urls import include, path

from markets import views as market_views
from trading import views as trading_views
from users import views as user_views

urlpatterns = [
    # admin
    path("admin/", admin.site.urls),

    # pages
    path("", market_views.home_page, name="home"),
    path("market/<int:market_id>/", market_views.market_page, name="market-page"),
    path("portfolio/", trading_views.portfolio_page, name="portfolio-page"),
    path("orders/", trading_views.orders_page, name="orders-page"),
    path("trades/", trading_views.trades_page, name="trades-page"),
    path("control/", market_views.control_page, name="control-page"),
    path("suggest/", market_views.suggest_page, name="suggest-page"),

    # accounts
    path("accounts/", include("django.contrib.auth.urls")),
    path("accounts/signup/", user_views.signup, name="signup"),

    # APIs
    path("api/users/", include("users.urls")),
    path("api/markets/", include("markets.urls")),
    path("api/trading/", include("trading.urls")),
]
