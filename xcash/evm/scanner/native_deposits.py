from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from typing import TypedDict

import structlog
from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone
from web3 import Web3

from chains.models import Chain
from chains.models import ChainType
from chains.models import Transfer
from chains.models import TransferStatus
from chains.service import ObservedTransferPayload
from chains.service import TransferService
from evm.models import EvmScanCursor
from evm.models import EvmScanCursorType
from evm.scanner.constants import DEFAULT_NATIVE_DEPOSIT_SCAN_BATCH_SIZE
from evm.scanner.constants import DEFAULT_NATIVE_DEPOSIT_SCAN_REPLAY_BLOCKS
from evm.scanner.constants import XCASH_NATIVE_DEPOSITED_TOPIC0
from evm.scanner.cursor import bootstrap_cursor_to_latest_for_debug
from evm.scanner.rpc import EvmScannerRpcClient
from evm.scanner.rpc import EvmScannerRpcError
from evm.scanner.watchers import EvmWatchSet
from evm.scanner.watchers import load_watch_set

logger = structlog.get_logger()


class ParsedNativeDepositLog(TypedDict):
    """描述一条已通过过滤的 DepositSlot 原生币充值事件。"""

    block_number: int
    block_hash: str | None
    tx_hash: str
    event_id: str
    from_address: str
    to_address: str
    value: Decimal
    amount: Decimal


@dataclass(frozen=True)
class EvmNativeDepositScanResult:
    """描述一次 DepositSlot 原生币充值事件扫描的结果。"""

    from_block: int
    to_block: int
    latest_block: int
    observed_logs: int
    created_transfers: int


