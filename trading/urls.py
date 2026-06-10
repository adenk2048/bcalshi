from django.urls import path
from . import views

urlpatterns = [
    # orders
    path("buy/", views.buy, name="api-buy"),
    path("sell/", views.sell, name="api-sell"),
    path("orders/me/", views.my_orders, name="api-my-orders"),
    path("orders/<int:order_id>/cancel/", views.cancel_order, name="api-cancel-order"),

    # portfolio
    path("portfolio/", views.portfolio, name="api-portfolio"),

    # market data
    path("orderbook/<int:market_id>/", views.order_book, name="api-order-book"),
    path("trades/", views.trade_history, name="api-trade-history"),
    path("markets/<int:market_id>/trades/", views.market_trades, name="api-market-trades"),
]
