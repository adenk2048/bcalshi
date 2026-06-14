from django.db import models
from django.contrib.auth.models import User

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=10000)
    #collateral
    locked = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.user.username} | ${self.balance} (+${self.locked} locked)"


def ensure_profile(user):

    profile, _ = Profile.objects.get_or_create(user=user)
    return profile
