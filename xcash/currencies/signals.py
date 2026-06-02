from django.db.models.signals import post_save
from django.dispatch import receiver

from chains.models import Chain
from currencies.models import ChainCryptoDeployment


@receiver(post_save, sender=Chain)
def ensure_native_crypto_mapping_for_chain(
    sender,
    instance: Chain,
    *,
    created: bool,
    **kwargs,
):
    # 新链落库后必须立即补齐原生币部署记录，保证 support_this_chain 等逻辑统一可用。
    if not created:
        return

    ChainCryptoDeployment.objects.get_or_create(
        crypto=instance.native_coin,
        chain=instance,
        defaults={
            "address": "",
            # 原生币精度以 ChainCryptoDeployment 为唯一真相，取自链的 ChainSpec。
            "decimals": instance.spec.native_coin_decimals,
        },
    )
