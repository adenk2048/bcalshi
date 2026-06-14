from django.contrib.auth.models import User
from django.test import TestCase


class SignupApprovalTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user("boss", password="pw", is_staff=True)

    def test_signup_creates_inactive_user(self):
        res = self.client.post("/accounts/signup/", {
            "username": "newbie",
            "password1": "Trader-2026-xyz",
            "password2": "Trader-2026-xyz",
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Request Received")

        user = User.objects.get(username="newbie")
        self.assertFalse(user.is_active)
        # Not auto-logged-in.
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_user_cannot_log_in(self):
        User.objects.create_user("pending", password="pw", is_active=False)
        res = self.client.post(
            "/api/users/login/",
            {"username": "pending", "password": "pw"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)

    def test_approve_then_login_works(self):
        pending = User.objects.create_user("pending", password="pw", is_active=False)

        self.client.login(username="boss", password="pw")
        res = self.client.post(f"/api/users/{pending.id}/approve/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "approved")

        pending.refresh_from_db()
        self.assertTrue(pending.is_active)

        # Now login succeeds.
        self.client.logout()
        res = self.client.post(
            "/api/users/login/",
            {"username": "pending", "password": "pw"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)

    def test_reject_deletes_pending_user(self):
        pending = User.objects.create_user("pending", password="pw", is_active=False)

        self.client.login(username="boss", password="pw")
        res = self.client.post(f"/api/users/{pending.id}/reject/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(User.objects.filter(username="pending").exists())

    def test_approval_endpoints_are_staff_only(self):
        pending = User.objects.create_user("pending", password="pw", is_active=False)
        User.objects.create_user("other", password="pw")  # active, non-staff

        self.client.login(username="other", password="pw")
        self.assertEqual(self.client.post(f"/api/users/{pending.id}/approve/").status_code, 403)
        self.assertEqual(self.client.post(f"/api/users/{pending.id}/reject/").status_code, 403)

        pending.refresh_from_db()
        self.assertFalse(pending.is_active)  # untouched

    def test_cannot_reject_an_approved_member(self):
        member = User.objects.create_user("member", password="pw")  # active
        self.client.login(username="boss", password="pw")
        res = self.client.post(f"/api/users/{member.id}/reject/")
        self.assertEqual(res.status_code, 400)
        self.assertTrue(User.objects.filter(username="member").exists())

    def test_cannot_delete_staff_account(self):
        victim = User.objects.create_user("admin2", password="pw", is_staff=True, is_active=False)
        self.client.login(username="boss", password="pw")
        res = self.client.post(f"/api/users/{victim.id}/reject/")
        self.assertEqual(res.status_code, 400)
        self.assertTrue(User.objects.filter(username="admin2").exists())

    def test_control_page_lists_pending_accounts(self):
        User.objects.create_user("waiting_guy", password="pw", is_active=False)
        self.client.login(username="boss", password="pw")
        res = self.client.get("/control/")
        self.assertContains(res, "Pending Accounts")
        self.assertContains(res, "waiting_guy")
