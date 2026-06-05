"""跨 app 复用的链构造器（测试用）。

active 链受 chain_active_requires_runtime_config 约束：EVM 必须有非空 rpc、Tron 必须有
非空 tron_api_key；且 Chain.save() 会对非空 rpc 触发远端 chain_id 校验。单元测试既不连
真实节点、也不想被约束挡住，故统一"先建 inactive、再用 update() 直接落库激活 + 占位
配置"，绕过 full_clean 的约束与 RPC 校验。
"""

from __future__ import annotations

from chains.constants import ChainCode
from chains.models import Chain
from currencies.models import Crypto


def make_evm_chain(
    *,
    code: str,
    chain_id: int | None = None,
    native_coin: Crypto | None = None,
    confirm_block_count: int = 6,
    rpc: str = "",
    latest_block_number: int = 0,
    evm_log_max_block_range: int | None = None,
    active: bool = True,
) -> Chain:
    # Chain 已收窄为 spec 驱动：chain_id / native_coin / confirm_block_count 全部由
    # ChainCode 常量推导，不再是可写字段，这里仅为兼容旧调用签名而保留并忽略。
    _ = (chain_id, native_coin, confirm_block_count)
    chain_code = code if code in ChainCode.values else ChainCode.Anvil
    chain = Chain.objects.create(
        code=chain_code,
        rpc="",
        active=False,
    )
    updates: dict[str, object] = {}
    if rpc:
        updates["rpc"] = rpc
    if active:
        updates.setdefault("rpc", "http://evm-test.invalid")
        updates["active"] = True
    if latest_block_number:
        updates["latest_block_number"] = latest_block_number
    if evm_log_max_block_range is not None:
        updates["evm_log_max_block_range"] = evm_log_max_block_range
    if updates:
        Chain.objects.filter(pk=chain.pk).update(**updates)
        chain.refresh_from_db()
    return chain


def make_tron_chain(
    *,
    code: str = ChainCode.Tron,
    tron_api_key: str = "test-tron-key",
    latest_block_number: int = 0,
    active: bool = True,
) -> Chain:
    chain = Chain.objects.create(code=code, active=False)
    updates: dict[str, object] = {}
    if active:
        updates["tron_api_key"] = tron_api_key
        updates["active"] = True
    if latest_block_number:
        updates["latest_block_number"] = latest_block_number
    if updates:
        Chain.objects.filter(pk=chain.pk).update(**updates)
        chain.refresh_from_db()
    return chain
