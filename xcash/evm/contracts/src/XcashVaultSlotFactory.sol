// SPDX-License-Identifier: MIT
pragma solidity 0.8.35;

import {Clones} from "@openzeppelin/contracts/proxy/Clones.sol";
import {XcashVaultSlotTemplate} from "./XcashVaultSlotTemplate.sol";

/// @title XcashVaultSlotFactory
/// @notice Deploys XcashVaultSlot addresses with immutable vault args at deterministic CREATE2 addresses.
contract XcashVaultSlotFactory {
    error InvalidVaultSlotTemplate();
    error ZeroVault();

    event XcashVaultSlotDeployed(
        address indexed vaultSlot, address indexed vault, bytes32 indexed salt
    );

    address public immutable vaultSlotTemplate;

    constructor(address vaultSlotTemplate_) {
        if (vaultSlotTemplate_.codehash != keccak256(type(XcashVaultSlotTemplate).runtimeCode)) {
            revert InvalidVaultSlotTemplate();
        }
        vaultSlotTemplate = vaultSlotTemplate_;
    }

    /// @dev 本合约刻意不含任何链上地址预测：EVM(0xff) 与 TVM(0x41) 的 CREATE2
    ///      preimage 前缀不同，链上预测无法共源。slot 地址一律由链下按链各自预测，
    ///      链上唯一权威是 create2 指令本身；目标地址已有合约时 create2 失败并 revert。
    function deployVaultSlot(address payable vault, bytes32 salt)
        external
        returns (address vaultSlot)
    {
        if (vault == address(0)) revert ZeroVault();
        vaultSlot = Clones.cloneDeterministicWithImmutableArgs(
            vaultSlotTemplate, abi.encodePacked(vault), salt
        );
        emit XcashVaultSlotDeployed(vaultSlot, vault, salt);
    }
}
