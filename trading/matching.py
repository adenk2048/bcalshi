from django.db import transaction

from markets.models import Market
from .models import Order, Trade
from .settlement import SettlementError, settle_trade


def try_match(market: Market):
    """Cross open orders for a market using price-time priority.

    - The resting (earlier) order sets the trade price.
    - A user's orders never match each other.
    - An order whose owner can't fund settlement is cancelled and matching
      continues with the rest of the book.
    """
    buys = list(
        Order.objects.filter(market=market, side=Order.BUY, status=Order.OPEN)
        .order_by("-price", "created_at", "id")
    )
    sells = list(
        Order.objects.filter(market=market, side=Order.SELL, status=Order.OPEN)
        .order_by("price", "created_at", "id")
    )

    for buy in buys:
        if buy.status != Order.OPEN:
            continue

        for sell in sells:
            if buy.status != Order.OPEN:
                break
            if sell.status != Order.OPEN:
                continue
            if buy.price < sell.price:
                break  # sells are sorted ascending; nothing further crosses
            if buy.user_id == sell.user_id:
                continue  # no self-trading

            matched = min(buy.shares - buy.filled, sell.shares - sell.filled)
            if matched <= 0:
                continue

            # Price-time priority: the order that was resting in the book
            # (the earlier one) sets the execution price. Timestamps can tie
            # within clock resolution, so order id breaks ties.
            sell_is_maker = (sell.created_at, sell.id) <= (buy.created_at, buy.id)
            price = sell.price if sell_is_maker else buy.price

            try:
                # Each match is fully atomic: if settlement fails, the Trade
                # row and all order/position updates roll back together.
                with transaction.atomic():
                    trade = Trade.objects.create(
                        buyer=buy.user,
                        seller=sell.user,
                        market=market,
                        price=price,
                        shares=matched,
                    )

                    settle_trade(trade)

                    buy.filled += matched
                    sell.filled += matched

                    if buy.filled >= buy.shares:
                        buy.status = Order.FILLED
                    if sell.filled >= sell.shares:
                        sell.status = Order.FILLED

                    buy.save()
                    sell.save()
            except SettlementError as exc:
                # Cancel the order whose owner couldn't pay, keep matching.
                failed = buy if exc.side == Order.BUY else sell
                failed.status = Order.CANCELLED
                failed.save()
                if failed is buy:
                    break