class EvmNativeDepositScanner:
    """按链扫描 DepositSlot 合约发出的原生币充值事件。"""

    cursor_type = EvmScanCursorType.NATIVE_DEPOSIT

    @classmethod
    def scan_chain(
        cls,
        *,
        chain: Chain,
        batch_size: int = DEFAULT_NATIVE_DEPOSIT_SCAN_BATCH_SIZE,
        rpc_client: EvmScannerRpcClient | None = None,
    ) -> EvmNativeDepositScanResult:
        if chain.type != ChainType.EVM:
            raise ValueError(f"仅支持 EVM 链扫描，当前链为 {chain.code}")

        cursor = cls._get_or_create_cursor(chain=chain)
        if rpc_client is None:
            rpc_client = EvmScannerRpcClient(chain=chain)

        try:
            latest_block = rpc_client.get_latest_block_number()
            Chain.objects.filter(pk=chain.pk).update(
                latest_block_number=Greatest(F("latest_block_number"), latest_block)
            )
            cursor = bootstrap_cursor_to_latest_for_debug(
                cursor=cursor,
                latest_block=latest_block,
            )

            watch_set = load_watch_set(chain=chain)
            if not watch_set.watched_addresses:
                cls._advance_cursor(
                    cursor=cursor,
                    latest_block=latest_block,
                    scanned_to_block=latest_block,
                )
                return EvmNativeDepositScanResult(
                    from_block=0,
                    to_block=0,
                    latest_block=latest_block,
                    observed_logs=0,
                    created_transfers=0,
                )

            from_block, to_block = cls._compute_scan_window(
                cursor=cursor,
                latest_block=latest_block,
                batch_size=batch_size,
            )
            if from_block > to_block:
                cls._mark_cursor_idle(cursor=cursor, latest_block=latest_block)
                return EvmNativeDepositScanResult(
                    from_block=from_block,
                    to_block=to_block,
                    latest_block=latest_block,
                    observed_logs=0,
                    created_transfers=0,
                )

            logs, created_transfers = cls.scan_range_without_cursor(
                chain=chain,
                rpc_client=rpc_client,
                watch_set=watch_set,
                from_block=from_block,
                to_block=to_block,
            )
        except EvmScannerRpcError as exc:
            cls._mark_cursor_error(cursor=cursor, exc=exc)
            raise

        cls._advance_cursor(
            cursor=cursor,
            latest_block=latest_block,
            scanned_to_block=to_block,
        )
        return EvmNativeDepositScanResult(
            from_block=from_block,
            to_block=to_block,
            latest_block=latest_block,
            observed_logs=len(logs),
            created_transfers=created_transfers,
        )

    @classmethod
    def _get_or_create_cursor(cls, *, chain: Chain) -> EvmScanCursor:
        with transaction.atomic():
            cursor, _ = EvmScanCursor.objects.select_for_update().get_or_create(
                chain=chain,
                scanner_type=cls.cursor_type,
                defaults={
                    "last_scanned_block": 0,
                    "enabled": True,
                },
            )
        return cursor

    @staticmethod
    def _compute_scan_window(
        *,
        cursor: EvmScanCursor,
        latest_block: int,
        batch_size: int,
    ) -> tuple[int, int]:
        if latest_block <= 0:
            return 0, -1

        replay_blocks = DEFAULT_NATIVE_DEPOSIT_SCAN_REPLAY_BLOCKS
        if cursor.last_scanned_block <= 0:
            from_block = 1
        else:
            from_block = max(1, cursor.last_scanned_block + 1 - replay_blocks)

        forward_batch_size = max(1, batch_size)
        if cursor.last_scanned_block > 0:
            to_block = min(latest_block, cursor.last_scanned_block + forward_batch_size)
        else:
            to_block = min(latest_block, from_block + forward_batch_size - 1)
        return from_block, to_block

    @classmethod
    def scan_range_without_cursor(
        cls,
        *,
        chain: Chain,
        rpc_client: EvmScannerRpcClient,
        watch_set: EvmWatchSet,
        from_block: int,
        to_block: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """对 [from_block, to_block] 区间拉取 + 落库 native deposit 事件。"""
        if from_block > to_block or not watch_set.watched_addresses:
            return [], 0

        logs = rpc_client.get_logs(
            from_block=from_block,
            to_block=to_block,
            addresses=list(watch_set.watched_addresses),
            topic0=XCASH_NATIVE_DEPOSITED_TOPIC0,
            summary="获取原生币充值日志失败",
        )
        cls._drop_reorged_existing_native_transfers(
            chain=chain,
            rpc_client=rpc_client,
            from_block=from_block,
            to_block=to_block,
        )
        created = cls._persist_logs(
            chain=chain,
            logs=logs,
            rpc_client=rpc_client,
            watch_set=watch_set,
        )
        return logs, created

    @staticmethod
    def _drop_reorged_existing_native_transfers(
        *,
        chain: Chain,
        rpc_client: EvmScannerRpcClient,
        from_block: int,
        to_block: int,
    ) -> None:
        """只校验 replay 范围内已有 native 未确认记录所在块，避免整段逐块 RPC。"""
        existing_block_hashes: dict[int, set[str]] = {}
        rows = (
            Transfer.objects.filter(
                chain=chain,
                status=TransferStatus.CONFIRMING,
                event_id__startswith="native:",
                block__gte=from_block,
                block__lte=to_block,
                block_hash__isnull=False,
            )
            .values_list("block", "block_hash")
            .distinct()
        )
        for block_number, block_hash in rows:
            if block_hash:
                existing_block_hashes.setdefault(int(block_number), set()).add(
                    str(block_hash).lower()
                )

        for block_number, old_hashes in existing_block_hashes.items():
            current_hash = rpc_client.get_block_hash(block_number=block_number)
            if current_hash.lower() in old_hashes:
                continue
            TransferService.drop_reorged_unconfirmed_transfers(
                chain=chain,
                block=block_number,
                block_hash=current_hash,
            )

    @classmethod
    def _persist_logs(
        cls,
        *,
        chain: Chain,
        logs: list[dict[str, Any]],
        rpc_client: EvmScannerRpcClient,
        watch_set: EvmWatchSet,
    ) -> int:
        if not logs:
            return 0

        timestamp_cache: dict[int, int] = {}
        created_transfers = 0
        reorg_checked_blocks: set[tuple[int, str | None]] = set()

        for log in logs:
            parsed = cls._parse_log(log=log, chain=chain, watch_set=watch_set)
            if parsed is None:
                continue

            block_identity = (parsed["block_number"], parsed["block_hash"])
            if block_identity not in reorg_checked_blocks:
                TransferService.drop_reorged_unconfirmed_transfers(
                    chain=chain,
                    block=parsed["block_number"],
                    block_hash=parsed["block_hash"],
                )
                reorg_checked_blocks.add(block_identity)

            block_number = parsed["block_number"]
            timestamp = timestamp_cache.get(block_number)
            if timestamp is None:
                timestamp = rpc_client.get_block_timestamp(block_number=block_number)
                timestamp_cache[block_number] = timestamp

            observed = ObservedTransferPayload(
                chain=chain,
                block=block_number,
                tx_hash=parsed["tx_hash"],
                event_id=parsed["event_id"],
                from_address=parsed["from_address"],
                to_address=parsed["to_address"],
                crypto=chain.native_coin,
                value=parsed["value"],
                amount=parsed["amount"],
                timestamp=timestamp,
                occurred_at=datetime.fromtimestamp(
                    timestamp,
                    tz=timezone.get_current_timezone(),
                ),
                block_hash=parsed["block_hash"],
                source="evm-scan",
            )
            result = TransferService.create_observed_transfer(observed=observed)
            if result.created:
                created_transfers += 1

        return created_transfers

    @classmethod
    def _parse_log(
        cls,
        *,
        log: dict[str, Any],
        chain: Chain,
        watch_set: EvmWatchSet,
    ) -> ParsedNativeDepositLog | None:
        if log.get("removed"):
            return None

        topics = list(log.get("topics") or [])
        if len(topics) < 2:
            return None

        try:
            slot_address = Web3.to_checksum_address(str(log.get("address", "")))
            payer = cls._topic_to_address(topics[1])
            raw_hex = cls._to_hex(log.get("data", "0x0"))
            if not raw_hex:
                return None
            value = Decimal(int(raw_hex, 16))
            if value <= 0:
                return None
            block_number = int(log["blockNumber"])
            block_hash = cls._normalize_hash(log.get("blockHash"))
            tx_hash = f"0x{cls._to_hex(log['transactionHash']).lower()}"
            log_index = cls._parse_int(log.get("logIndex", 0))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            logger.warning(
                "EVM 原生币充值日志解析失败，已跳过",
                chain=chain.code,
                error=str(exc),
            )
            return None

        if slot_address not in watch_set.watched_addresses:
            return None

        return {
            "block_number": block_number,
            "block_hash": block_hash,
            "tx_hash": tx_hash,
            "event_id": f"native:{log_index}",
            "from_address": payer,
            "to_address": slot_address,
            "value": value,
            "amount": Decimal(value).scaleb(-chain.native_coin.decimals),
        }

    @staticmethod
    def _topic_to_address(topic: object) -> str:
        raw_hex = EvmNativeDepositScanner._to_hex(topic)
        return Web3.to_checksum_address(f"0x{raw_hex[-40:]}")

    @staticmethod
    def _to_hex(value: object) -> str:
        if hasattr(value, "hex"):
            hex_value = value.hex()
        else:
            hex_value = str(value)
        return hex_value[2:] if hex_value.startswith("0x") else hex_value

    @staticmethod
    def _normalize_hash(value: object | None) -> str | None:
        if value is None:
            return None
        raw_hex = EvmNativeDepositScanner._to_hex(value)
        return f"0x{raw_hex.lower()}" if raw_hex else None

    @staticmethod
    def _parse_int(raw_value: object) -> int:
        if isinstance(raw_value, int):
            return raw_value
        value = str(raw_value).strip()
        if value.startswith(("0x", "0X")):
            return int(value, 16)
        return int(value) if value else 0

    @staticmethod
    def _mark_cursor_idle(*, cursor: EvmScanCursor, latest_block: int) -> None:
        del latest_block
        EvmScanCursor.objects.filter(pk=cursor.pk).update(
            last_error="",
            last_error_at=None,
            updated_at=timezone.now(),
        )

    @staticmethod
    def _advance_cursor(
        *,
        cursor: EvmScanCursor,
        latest_block: int,
        scanned_to_block: int,
    ) -> None:
        del latest_block
        EvmScanCursor.objects.filter(pk=cursor.pk).update(
            last_scanned_block=Greatest(F("last_scanned_block"), scanned_to_block),
            last_error="",
            last_error_at=None,
            updated_at=timezone.now(),
        )

    @staticmethod
    def _mark_cursor_error(*, cursor: EvmScanCursor, exc: Exception) -> None:
        logger.warning(
            "EVM 原生币充值扫描失败",
            chain=cursor.chain.code,
            scanner_type=cursor.scanner_type,
            error=str(exc),
        )
        EvmScanCursor.objects.filter(pk=cursor.pk).update(
            last_error=str(exc),
            last_error_at=timezone.now(),
            updated_at=timezone.now(),
        )
