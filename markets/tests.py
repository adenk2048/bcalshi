import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from markets.models import Market, MarketSuggestion
from markets.views import MAX_PENDING_SUGGESTIONS
from trading.models import Order


class ControlAccessTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user("boss", password="pw", is_staff=True)
        self.pleb = User.objects.create_user("pleb", password="pw")
        self.market = Market.objects.create(title="Control test market")

    def post_json(self, url, body):
        return self.client.post(url, json.dumps(body), content_type="application/json")

    def test_control_page_requires_staff(self):
        res = self.client.get("/control/")
        self.assertEqual(res.status_code, 302)  # anonymous -> login redirect

        self.client.login(username="pleb", password="pw")
        res = self.client.get("/control/")
        self.assertEqual(res.status_code, 302)  # non-staff -> redirect

        self.client.login(username="boss", password="pw")
        res = self.client.get("/control/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Market Control")

    def test_resolve_endpoint_staff_only(self):
        self.client.login(username="pleb", password="pw")
        res = self.post_json(f"/api/markets/{self.market.id}/resolve/", {"outcome": True})
        self.assertEqual(res.status_code, 403)

        self.market.refresh_from_db()
        self.assertFalse(self.market.resolved)

    def test_resolve_endpoint_resolves(self):
        self.client.login(username="boss", password="pw")
        res = self.post_json(f"/api/markets/{self.market.id}/resolve/", {"outcome": False})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["outcome"], "NO")

        self.market.refresh_from_db()
        self.assertTrue(self.market.resolved)
        self.assertFalse(self.market.outcome)

        # Resolving again fails cleanly.
        res = self.post_json(f"/api/markets/{self.market.id}/resolve/", {"outcome": True})
        self.assertEqual(res.status_code, 400)


class CloseMarketTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user("boss", password="pw", is_staff=True)
        self.trader = User.objects.create_user("trader", password="pw")
        self.market = Market.objects.create(title="Closable market")

    def post_json(self, url, body):
        return self.client.post(url, json.dumps(body), content_type="application/json")

    def test_close_blocks_new_orders_and_reopen_restores(self):
        self.client.login(username="boss", password="pw")
        res = self.post_json(f"/api/markets/{self.market.id}/close/", {"action": "close"})
        self.assertEqual(res.json()["status"], "CLOSED")

        self.market.refresh_from_db()
        self.assertTrue(self.market.is_closed)
        self.assertFalse(self.market.is_tradable)

        # Trading is rejected while closed.
        self.client.login(username="trader", password="pw")
        res = self.post_json("/api/trading/buy/", {
            "market_id": self.market.id, "shares": 5, "price": 0.50,
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("closed", res.json()["error"])

        # Cancelling resting orders still works while closed.
        order = Order.objects.create(
            user=self.trader, market=self.market, side=Order.BUY,
            price=Decimal("0.40"), shares=5,
        )
        res = self.client.post(f"/api/trading/orders/{order.id}/cancel/")
        self.assertTrue(res.json()["success"])

        # Reopen restores trading.
        self.client.login(username="boss", password="pw")
        self.post_json(f"/api/markets/{self.market.id}/close/", {"action": "reopen"})
        self.client.login(username="trader", password="pw")
        res = self.post_json("/api/trading/buy/", {
            "market_id": self.market.id, "shares": 5, "price": 0.50,
        })
        self.assertEqual(res.status_code, 200)

    def test_close_staff_only(self):
        self.client.login(username="trader", password="pw")
        res = self.post_json(f"/api/markets/{self.market.id}/close/", {"action": "close"})
        self.assertEqual(res.status_code, 403)

    def test_cannot_close_resolved_market(self):
        self.market.resolved = True
        self.market.outcome = True
        self.market.save()

        self.client.login(username="boss", password="pw")
        res = self.post_json(f"/api/markets/{self.market.id}/close/", {"action": "close"})
        self.assertEqual(res.status_code, 400)

    def test_future_closes_at_still_tradable(self):
        self.market.closes_at = timezone.now() + timezone.timedelta(hours=1)
        self.market.save()
        self.assertFalse(self.market.is_closed)
        self.assertTrue(self.market.is_tradable)


class SuggestionTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user("boss", password="pw", is_staff=True)
        self.user = User.objects.create_user("dreamer", password="pw")

    def post_json(self, url, body):
        return self.client.post(url, json.dumps(body), content_type="application/json")

    def suggest(self, title="Will my team win?", description="Resolves YES if they win."):
        return self.post_json("/api/markets/suggestions/", {
            "title": title, "description": description,
        })

    def test_suggestion_requires_login(self):
        res = self.suggest()
        self.assertEqual(res.status_code, 302)  # redirected to login

    def test_create_and_list_suggestion(self):
        self.client.login(username="dreamer", password="pw")
        res = self.suggest()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["suggestion"]["status"], "PENDING")

        data = self.client.get("/api/markets/suggestions/me/").json()
        self.assertEqual(len(data["suggestions"]), 1)
        self.assertEqual(data["suggestions"][0]["title"], "Will my team win?")

    def test_blank_title_rejected(self):
        self.client.login(username="dreamer", password="pw")
        res = self.suggest(title="   ")
        self.assertEqual(res.status_code, 400)

    def test_pending_limit(self):
        self.client.login(username="dreamer", password="pw")
        for i in range(MAX_PENDING_SUGGESTIONS):
            self.assertEqual(self.suggest(title=f"Idea {i}").status_code, 200)
        res = self.suggest(title="One too many")
        self.assertEqual(res.status_code, 400)
        self.assertIn("pending", res.json()["error"])

        # A review frees up a slot.
        first = MarketSuggestion.objects.filter(user=self.user).first()
        first.status = MarketSuggestion.REJECTED
        first.save()
        self.assertEqual(self.suggest(title="Now it fits").status_code, 200)

    def test_review_requires_staff(self):
        self.client.login(username="dreamer", password="pw")
        s = MarketSuggestion.objects.create(user=self.user, title="Idea")
        res = self.post_json(f"/api/markets/suggestions/{s.id}/review/", {"action": "approve"})
        self.assertEqual(res.status_code, 403)
        s.refresh_from_db()
        self.assertEqual(s.status, MarketSuggestion.PENDING)

    def test_approve_creates_live_market(self):
        s = MarketSuggestion.objects.create(
            user=self.user, title="Approved idea", description="Some criteria."
        )
        self.client.login(username="boss", password="pw")
        res = self.post_json(f"/api/markets/suggestions/{s.id}/review/", {"action": "approve"})
        self.assertEqual(res.status_code, 200)

        s.refresh_from_db()
        self.assertEqual(s.status, MarketSuggestion.APPROVED)
        self.assertIsNotNone(s.reviewed_at)
        self.assertIsNotNone(s.market)
        self.assertEqual(s.market.title, "Approved idea")
        self.assertEqual(s.market.description, "Some criteria.")
        self.assertTrue(s.market.is_tradable)

    def test_reject_with_note(self):
        s = MarketSuggestion.objects.create(user=self.user, title="Vague idea")
        self.client.login(username="boss", password="pw")
        res = self.post_json(f"/api/markets/suggestions/{s.id}/review/", {
            "action": "reject", "note": "Too vague to resolve.",
        })
        self.assertEqual(res.status_code, 200)

        s.refresh_from_db()
        self.assertEqual(s.status, MarketSuggestion.REJECTED)
        self.assertEqual(s.review_note, "Too vague to resolve.")
        self.assertIsNone(s.market)
        self.assertEqual(Market.objects.filter(title="Vague idea").count(), 0)

        # The suggester sees the note.
        self.client.login(username="dreamer", password="pw")
        data = self.client.get("/api/markets/suggestions/me/").json()
        self.assertEqual(data["suggestions"][0]["review_note"], "Too vague to resolve.")

    def test_cannot_review_twice(self):
        s = MarketSuggestion.objects.create(user=self.user, title="Idea")
        self.client.login(username="boss", password="pw")
        self.post_json(f"/api/markets/suggestions/{s.id}/review/", {"action": "approve"})
        res = self.post_json(f"/api/markets/suggestions/{s.id}/review/", {"action": "reject"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Market.objects.filter(title="Idea").count(), 1)

    def test_control_page_shows_pending(self):
        MarketSuggestion.objects.create(user=self.user, title="Visible on control")
        self.client.login(username="boss", password="pw")
        res = self.client.get("/control/")
        self.assertContains(res, "Visible on control")
        self.assertContains(res, "Approve")
