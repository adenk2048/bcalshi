import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from markets.models import Market
from trading.matching import try_match
from trading.models import Order, Position, Trade
from trading.settlement import resolve_market

START = Decimal("10000")


class TradingTestCase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pw")
        self.bob = User.objects.create_user("bob", password="pw")
        self.market = Market.objects.create(title="Will it rain tomorrow?")

    def place(self, user, side, price, shares):
        order = Order.objects.create(
            user=user,
            market=self.market,
            side=side,
            price=Decimal(price),
            shares=shares,
        )
        try_match(self.market)
        order.refresh_from_db()
        return order

    def profile(self, user):
        user.profile.refresh_from_db()
        return user.profile

    def shares(self, user):
        pos = Position.objects.filter(user=user, market=self.market).first()
        return pos.shares if pos else 0


class ShortSellingTests(TradingTestCase):
    def test_short_sale_locks_collateral_and_creates_supply(self):
        # Bob holds nothing and sells 10 @ 60c -> opens a short.
        self.place(self.bob, Order.SELL, "0.60", 10)
        self.place(self.alice, Order.BUY, "0.60", 10)

        # Alice: paid $6 for 10 long shares.
        self.assertEqual(self.profile(self.alice).balance, START - 6)
        self.assertEqual(self.shares(self.alice), 10)

        # Bob: received $6 premium, locked $10 collateral, short 10.
        bob = self.profile(self.bob)
        self.assertEqual(bob.balance, START + 6 - 10)
        self.assertEqual(bob.locked, Decimal("10"))
        self.assertEqual(self.shares(self.bob), -10)

        # Net shares across all users is always zero.
        self.assertEqual(self.shares(self.alice) + self.shares(self.bob), 0)

    def test_covering_releases_collateral(self):
        self.place(self.bob, Order.SELL, "0.60", 10)
        self.place(self.alice, Order.BUY, "0.60", 10)

        # Bob covers at 40c: shorted at 60c, covered at 40c -> $2 profit.
        self.place(self.alice, Order.SELL, "0.40", 10)
        self.place(self.bob, Order.BUY, "0.40", 10)

        bob = self.profile(self.bob)
        self.assertEqual(bob.balance, START + 2)
        self.assertEqual(bob.locked, Decimal("0"))
        self.assertEqual(self.shares(self.bob), 0)

        alice = self.profile(self.alice)
        self.assertEqual(alice.balance, START - 2)
        self.assertEqual(self.shares(self.alice), 0)

        # Cash is conserved.
        self.assertEqual(alice.balance + bob.balance, START * 2)

    def test_partial_fill_and_partial_short(self):
        # Alice first buys 5 long from Bob, then sells 8: 5 covered, 3 short.
        self.place(self.bob, Order.SELL, "0.50", 5)
        self.place(self.alice, Order.BUY, "0.50", 5)
        self.assertEqual(self.shares(self.alice), 5)

        self.place(self.alice, Order.SELL, "0.50", 8)
        self.place(self.bob, Order.BUY, "0.50", 8)

        self.assertEqual(self.shares(self.alice), -3)
        self.assertEqual(self.profile(self.alice).locked, Decimal("3"))


class MatchingTests(TradingTestCase):
    def test_no_self_match(self):
        sell = self.place(self.alice, Order.SELL, "0.50", 10)
        buy = self.place(self.alice, Order.BUY, "0.50", 10)

        self.assertEqual(Trade.objects.count(), 0)
        self.assertEqual(sell.status, Order.OPEN)
        buy.refresh_from_db()
        self.assertEqual(buy.status, Order.OPEN)
        self.assertEqual(self.profile(self.alice).balance, START)

    def test_resting_order_sets_price(self):
        # Resting sell at 40c, aggressive buy at 60c -> trades at 40c.
        self.place(self.bob, Order.SELL, "0.40", 10)
        self.place(self.alice, Order.BUY, "0.60", 10)
        self.assertEqual(Trade.objects.get().price, Decimal("0.40"))

        # Resting buy at 60c, aggressive sell at 40c -> trades at 60c.
        market2 = Market.objects.create(title="Second market")
        Order.objects.create(user=self.alice, market=market2, side=Order.BUY,
                             price=Decimal("0.60"), shares=10)
        Order.objects.create(user=self.bob, market=market2, side=Order.SELL,
                             price=Decimal("0.40"), shares=10)
        try_match(market2)
        self.assertEqual(Trade.objects.filter(market=market2).get().price, Decimal("0.60"))

    def test_unfunded_buyer_is_cancelled_not_crashed(self):
        broke = User.objects.create_user("broke", password="pw")
        broke.profile.balance = Decimal("1")
        broke.profile.save()

        # Bypass the view's optimistic check by creating the order directly.
        buy = Order.objects.create(user=broke, market=self.market,
                                   side=Order.BUY, price=Decimal("0.90"), shares=100)
        sell = self.place(self.bob, Order.SELL, "0.90", 100)

        buy.refresh_from_db()
        sell.refresh_from_db()
        self.assertEqual(buy.status, Order.CANCELLED)
        self.assertEqual(sell.status, Order.OPEN)  # stays in the book
        self.assertEqual(Trade.objects.count(), 0)
        self.assertEqual(self.profile(broke).balance, Decimal("1"))


