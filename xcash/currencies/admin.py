from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.decorators import display

from common.admin import ModelAdmin
from common.admin import TabularInline
from currencies.models import ChainCryptoDeployment
from currencies.models import Crypto
from currencies.models import Fiat


class ChainCryptoDeploymentInline(TabularInline):
    model = ChainCryptoDeployment
    extra = 0
    verbose_name = _("链上部署")
    verbose_name_plural = _("链上部署")
    fields = ("chain", "address", "decimals", "active")


@admin.register(Crypto)
class CryptoAdmin(ModelAdmin):
    inlines = (ChainCryptoDeploymentInline,)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .prefetch_related("chain_crypto_deployments__chain")
        )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return "symbol", "prices"
        return ()

    list_display = (
        "name",
        "symbol",
        "supported_chains",
        "display_type",
        "active",
    )
    list_filter = ("active", "is_native")

    @display(
        description="类型",
        label={
            "原生币": "warning",
            "代币": "info",
        },
    )
    def display_type(self, instance: Crypto):
        if instance.is_native:
            return "原生币"
        return "代币"


@admin.register(Fiat)
class FiatAdmin(ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ("code",)
        return ()

    list_display = (
        "code",
        "icon",
    )
