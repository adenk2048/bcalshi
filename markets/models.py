from django.conf import settings
from django.db import models
from django.utils import timezone


class Market(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    closes_at = models.DateTimeField(null=True, blank=True)

    resolved = models.BooleanField(default=False)

    outcome = models.BooleanField(null=True, blank=True)
    # True = YES won
    # False = NO won

    @property
    def is_closed(self):
        """Trading halted (close time passed) but not yet resolved."""
        return self.closes_at is not None and self.closes_at <= timezone.now()

    @property
    def is_tradable(self):
        return not self.resolved and not self.is_closed

    @property
    def status(self):
        if self.resolved:
            return "RESOLVED YES" if self.outcome else "RESOLVED NO"
        if self.is_closed:
            return "CLOSED"
        return "OPEN"

    def __str__(self):
        return self.title


class MarketSuggestion(models.Model):
    """A market idea submitted by a regular user, reviewed by the superaccount."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STATUS_CHOICES = [(PENDING, "Pending"), (APPROVED, "Approved"), (REJECTED, "Rejected")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    # Set when approved; survives as history even if the market is deleted.
    market = models.ForeignKey(Market, null=True, blank=True, on_delete=models.SET_NULL)
    # Optional reviewer note, mainly used to explain rejections.
    review_note = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.title} ({self.status})"
