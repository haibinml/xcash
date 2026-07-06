from __future__ import annotations

from collections import defaultdict

from django.contrib import admin
from django.contrib import messages
from django.db import transaction
from django.utils import timezone


class SyncScanCursorToLatestActionMixin:
    """为扫描游标后台提供“追平到最新区块”批量动作。"""

    def get_sync_latest_block(self, *, chain) -> int:
        return chain.latest_block_number

    def has_sync_scan_cursor_permission(self, request) -> bool:
        # 启停/追平扫描游标直接改动资金入账的扫描位点：暂停会停止充值/归集确认入账，
        # 「追平到最新区块」会把 last_scanned_block 直接跳到链头、跳过区间内的充值永久
        # 漏账（游标单调前进、无回补机制）。属系统级治理操作，收口到超管，不能靠 view
        # 只读权限放行给审计员，与 chains.requeue / SystemSettings 口径一致。
        return bool(request.user.is_active and request.user.is_superuser)

    @admin.action(
        description="启用所选扫描游标",
        permissions=["sync_scan_cursor"],
    )
    def enable_selected_scanners(self, request, queryset) -> None:
        selected_ids = list(queryset.values_list("pk", flat=True))
        if not selected_ids:
            self.message_user(request, "未选中任何扫描游标", level=messages.WARNING)
            return

        updated_count = queryset.model.objects.filter(pk__in=selected_ids).update(
            enabled=True
        )
        self.message_user(
            request,
            f"已启用 {updated_count} 个扫描游标",
            level=messages.SUCCESS,
        )

    @admin.action(
        description="暂停所选扫描游标",
        permissions=["sync_scan_cursor"],
    )
    def disable_selected_scanners(self, request, queryset) -> None:
        selected_ids = list(queryset.values_list("pk", flat=True))
        if not selected_ids:
            self.message_user(request, "未选中任何扫描游标", level=messages.WARNING)
            return

        updated_count = queryset.model.objects.filter(pk__in=selected_ids).update(
            enabled=False
        )
        self.message_user(
            request,
            f"已暂停 {updated_count} 个扫描游标",
            level=messages.SUCCESS,
        )

    @admin.action(
        description="追平到最新区块",
        permissions=["sync_scan_cursor"],
    )
    def sync_selected_to_latest(self, request, queryset) -> None:
        selected_cursors = list(
            queryset.select_related("chain").order_by("chain_id", "pk")
        )
        if not selected_cursors:
            self.message_user(request, "未选中任何扫描游标", level=messages.WARNING)
            return

        cursor_ids_by_chain_id: dict[int, list[int]] = defaultdict(list)
        chains_by_id = {}
        for cursor in selected_cursors:
            cursor_ids_by_chain_id[cursor.chain_id].append(cursor.pk)
            chains_by_id[cursor.chain_id] = cursor.chain

        success_count = 0
        updated_at = timezone.now()

        for chain_id, cursor_ids in cursor_ids_by_chain_id.items():
            chain = chains_by_id[chain_id]
            try:
                latest_block = self.get_sync_latest_block(chain=chain)
            except Exception as exc:  # noqa: BLE001
                self.message_user(
                    request,
                    f"{chain.code} 获取最新区块失败，已跳过 {len(cursor_ids)} 个扫描游标：{exc}",
                    level=messages.ERROR,
                )
                continue
            with transaction.atomic():
                queryset.model.objects.filter(pk__in=cursor_ids).update(
                    last_scanned_block=latest_block,
                    last_error="",
                    last_error_at=None,
                    updated_at=updated_at,
                )
            success_count += len(cursor_ids)

        if success_count:
            self.message_user(
                request,
                f"已将 {success_count} 个扫描游标追平到链上最新区块",
                level=messages.SUCCESS,
            )
