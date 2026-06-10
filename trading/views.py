import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from markets.models import Market
from users.models import ensure_profile
from .matching import try_match
from .models import Order, Position, Trade
from .settlement import PAYOUT


#  pages

@login_required
def portfolio_page(request):
    return render(request, "portfolio.html")


@login_required
def orders_page(request):
    return render(request, "orders.html")


@login_required
def trades_page(request):
    return render(request, "trades.html")


#  helpers

def _parse_order(request):
    """Validate an order payload. Returns (market, shares, price, error)."""
    if request.method != "POST":
        return None, None, None, JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
        market_id = int(data["market_id"])
        shares = int(data["shares"])
        price = Decimal(str(data["price"]))
    except (json.JSONDecodeError, KeyError, ValueError, TypeError, InvalidOperation):
        return None, None, None, JsonResponse({"error": "invalid request body"}, status=400)

    if shares <= 0:
        return None, None, None, JsonResponse({"error": "shares must be positive"}, status=400)
    if not (Decimal("0.01") <= price <= Decimal("0.99")):
        return None, None, None, JsonResponse({"error": "price must be 0.01-0.99"}, status=400)
    if price != price.quantize(Decimal("0.01")):
        return None, None, None, JsonResponse({"error": "price must be in 1¢ increments"}, status=400)

    market = Market.objects.filter(id=market_id).first()
    if market is None:
        return None, None, None, JsonResponse({"error": "market not found"}, status=404)
    if market.resolved:
        return None, None, None, JsonResponse({"error": "market is resolved"}, status=400)
    if market.is_closed:
        return None, None, None, JsonResponse({"error": "market is closed to trading"}, status=400)

    return market, shares, price, None


def _held_shares(user, market):
    position = Position.objects.filter(user=user, market=market).first()
    return position.shares if position else 0


def _open_remaining(user, market, side):
    """Total unfilled shares on the user's other open orders in this market."""
    total = (
        Order.objects.filter(user=user, market=market, side=side, status=Order.OPEN)
        .aggregate(total=Sum(F("shares") - F("filled")))["total"]
    )
    return total or 0


def _last_price(market):
    last = Trade.objects.filter(market=market).order_by("-created_at").first()
    return float(last.price) if last else None


def _order_payload(order):
    return {
        "id": order.id,
        "market_id": order.market_id,
        "market": order.market.title,
        "side": order.side,
        "price": float(order.price),
        "shares": order.shares,
        "filled": order.filled,
        "remaining": order.remaining,
        "status": order.status,
        "created_at": order.created_at.isoformat(),
    }


#  orders

@login_required
def buy(request):
    market, shares, price, error = _parse_order(request)
    if error:
        return error

    # Optimistic affordability check — settlement is the authoritative,
    # atomic check. Buying while short releases $1/share of collateral
    # for every covered share, so covering costs less than it looks.
    held = _held_shares(request.user, market)
    covering = min(shares, max(0, -held))
    worst_case_cost = price * shares - PAYOUT * covering
    if ensure_profile(request.user).balance < worst_case_cost:
        return JsonResponse({"error": "insufficient balance"}, status=400)

    order = Order.objects.create(
        user=request.user,
        market=market,
        side=Order.BUY,
        price=price,
        shares=shares,
    )

    try_match(market)

    order.refresh_from_db()
    return JsonResponse({
        "success": True,
        "order": _order_payload(order),
        "covers_short": covering,
    })


@login_required
def sell(request):
    market, shares, price, error = _parse_order(request)
    if error:
        return error

    # Selling more than you hold opens a short. Count other open sell
    # orders too, so stacked sells are classified honestly.
    held = _held_shares(request.user, market)
    already_committed = _open_remaining(request.user, market, Order.SELL)
    available_long = max(0, held - already_committed)
    opens_short = max(0, shares - available_long)

    # Optimistic collateral check: a short costs (1 - price) per share net
    # (you receive the premium but lock $1). Fills can only happen at or
    # above the limit price, so this is the worst case.
    collateral_needed = (PAYOUT - price) * opens_short
    if ensure_profile(request.user).balance < collateral_needed:
        return JsonResponse(
            {"error": f"insufficient balance for short collateral (need ${collateral_needed})"},
            status=400,
        )

    order = Order.objects.create(
        user=request.user,
        market=market,
        side=Order.SELL,
        price=price,
        shares=shares,
    )

    try_match(market)

    order.refresh_from_db()
    return JsonResponse({
        "success": True,
        "order": _order_payload(order),
        "opens_short": opens_short,
    })


@login_required
def cancel_order(request, order_id):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .filter(id=order_id, user=request.user)
            .first()
        )
        if order is None:
            return JsonResponse({"error": "order not found"}, status=404)
        if order.status != Order.OPEN:
            return JsonResponse({"error": f"order is {order.status}, not open"}, status=400)

        order.status = Order.CANCELLED
        order.save()

    return JsonResponse({"success": True, "order": _order_payload(order)})


@login_required
def my_orders(request):
    orders = (
        Order.objects.filter(user=request.user)
        .select_related("market")
        .order_by("-created_at")
    )
    return JsonResponse({"orders": [_order_payload(o) for o in orders]})


#  portfolio

@login_required
def portfolio(request):
    positions = (
        Position.objects.filter(user=request.user)
        .exclude(shares=0)
        .select_related("market")
    )

    data = [
        {
            "market_id": p.market.id,
            "market_title": p.market.title,
            "shares": p.shares,
            "direction": "SHORT" if p.is_short else "LONG",
            "last_price": _last_price(p.market),
            "resolved": p.market.resolved,
        }
        for p in positions
    ]

    profile = ensure_profile(request.user)
    return JsonResponse({
        "balance": float(profile.balance),
        "locked": float(profile.locked),
        "positions": data,
    })


#  market data

@login_required
def order_book(request, market_id):
    market = get_object_or_404(Market, id=market_id)

    bid_levels = defaultdict(int)
    ask_levels = defaultdict(int)
    open_orders = Order.objects.filter(market=market, status=Order.OPEN)
    for o in open_orders:
        if o.remaining <= 0:
            continue
        levels = bid_levels if o.side == Order.BUY else ask_levels
        levels[o.price] += o.remaining

    bids = [
        {"price": float(p), "shares": s}
        for p, s in sorted(bid_levels.items(), reverse=True)
    ]
    asks = [
        {"price": float(p), "shares": s}
        for p, s in sorted(ask_levels.items())
    ]
    return JsonResponse({"market": market.title, "bids": bids, "asks": asks})


@login_required
def trade_history(request):
    trades = (
        Trade.objects.filter(buyer=request.user) | Trade.objects.filter(seller=request.user)
    ).select_related("market", "buyer", "seller").order_by("-created_at")

    data = [
        {
            "market_id": t.market_id,
            "market": t.market.title,
            "price": float(t.price),
            "shares": t.shares,
            "buyer": t.buyer.username,
            "seller": t.seller.username,
            "side": "BUY" if t.buyer == request.user else "SELL",
            "created_at": t.created_at.isoformat(),
        }
        for t in trades
    ]
    return JsonResponse({"trades": data})


def market_trades(request, market_id):
    trades = (
        Trade.objects.filter(market_id=market_id)
        .select_related("buyer", "seller")
        .order_by("-created_at")[:50]
    )
    return JsonResponse({
        "trades": [
            {
                "id": t.id,
                "price": str(t.price),
                "shares": t.shares,
                "buyer": t.buyer.username,
                "seller": t.seller.username,
                "created_at": t.created_at.isoformat(),
            }
            for t in trades
        ]
    })
