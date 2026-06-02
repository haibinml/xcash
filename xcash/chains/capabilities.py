from __future__ import annotations

from chains.models import ChainType


class ChainProductCapabilityService:
    """集中维护链类型在各产品入口中的能力边界。"""

    INVOICE_RECIPIENT_CHAIN_TYPES = frozenset({ChainType.EVM, ChainType.TRON})
    DEPOSIT_CHAIN_TYPES = frozenset({ChainType.EVM})

    @classmethod
    def supports_existing_invoice_method(cls, *, chain, crypto) -> bool:
        """判断已存在 ChainCryptoDeployment 关系的链币组合是否可用于 Invoice。"""
        if chain.type not in cls.INVOICE_RECIPIENT_CHAIN_TYPES:
            return False
        # 支付按法币计价，必须有价格来源；无价格源的币（如未上 CoinGecko 的自定义代币）
        # 只能用于非支付资产流转，不进支付选项，否则建单时 to_fiat/to_crypto 会因缺价失败。
        if not crypto.is_payable():
            return False
        if chain.type == ChainType.TRON:
            return crypto.symbol == "USDT"
        return True

    @classmethod
    def supports_deposit_address(cls, *, chain, crypto) -> bool:
        return chain.type in cls.DEPOSIT_CHAIN_TYPES and crypto.support_this_chain(
            chain
        )
