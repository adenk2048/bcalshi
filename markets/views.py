import json

from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from trading.models import Order, Position, Trade
from trading.settlement import resolve_market
from .models import Market, MarketSuggestion

MAX_PENDING_SUGGESTIONS = 5


def _is_market_admin(user):
    return user.is_authenticated and user.is_staff


market_admin_required = user_passes_test(_is_market_admin)


def _staff_api_guard(request):

    if not request.user.is_authenticated:
        return JsonResponse({"error": "login required"}, status=401)
    if not request.user.is_staff:
        return JsonResponse({"error": "superaccount required"}, status=403)
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    return None


# pages

def home_page(request):
    markets = Market.objects.all().order_by("resolved", "-created_at")

    cards = []
    for m in markets:
        last = Trade.objects.filter(market=m).order_by("-created_at").first()
        cards.append({"market": m, "last_price": last.price if last else None})

    return render(request, "home.html", {"cards": cards})


def market_page(request, market_id):
    market = get_object_or_404(Market, id=market_id)
    return render(request, "market.html", {"market": market})


@market_admin_required
def control_page(request):
    rows = []
    for m in Market.objects.all().order_by("resolved", "-created_at"):
        last = Trade.objects.filter(market=m).order_by("-created_at").first()
        open_orders = Order.objects.filter(market=m, status=Order.OPEN).count()
        open_interest = (
            Position.objects.filter(market=m, shares__gt=0)
            .aggregate(total=Sum("shares"))["total"]
            or 0
        )
        rows.append({
            "market": m,
            "last_price": last.price if last else None,
            "open_orders": open_orders,
            "open_interest": open_interest,
        })

    pending_suggestions = (
        MarketSuggestion.objects.filter(status=MarketSuggestion.PENDING)
        .select_related("user")
        .order_by("created_at")
    )
    reviewed_suggestions = (
        MarketSuggestion.objects.exclude(status=MarketSuggestion.PENDING)
        .select_related("user")
        .order_by("-reviewed_at")[:10]
    )

    # Accounts awaiting approval: signed up (inactive) and not staff.
    pending_users = (
        User.objects.filter(is_active=False, is_staff=False).order_by("date_joined")
    )

    return render(request, "control.html", {
        "rows": rows,
        "pending_suggestions": pending_suggestions,
        "reviewed_suggestions": reviewed_suggestions,
        "pending_users": pending_users,
    })


@login_required
def suggest_page(request):
    return render(request, "suggest.html")


# control APIs

def resolve_market_api(request, market_id):
    guard = _staff_api_guard(request)
    if guard:
        return guard

    market = get_object_or_404(Market, id=market_id)
    try:
        outcome = bool(json.loads(request.body)["outcome"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "body must include outcome: true|false"}, status=400)

    try:
        resolve_market(market, outcome)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse({
        "success": True,
        "market": market.title,
        "outcome": "YES" if outcome else "NO",
    })


#  suggestions

def _suggestion_payload(s):
    return {
        "id": s.id,
        "title": s.title,
        "description": s.description,
        "status": s.status,
        "created_at": s.created_at.isoformat(),
        "reviewed_at": s.reviewed_at.isoformat() if s.reviewed_at else None,
        "market_id": s.market_id,
        "review_note": s.review_note,
    }


@login_required
def create_suggestion(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid request body"}, status=400)

    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()

    if not title:
        return JsonResponse({"error": "title is required"}, status=400)
    if len(title) > 255:
        return JsonResponse({"error": "title must be 255 characters or fewer"}, status=400)

    pending = MarketSuggestion.objects.filter(
        user=request.user, status=MarketSuggestion.PENDING
    ).count()
    if pending >= MAX_PENDING_SUGGESTIONS:
        return JsonResponse(
            {"error": f"you already have {MAX_PENDING_SUGGESTIONS} pending suggestions — wait for a review"},
            status=400,
        )

    suggestion = MarketSuggestion.objects.create(
        user=request.user, title=title, description=description
    )
    return JsonResponse({"success": True, "suggestion": _suggestion_payload(suggestion)})


@login_required
def my_suggestions(request):
    suggestions = MarketSuggestion.objects.filter(user=request.user).order_by("-created_at")
    return JsonResponse({"suggestions": [_suggestion_payload(s) for s in suggestions]})


def review_suggestion(request, suggestion_id):
    guard = _staff_api_guard(request)
    if guard:
        return guard

    try:
        data = json.loads(request.body)
        action = data["action"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "body must include action: approve|reject"}, status=400)

    if action not in ("approve", "reject"):
        return JsonResponse({"error": "action must be approve or reject"}, status=400)

    note = (data.get("note") or "").strip()[:255]

    with transaction.atomic():
        suggestion = (
            MarketSuggestion.objects.select_for_update()
            .filter(id=suggestion_id)
            .first()
        )
        if suggestion is None:
            return JsonResponse({"error": "suggestion not found"}, status=404)
        if suggestion.status != MarketSuggestion.PENDING:
            return JsonResponse(
                {"error": f"suggestion is already {suggestion.status}"}, status=400
            )

        if action == "approve":
            market = Market.objects.create(
                title=suggestion.title, description=suggestion.description
            )
            suggestion.market = market
            suggestion.status = MarketSuggestion.APPROVED
        else:
            suggestion.status = MarketSuggestion.REJECTED

        suggestion.review_note = note
        suggestion.reviewed_at = timezone.now()
        suggestion.save()

    payload = {"success": True, "suggestion": _suggestion_payload(suggestion)}
    if suggestion.market_id:
        payload["market_id"] = suggestion.market_id
    return JsonResponse(payload)


def close_market_api(request, market_id):
    guard = _staff_api_guard(request)
    if guard:
        return guard

    market = get_object_or_404(Market, id=market_id)
    if market.resolved:
        return JsonResponse({"error": "market is already resolved"}, status=400)

    try:
        action = json.loads(request.body)["action"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "body must include action: close|reopen"}, status=400)

    if action == "close":
        market.closes_at = timezone.now()
    elif action == "reopen":
        market.closes_at = None
    else:
        return JsonResponse({"error": "action must be close or reopen"}, status=400)

    market.save()
    return JsonResponse({"success": True, "market": market.title, "status": market.status})


# APIs

def list_markets(request):
    markets = Market.objects.all().order_by("-created_at")

    data = [
        {
            "id": m.id,
            "title": m.title,
            "description": m.description,
            "resolved": m.resolved,
            "outcome": m.outcome,
        }
        for m in markets
    ]
    return JsonResponse({"markets": data})


def market_detail(request, market_id):
    market = get_object_or_404(Market, id=market_id)

    return JsonResponse({
        "id": market.id,
        "title": market.title,
        "description": market.description,
        "resolved": market.resolved,
        "outcome": market.outcome,
    })


@login_required
def market_positions(request, market_id):
    market = get_object_or_404(Market, id=market_id)
    positions = Position.objects.filter(market=market).exclude(shares=0)

    data = [
        {"username": p.user.username, "shares": p.shares}
        for p in positions
    ]
    return JsonResponse({"market": market.title, "positions": data})