class ResolutionTests(TradingTestCase):
    def setUp(self):
        super().setUp()
        # Alice long 10 @ 60c, Bob short 10.
        self.place(self.bob, Order.SELL, "0.60", 10)
        self.place(self.alice, Order.BUY, "0.60", 10)

    def test_resolve_yes_pays_longs_from_short_collateral(self):
        leftover = self.place(self.bob, Order.SELL, "0.90", 5)

        resolve_market(self.market, True)

        alice = self.profile(self.alice)
        bob = self.profile(self.bob)
        self.assertEqual(alice.balance, START - 6 + 10)  # paid $1/share
        self.assertEqual(bob.balance, START + 6 - 10)    # collateral forfeited
        self.assertEqual(bob.locked, Decimal("0"))
        self.assertEqual(alice.balance + bob.balance, START * 2)

        self.assertEqual(self.shares(self.alice), 0)
        self.assertEqual(self.shares(self.bob), 0)

        leftover.refresh_from_db()
        self.assertEqual(leftover.status, Order.CANCELLED)

        self.market.refresh_from_db()
        self.assertTrue(self.market.resolved)
        self.assertTrue(self.market.outcome)

    def test_resolve_no_returns_short_collateral(self):
        resolve_market(self.market, False)

        alice = self.profile(self.alice)
        bob = self.profile(self.bob)
        self.assertEqual(alice.balance, START - 6)      # shares expire worthless
        self.assertEqual(bob.balance, START + 6)        # keeps premium + collateral back
        self.assertEqual(bob.locked, Decimal("0"))
        self.assertEqual(alice.balance + bob.balance, START * 2)

    def test_cannot_resolve_twice(self):
        resolve_market(self.market, True)
        with self.assertRaises(ValueError):
            resolve_market(self.market, False)


class ApiTests(TradingTestCase):
    def post_json(self, url, body):
        return self.client.post(url, json.dumps(body), content_type="application/json")

    def test_sell_without_position_opens_short_via_api(self):
        self.client.login(username="bob", password="pw")
        res = self.post_json("/api/trading/sell/", {
            "market_id": self.market.id, "shares": 10, "price": 0.60,
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["opens_short"], 10)

    def test_sell_rejected_when_collateral_unaffordable(self):
        broke = User.objects.create_user("broke2", password="pw")
        broke.profile.balance = Decimal("1")
        broke.profile.save()

        self.client.login(username="broke2", password="pw")
        res = self.post_json("/api/trading/sell/", {
            "market_id": self.market.id, "shares": 100, "price": 0.50,
        })
        self.assertEqual(res.status_code, 400)

    def test_stacked_sells_classified_against_open_orders(self):
        # Alice holds 10; first sell of 10 is plain, second 10 is a short.
        self.place(self.bob, Order.SELL, "0.50", 10)
        self.place(self.alice, Order.BUY, "0.50", 10)

        self.client.login(username="alice", password="pw")
        first = self.post_json("/api/trading/sell/", {
            "market_id": self.market.id, "shares": 10, "price": 0.90,
        }).json()
        second = self.post_json("/api/trading/sell/", {
            "market_id": self.market.id, "shares": 10, "price": 0.90,
        }).json()
        self.assertEqual(first["opens_short"], 0)
        self.assertEqual(second["opens_short"], 10)

    def test_cancel_order(self):
        self.client.login(username="alice", password="pw")
        res = self.post_json("/api/trading/buy/", {
            "market_id": self.market.id, "shares": 5, "price": 0.30,
        })
        order_id = res.json()["order"]["id"]

        res = self.client.post(f"/api/trading/orders/{order_id}/cancel/")
        self.assertTrue(res.json()["success"])
        self.assertEqual(Order.objects.get(id=order_id).status, Order.CANCELLED)

        # Cancelling again fails cleanly.
        res = self.client.post(f"/api/trading/orders/{order_id}/cancel/")
        self.assertEqual(res.status_code, 400)

    def test_cannot_cancel_someone_elses_order(self):
        order = Order.objects.create(user=self.bob, market=self.market,
                                     side=Order.BUY, price=Decimal("0.50"), shares=5)
        self.client.login(username="alice", password="pw")
        res = self.client.post(f"/api/trading/orders/{order.id}/cancel/")
        self.assertEqual(res.status_code, 404)

    def test_trading_blocked_on_resolved_market(self):
        resolve_market(self.market, True)
        self.client.login(username="alice", password="pw")
        res = self.post_json("/api/trading/buy/", {
            "market_id": self.market.id, "shares": 5, "price": 0.50,
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("resolved", res.json()["error"])

    def test_price_validation(self):
        self.client.login(username="alice", password="pw")
        for bad_price in (0, 1, 1.5, -0.2, 0.505):
            res = self.post_json("/api/trading/buy/", {
                "market_id": self.market.id, "shares": 5, "price": bad_price,
            })
            self.assertEqual(res.status_code, 400, f"price {bad_price} should be rejected")

    def test_portfolio_api_shape(self):
        self.place(self.bob, Order.SELL, "0.60", 10)
        self.place(self.alice, Order.BUY, "0.60", 10)

        self.client.login(username="bob", password="pw")
        data = self.client.get("/api/trading/portfolio/").json()

        self.assertEqual(data["balance"], float(START + 6 - 10))
        self.assertEqual(data["locked"], 10.0)
        self.assertEqual(len(data["positions"]), 1)
        pos = data["positions"][0]
        self.assertEqual(pos["shares"], -10)
        self.assertEqual(pos["direction"], "SHORT")
        self.assertEqual(pos["last_price"], 0.60)

    def test_my_orders_includes_remaining(self):
        self.client.login(username="alice", password="pw")
        self.post_json("/api/trading/buy/", {
            "market_id": self.market.id, "shares": 7, "price": 0.20,
        })
        data = self.client.get("/api/trading/orders/me/").json()
        order = data["orders"][0]
        self.assertEqual(order["remaining"], 7)
        self.assertEqual(order["status"], "OPEN")
        self.assertIn("market_id", order)
