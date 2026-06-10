from django.contrib import admin, messages

from trading.settlement import resolve_market
from .models import Market, MarketSuggestion


@admin.register(MarketSuggestion)
class MarketSuggestionAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "status", "created_at", "reviewed_at")
    list_filter = ("status",)
    search_fields = ("title", "user__username")


@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = ("title", "resolved", "outcome", "created_at", "closes_at")
    list_filter = ("resolved",)
    actions = ("resolve_yes", "resolve_no")

    def _resolve(self, request, queryset, outcome):
        label = "YES" if outcome else "NO"
        for market in queryset:
            try:
                resolve_market(market, outcome)
                self.message_user(request, f"Resolved {label}: {market.title}")
            except ValueError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)

    @admin.action(description="Resolve selected markets YES (longs paid $1/share)")
    def resolve_yes(self, request, queryset):
        self._resolve(request, queryset, True)

    @admin.action(description="Resolve selected markets NO (shorts keep premium)")
    def resolve_no(self, request, queryset):
        self._resolve(request, queryset, False)
