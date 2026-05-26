# xcash EVM Vault Slot Contracts

XcashVaultSlotFactory 与 XcashVaultSlotTemplate 是合约账单与充币的链上归集入口。

## 设计

- `XcashVaultSlotFactory` 持有不可变的 `vaultSlotTemplate` 地址。
- `deployVaultSlot(vault, salt)` 使用 OpenZeppelin Clones immutable args 通过 CREATE2 部署 slot。
- 每个 slot 的 immutable `vault` 决定原生币和 ERC20 最终归集地址。
- `XcashVaultSlotTemplate` 的 `receive` 会把原生币转发到 vault。
- ERC20 余额由 `collect(token)` 转入 vault。

## 构建

```bash
forge install OpenZeppelin/openzeppelin-contracts@v5.6.1 --no-git --shallow
make all
make test
```

## 地址预测公式

```text
vault_slot = keccak256(0xff || factory || salt || keccak256(slot_init_code))[-20:]
```

其中 `slot_init_code` 由 OpenZeppelin `Clones` immutable args 规则构造。
Python 侧对应实现为 `xcash/evm/contracts_codec.py` 的
`build_xcash_vault_slot_init_code(vault_slot_template, vault)` 和
`predict_xcash_vault_slot_address(vault, salt)`；如需校验非默认部署地址，
也可显式传入 `factory` 和 `vault_slot_template`。

## Fixtures

`make fixtures` 会运行 `scripts/DumpXcashVaultSlotFixtures.s.sol`，生成：

```text
../tests/fixtures/xcash_vault_slot_fixtures.json
```

该 fixture 用 Foundry/OpenZeppelin 的实现校验 Python 侧 slot init_code 与
CREATE2 地址预测逻辑。

## Salt 约束

工厂无访问控制，任何人拿到相同 `salt + vault` 都能触发部署。业务层生成
salt 时必须包含服务端秘密或使用内部不可预测随机源，禁止直接使用公开订单号、
商户号、递增编号等可预测输入。
