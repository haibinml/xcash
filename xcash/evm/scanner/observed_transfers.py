from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog
from django.db import Error as DatabaseLayerError
from django.utils import timezone
from web3 import Web3

from chains.models import Chain
from chains.models import TxHash
from chains.service import MAX_TRANSFER_VALUE
from chains.service import ObservedTransferPayload
from chains.service import TransferService
from currencies.models import CryptoOnChain
from evm.scanner.constants import ERC20_TRANSFER_TOPIC0
from evm.scanner.constants import XCASH_NATIVE_RECEIVED_TOPIC0
from evm.scanner.rpc import EvmScannerRpcClient

logger = structlog.get_logger()


@dataclass(frozen=True)
class ParsedEvmTransferLog:
    """扫描器已验证可进入 Transfer 管线的一条外部入账日志。"""

    block_number: int
    block_hash: str
    tx_hash: str
    block_log_index: int | None
    from_address: str
    to_address: str
    crypto: Any
    value: Decimal
    amount: Decimal


class EvmObservedTransferProcessor:
    """处理 scanner 已解析出的外部入账事实：过滤与幂等落库。"""

    @classmethod
    def process(
        cls,
        *,
        chain: Chain,
        rpc_client: EvmScannerRpcClient,
        raw_logs: list[dict[str, Any]],
        token_registry: dict[str, CryptoOnChain],
        owned_addresses: frozenset[str],
    ) -> None:
        """解析外部入账日志并幂等落库。"""
        candidate_logs = [
            parsed
            for log in raw_logs
            if (
                parsed := cls._parse_log(
                    log=log,
                    chain=chain,
                    token_registry=token_registry,
                    owned_addresses=owned_addresses,
                )
            )
            is not None
        ]
        internal_tx_hashes = cls._known_internal_tx_hashes(
            chain=chain,
            logs=candidate_logs,
        )
        parsed_logs = [
            log for log in candidate_logs if log.tx_hash not in internal_tx_hashes
        ]
        cls._persist_logs(
            chain=chain,
            logs=parsed_logs,
            rpc_client=rpc_client,
        )

    @staticmethod
    def _known_internal_tx_hashes(
        *,
        chain: Chain,
        logs: list[ParsedEvmTransferLog],
    ) -> set[str]:
        """返回已登记 TxHash 的本系统主动交易 hash，scanner 必须整体跳过。"""
        tx_hashes = {log.tx_hash for log in logs}
        if not tx_hashes:
            return set()
        return set(
            TxHash.objects.filter(chain=chain, hash__in=tx_hashes).values_list(
                "hash",
                flat=True,
            )
        )

    @classmethod
    def _parse_log(
        cls,
        *,
        log: dict[str, Any],
        chain: Chain,
        token_registry: dict[str, CryptoOnChain],
        owned_addresses: frozenset[str],
    ) -> ParsedEvmTransferLog | None:
        """按 topic0 分派到原生币或 ERC20 解析；非入账日志返回 None。"""
        if log.get("removed"):
            return None
        topics = list(log.get("topics") or [])
        if not topics:
            return None

        topic0 = cls._normalize_hash(topics[0])
        if topic0 == XCASH_NATIVE_RECEIVED_TOPIC0.lower():
            return cls._parse_native_log(
                log=log, chain=chain, owned_addresses=owned_addresses
            )
        if topic0 == ERC20_TRANSFER_TOPIC0.lower():
            return cls._parse_erc20_log(
                log=log,
                chain=chain,
                token_registry=token_registry,
                owned_addresses=owned_addresses,
            )
        return None

    @classmethod
    def _parse_native_log(
        cls,
        *,
        log: dict[str, Any],
        chain: Chain,
        owned_addresses: frozenset[str],
    ) -> ParsedEvmTransferLog | None:
        """解析 VaultSlot 上的原生币入账事件，并过滤掉不在观察集中的 slot。"""
        topics = list(log.get("topics") or [])
        if len(topics) < 2:
            return None

        try:
            slot_address = Web3.to_checksum_address(str(log.get("address", "")))
            payer = cls._topic_to_address(topics[1])
            value = Decimal(int(cls._to_hex(log.get("data", "0x0")), 16))
            block_number = cls._parse_int(log["blockNumber"])
            block_hash = cls._normalize_required_hash(log["blockHash"])
            tx_hash = cls._normalize_required_hash(log["transactionHash"])
            block_log_index = cls._parse_optional_int(log.get("logIndex"))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            logger.warning(
                "EVM 原生币充值日志解析失败，已跳过",
                chain=chain.code,
                error=str(exc),
            )
            return None

        if value <= 0 or slot_address not in owned_addresses:
            return None
        if value > MAX_TRANSFER_VALUE:
            logger.warning(
                "EVM 原生币充值数值超过 Transfer.value 范围，已跳过",
                chain=chain.code,
                tx_hash=tx_hash,
                value=str(value),
            )
            return None
        if payer in owned_addresses:
            return None

        return ParsedEvmTransferLog(
            block_number=block_number,
            block_hash=block_hash,
            tx_hash=tx_hash,
            block_log_index=block_log_index,
            from_address=payer,
            to_address=slot_address,
            crypto=chain.native_coin,
            value=value,
            amount=value.scaleb(-chain.native_coin.get_decimals(chain)),
        )

    @classmethod
    def _parse_erc20_log(
        cls,
        *,
        log: dict[str, Any],
        chain: Chain,
        token_registry: dict[str, CryptoOnChain],
        owned_addresses: frozenset[str],
    ) -> ParsedEvmTransferLog | None:
        """解析 ERC20 Transfer 日志，仅保留外部地址打入系统观察地址的入账。"""
        topics = list(log.get("topics") or [])
        if len(topics) < 3:
            return None

        try:
            token_address = Web3.to_checksum_address(str(log.get("address", "")))
            token = token_registry.get(token_address)
            if token is None:
                return None

            from_address = cls._topic_to_address(topics[1])
            to_address = cls._topic_to_address(topics[2])
            # 只观察外部地址打入系统观察地址的入账事实；
            # 系统地址或 VaultSlot 发出的资产移动由 internal_tx receipt 路径收口。
            if to_address not in owned_addresses:
                return None
            if from_address in owned_addresses:
                return None

            raw_hex = cls._to_hex(log.get("data", "0x0"))
            if not raw_hex:
                return None
            value = Decimal(int(raw_hex, 16))
            block_number = cls._parse_int(log["blockNumber"])
            block_hash = cls._normalize_required_hash(log["blockHash"])
            tx_hash = cls._normalize_required_hash(log["transactionHash"])
            block_log_index = cls._parse_optional_int(log.get("logIndex"))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            logger.warning(
                "EVM ERC20 Transfer 日志解析失败，已跳过",
                chain=chain.code,
                error=str(exc),
            )
            return None

        if value <= 0:
            return None
        if value > MAX_TRANSFER_VALUE:
            logger.warning(
                "EVM ERC20 Transfer 数值超过 Transfer.value 范围，已跳过",
                chain=chain.code,
                tx_hash=tx_hash,
                block_log_index=block_log_index,
                value=str(value),
            )
            return None

        decimals = token.decimals
        return ParsedEvmTransferLog(
            block_number=block_number,
            block_hash=block_hash,
            tx_hash=tx_hash,
            block_log_index=block_log_index,
            from_address=from_address,
            to_address=to_address,
            crypto=token.crypto,
            value=value,
            amount=value.scaleb(-decimals),
        )

    @classmethod
    def _persist_logs(
        cls,
        *,
        chain: Chain,
        logs: list[ParsedEvmTransferLog],
        rpc_client: EvmScannerRpcClient,
    ) -> None:
        """逐条外部入账事件幂等落库。

        event_index 采用"同一交易内、按区块级 logIndex 升序的相对序号"，既不是
        直接用区块级 logIndex，也不再回查 receipt 取其数组下标：

        - 直接用区块级 logIndex 不安全：reorg 把交易重排到新区块的不同位置时
          logIndex 会变，(chain, hash, event_index) 唯一键随之改变，旧 Transfer 行
          不再被 reorg-drop 命中，同一笔充值会被当成新事件重复入账。
        - 交易内相对序号在 reorg 下不变：一笔交易自身的日志始终按发射顺序（即
          logIndex 升序）连续排列，其相对次序不随区块位置漂移，可稳定区分同一笔
          交易内的多条入账（如批量代付合约一笔交易向多个收款地址转账）。

        该序号可直接从本轮已拉取的日志计算，无需每条日志再回查一次 receipt，既省
        一次 RPC，也消除了"receipt 暂不可见 / logIndex 匹配不上即抛错中断整轮"这一
        单条坏日志卡死全链的风险。
        """
        ordinals = cls._intra_tx_event_indexes(logs=logs)
        timestamp_cache: dict[int, int] = {}

        for log in logs:
            event_index = ordinals.get((log.tx_hash, log.block_log_index))
            if event_index is None:
                # 已确认区块的日志必带 logIndex；缺失属异常数据，跳过单条而非中断
                # 整轮，避免一条坏日志拖垮全链扫描。
                logger.warning(
                    "EVM 入账日志缺少区块级 logIndex，无法稳定定位 event_index，已跳过",
                    chain=chain.code,
                    tx_hash=log.tx_hash,
                )
                continue

            timestamp = timestamp_cache.get(log.block_number)
            if timestamp is None:
                timestamp = rpc_client.get_block_timestamp(
                    block_number=log.block_number
                )
                timestamp_cache[log.block_number] = timestamp

            observed = ObservedTransferPayload(
                chain=chain,
                block=log.block_number,
                tx_hash=log.tx_hash,
                event_index=event_index,
                from_address=log.from_address,
                to_address=log.to_address,
                crypto=log.crypto,
                value=log.value,
                amount=log.amount,
                timestamp=timestamp,
                datetime=datetime.fromtimestamp(
                    timestamp,
                    tz=timezone.get_current_timezone(),
                ),
                block_hash=log.block_hash,
                source="evm-scan",
            )
            cls._persist_observed_transfer_safely(chain=chain, observed=observed)

    @staticmethod
    def _intra_tx_event_indexes(
        *, logs: list[ParsedEvmTransferLog]
    ) -> dict[tuple[str, int | None], int]:
        """按 tx_hash 分组，组内按区块级 logIndex 升序赋 0 基相对序号。

        返回 {(tx_hash, block_log_index): 序号}。缺少 block_log_index 的日志不参与
        排名（键无法命中，落库阶段按坏数据跳过）。
        """
        block_log_indexes_by_tx: dict[str, list[int]] = defaultdict(list)
        for log in logs:
            if log.block_log_index is not None:
                block_log_indexes_by_tx[log.tx_hash].append(log.block_log_index)

        event_indexes: dict[tuple[str, int | None], int] = {}
        for tx_hash, block_log_indexes in block_log_indexes_by_tx.items():
            for rank, block_log_index in enumerate(sorted(block_log_indexes)):
                event_indexes[(tx_hash, block_log_index)] = rank
        return event_indexes

    @staticmethod
    def _persist_observed_transfer_safely(
        *,
        chain: Chain,
        observed: ObservedTransferPayload,
    ) -> None:
        try:
            TransferService.create_observed_transfer(observed=observed)
        except DatabaseLayerError:
            # 数据库层异常多为暂时性故障（死锁被牺牲、连接抖动、超时），必须上抛，
            # 让本轮扫描中断、游标不推进，由下一轮重扫幂等恢复；
            # 在这里吞掉会推进游标，把真实入账事件永久静默丢弃。
            # 确定性脏数据（值超界 DataError、唯一键冲突 IntegrityError）已在
            # create_observed_transfer 内部用 savepoint 消化，不会传播到这里。
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "EVM 入账事件落库失败，已跳过",
                chain=chain.code,
                tx_hash=observed.tx_hash,
                event_index=observed.event_index,
                value=str(observed.value),
                amount=str(observed.amount),
                error=str(exc),
            )

    @staticmethod
    def _to_hex(value: Any) -> str:
        """提取原始十六进制字面（无 0x 前缀），兼容 bytes 与 str。"""
        if hasattr(value, "hex"):
            hex_value = value.hex()
        else:
            hex_value = str(value)
        return hex_value[2:] if hex_value.startswith("0x") else hex_value

    @classmethod
    def _normalize_hash(cls, value: object | None) -> str | None:
        """转成带 0x 前缀的小写哈希串，空值返回 None。"""
        if value is None:
            return None
        raw_hex = cls._to_hex(value)
        return f"0x{raw_hex.lower()}" if raw_hex else None

    @classmethod
    def _normalize_required_hash(cls, value: object) -> str:
        """要求哈希必填的归一化变体，空值直接抛错。"""
        normalized = cls._normalize_hash(value)
        if normalized is None:
            raise ValueError("hash is empty")
        return normalized

    @staticmethod
    def _parse_int(raw_value: Any) -> int:
        """兼容十进制 / 0x 十六进制 / int 的整数解析。"""
        if isinstance(raw_value, int):
            return raw_value
        value = str(raw_value).strip()
        if value.startswith(("0x", "0X")):
            return int(value, 16)
        return int(value) if value else 0

    @classmethod
    def _parse_optional_int(cls, raw_value: Any) -> int | None:
        if raw_value in (None, ""):
            return None
        return cls._parse_int(raw_value)

    @staticmethod
    def _normalize_address(value: Any) -> str | None:
        if value is None:
            return None
        try:
            return Web3.to_checksum_address(str(value))
        except ValueError:
            return None

    @staticmethod
    def _topic_to_address(topic: object) -> str:
        """从 32 字节 topic 取后 20 字节作为 checksum 地址。"""
        raw_hex = EvmObservedTransferProcessor._to_hex(topic)
        return Web3.to_checksum_address(f"0x{raw_hex[-40:]}")
