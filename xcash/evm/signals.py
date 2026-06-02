from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_delete
from django.db.models.signals import post_save
from django.dispatch import receiver

from chains.constants import ChainType
from currencies.models import ChainCryptoDeployment
from currencies.models import Crypto
from evm.scanner.watchers import clear_evm_chain_crypto_deployments_cache
from evm.scanner.watchers import load_watch_set


def _refresh_evm_chain_crypto_deployments_on_commit(
    *, chain_crypto_deployment: ChainCryptoDeployment
) -> None:
    chain = chain_crypto_deployment.chain
    if chain.type != ChainType.EVM:
        return
    clear_evm_chain_crypto_deployments_cache(chain=chain)
    transaction.on_commit(lambda: load_watch_set(chain=chain, refresh=True))


def _refresh_crypto_chain_crypto_deployments_on_commit(*, crypto: Crypto) -> None:
    chains = [
        chain_crypto_deployment.chain
        for chain_crypto_deployment in (
            ChainCryptoDeployment.objects.select_related("chain").filter(
                crypto=crypto,
                chain__type=ChainType.EVM,
            )
        )
    ]
    for chain in chains:
        clear_evm_chain_crypto_deployments_cache(chain=chain)

    def refresh_chain_watch_sets() -> None:
        for chain in chains:
            load_watch_set(chain=chain, refresh=True)

    transaction.on_commit(refresh_chain_watch_sets)


@receiver(post_save, sender=ChainCryptoDeployment)
@receiver(post_delete, sender=ChainCryptoDeployment)
def refresh_watch_set_when_chain_crypto_deployment_changes(
    sender,
    instance: ChainCryptoDeployment,
    **kwargs,
):
    _refresh_evm_chain_crypto_deployments_on_commit(chain_crypto_deployment=instance)


@receiver(post_save, sender=Crypto)
def refresh_watch_set_when_crypto_changes(sender, instance: Crypto, **kwargs):
    _refresh_crypto_chain_crypto_deployments_on_commit(crypto=instance)
