from django.db import models
from django.contrib.auth.models import User
from markets.models import Market


class Position(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    market = models.ForeignKey(Market, on_delete=models.CASCADE)
    # Positive = long, negative = short.
    shares = models.IntegerField(default=0)

    @property
    def is_short(self):
        return self.shares < 0

    def __str__(self):
        return f"{self.user} | {self.market} | {self.shares}"


class Order(models.Model):
    BUY = "BUY"
    SELL = "SELL"
    SIDE_CHOICES = [(BUY, "Buy"), (SELL, "Sell")]

    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    STATUS_CHOICES = [(OPEN, "Open"), (FILLED, "Filled"), (CANCELLED, "Cancelled")]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    market = models.ForeignKey(Market, on_delete=models.CASCADE)
    side = models.CharField(max_length=4, choices=SIDE_CHOICES)
    price = models.DecimalField(max_digits=6, decimal_places=4)
    shares = models.IntegerField()
    filled = models.IntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def remaining(self):
        return self.shares - self.filled

    def __str__(self):
        return f"{self.user} | {self.side} {self.shares}@{self.price} | {self.status}"


class Trade(models.Model):
    market = models.ForeignKey(Market, on_delete=models.CASCADE)
    buyer = models.ForeignKey(User, related_name="buy_trades", on_delete=models.CASCADE)
    seller = models.ForeignKey(User, related_name="sell_trades", on_delete=models.CASCADE)
    price = models.DecimalField(max_digits=6, decimal_places=4)
    shares = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.market} | {self.shares}@{self.price}"
