from __future__ import annotations

from web3 import Web3

from chains.models import AddressUsage
from chains.models import Chain
from chains.models import ChainType
from chains.models import TxTask
from chains.models import VaultSlot
from core.models import SystemWallet
from evm.adapter import EvmAdapter
from evm.constants import XCASH_VAULT_SLOT_FACTORY_ADDRESS
from evm.contracts_codec import predict_xcash_vault_slot_address
from evm.intents import build_vault_slot_collect_intent
from evm.intents import build_vault_slot_deploy_intent
from evm.models import EvmTxTask


def predict_address(*, vault: str, salt: bytes) -> str:
    return predict_xcash_vault_slot_address(vault=vault, salt=salt)


def is_deployed_on_chain(*, chain: Chain, address: str) -> bool:
    return EvmAdapter.is_contract(chain, address)


def create_deploy_tx_task(*, slot: VaultSlot) -> TxTask:
    sender = SystemWallet.get_current().wallet.get_address(
        chain_type=ChainType.EVM,
        usage=AddressUsage.HotWallet,
    )
    intent = build_vault_slot_deploy_intent(
        sender=sender,
        chain=slot.chain,
        factory_address=XCASH_VAULT_SLOT_FACTORY_ADDRESS,
        vault_address=Web3.to_checksum_address(slot.project.evm_vault),
        salt=bytes(slot.salt),
    )
    return EvmTxTask.schedule(intent).base_task


def create_collect_tx_task(*, chain: Chain, crypto, slot: VaultSlot) -> TxTask:
    # 归集前置闸门保证只有已部署的 slot 走到这里;未部署一律先走部署任务。
    if not slot.is_deployed:
        raise RuntimeError(f"VaultSlot {slot.pk} 尚未部署,不能创建归集任务")
    # 归集交易只把 VaultSlot 内的资金转给合约写死的 vault，collect() 无权限校验，
    # 调用方仅承担 gas。故与部署一样统一用系统热钱包，全局只需维护一个热钱包的 gas。
    sender = SystemWallet.get_current().wallet.get_address(
        chain_type=ChainType.EVM,
        usage=AddressUsage.HotWallet,
    )
    intent = build_vault_slot_collect_intent(
        sender=sender,
        chain=chain,
        slot_address=slot.address,
        token_address=crypto.address(chain),
    )
    # 不复用在途归集任务:归集计划 tx_task 是 OneToOne,复用同一任务会让第二个
    # 窗口撞唯一约束;collect(token) 是全额清扫,独立任务最多产生余额为 0 的空扫。
    return EvmTxTask.schedule(intent).base_task
