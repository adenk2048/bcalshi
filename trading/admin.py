from django.contrib import admin

from .models import Order, Position, Trade


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("user", "market", "shares")
    list_filter = ("market",)
    search_fields = ("user__username",)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("user", "market", "side", "price", "shares", "filled", "status", "created_at")
    list_filter = ("status", "side", "market")
    search_fields = ("user__username",)


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ("market", "buyer", "seller", "price", "shares", "created_at")
    list_filter = ("market",)
