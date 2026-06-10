from django.db import transaction

from markets.models import Market
from .models import Order, Trade
from .settlement import SettlementError, settle_trade


def try_match(market: Market):

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
                break  
            if buy.user_id == sell.user_id:
                continue  

            matched = min(buy.shares - buy.filled, sell.shares - sell.filled)
            if matched <= 0:
                continue

           
            sell_is_maker = (sell.created_at, sell.id) <= (buy.created_at, buy.id)
            price = sell.price if sell_is_maker else buy.price

            try:
                
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
                
                failed = buy if exc.side == Order.BUY else sell
                failed.status = Order.CANCELLED
                failed.save()
                if failed is buy:
                    break
