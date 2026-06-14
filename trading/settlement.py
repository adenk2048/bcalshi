from decimal import Decimal

from django.db import transaction

from markets.models import Market
from trading.models import Order, Position
from users.models import Profile, ensure_profile

# const, represents the final value of a share
PAYOUT = Decimal("1")


class SettlementError(Exception):

    def __init__(self, side, message):
        self.side = side
        super().__init__(message)


def settle_trade(trade):

    buyer = trade.buyer
    seller = trade.seller
    market = trade.market
    shares = trade.shares
    price = Decimal(str(trade.price))
    total = price * shares

    if buyer.id == seller.id:
        raise SettlementError(Order.BUY, "self-trades are not allowed")

    with transaction.atomic():

        ensure_profile(buyer)
        ensure_profile(seller)

        profiles = {
            p.user_id: p
            for p in Profile.objects.select_for_update()
            .filter(user_id__in=[buyer.id, seller.id])
            .order_by("user_id")
        }
        buyer_profile = profiles[buyer.id]
        seller_profile = profiles[seller.id]

        buyer_pos, _ = Position.objects.select_for_update().get_or_create(
            user=buyer, market=market, defaults={"shares": 0}
        )
        seller_pos, _ = Position.objects.select_for_update().get_or_create(
            user=seller, market=market, defaults={"shares": 0}
        )

        # Shares sold beyond what the seller holds open a short.
        short_opened = max(0, shares - max(seller_pos.shares, 0))
        collateral_locked = PAYOUT * short_opened

        # Shares bought while short close the short out.
        short_covered = min(shares, max(-buyer_pos.shares, 0))
        collateral_released = PAYOUT * short_covered

        buyer_balance = buyer_profile.balance - total + collateral_released
        if buyer_balance < 0:
            raise SettlementError(
                Order.BUY, f"{buyer.username} cannot fund ${total} purchase"
            )

        seller_balance = seller_profile.balance + total - collateral_locked
        if seller_balance < 0:
            raise SettlementError(
                Order.SELL,
                f"{seller.username} cannot post ${collateral_locked} short collateral",
            )

        buyer_profile.balance = buyer_balance
        buyer_profile.locked -= collateral_released
        seller_profile.balance = seller_balance
        seller_profile.locked += collateral_locked
        buyer_profile.save()
        seller_profile.save()

        buyer_pos.shares += shares
        seller_pos.shares -= shares
        buyer_pos.save()
        seller_pos.save()


def resolve_market(market, outcome):

    with transaction.atomic():
        market = Market.objects.select_for_update().get(pk=market.pk)
        if market.resolved:
            raise ValueError(f"{market.title} is already resolved")

        Order.objects.filter(market=market, status=Order.OPEN).update(
            status=Order.CANCELLED
        )

        positions = (
            Position.objects.select_for_update()
            .filter(market=market)
            .exclude(shares=0)
        )
        for pos in positions:
            ensure_profile(pos.user)
            profile = Profile.objects.select_for_update().get(user=pos.user)
            if pos.shares > 0:
                if outcome:
                    profile.balance += PAYOUT * pos.shares
            else:
                collateral = PAYOUT * (-pos.shares)
                profile.locked -= collateral
                if not outcome:
                    profile.balance += collateral
            profile.save()
            pos.shares = 0
            pos.save()

        market.resolved = True
        market.outcome = outcome
        market.save()
