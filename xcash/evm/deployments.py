from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from web3 import Web3


@dataclass(frozen=True)
class XcashDepositDeployment:
    deposit_template: str
    deposit_factory: str


def _deployment_file_path() -> Path:
    configured = getattr(settings, "EVM_DEPOSIT_SLOT_FACTORY_PATH", "")
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / "xcash" / "evm" / "deposit_slot_factory.json"


def get_xcash_deposit_deployment(chain_code: str) -> XcashDepositDeployment:
    path = _deployment_file_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        item = raw[chain_code]
    except FileNotFoundError as exc:
        raise RuntimeError(f"缺少 DepositSlot Factory 部署配置文件: {path}") from exc
    except KeyError as exc:
        raise RuntimeError(f"链 {chain_code} 未配置 DepositSlot Factory 部署地址") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DepositSlot Factory 部署配置 JSON 非法: {path}") from exc

    template = item.get("deposit_template")
    factory = item.get("deposit_factory")
    if not Web3.is_address(template or "") or not Web3.is_address(factory or ""):
        raise RuntimeError(f"链 {chain_code} 的 XcashDeposit 部署地址非法")

    return XcashDepositDeployment(
        deposit_template=Web3.to_checksum_address(template),
        deposit_factory=Web3.to_checksum_address(factory),
    )
