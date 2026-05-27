import pytest

from chains.constants import CHAIN_SPECS
from chains.constants import ChainName
from chains.constants import ChainType


def test_every_chain_name_has_spec():
    for name in ChainName:
        assert name.value in CHAIN_SPECS, f"{name} 缺少 ChainSpec"


def test_evm_specs_have_chain_id_and_is_poa():
    for name, spec in CHAIN_SPECS.items():
        if spec.type == ChainType.EVM:
            assert spec.chain_id is not None, f"{name} EVM 链必须有 chain_id"
            assert spec.is_poa is not None, f"{name} EVM 链必须有 is_poa"


def test_tron_spec_has_no_evm_fields():
    spec = CHAIN_SPECS[ChainName.Tron]
    assert spec.type == ChainType.TRON
    assert spec.chain_id is None
    assert spec.is_poa is None


@pytest.mark.parametrize(
    ("name", "expected_chain_id"),
    [
        (ChainName.Ethereum, 1),
        (ChainName.BSC, 56),
        (ChainName.Polygon, 137),
        (ChainName.ArbitrumOne, 42161),
        (ChainName.Optimism, 10),
        (ChainName.Base, 8453),
        (ChainName.Avalanche, 43114),
        (ChainName.ZkSyncEra, 324),
        (ChainName.Linea, 59144),
        (ChainName.Scroll, 534352),
    ],
)
def test_evm_chain_ids(name, expected_chain_id):
    assert CHAIN_SPECS[name].chain_id == expected_chain_id


def test_poa_chains():
    poa_names = {n for n, s in CHAIN_SPECS.items() if s.is_poa}
    assert poa_names == {ChainName.BSC, ChainName.Polygon}


def test_native_coin_symbols():
    assert CHAIN_SPECS[ChainName.Ethereum].native_coin_symbol == "ETH"
    assert CHAIN_SPECS[ChainName.BSC].native_coin_symbol == "BNB"
    assert CHAIN_SPECS[ChainName.Polygon].native_coin_symbol == "POL"
    assert CHAIN_SPECS[ChainName.Avalanche].native_coin_symbol == "AVAX"
    assert CHAIN_SPECS[ChainName.Tron].native_coin_symbol == "TRX"
    assert CHAIN_SPECS[ChainName.Tron].native_coin_decimals == 6


def test_chain_name_groups():
    from chains.constants import EVM_CHAIN_NAMES, TRON_CHAIN_NAMES

    assert len(EVM_CHAIN_NAMES) == 11
    assert TRON_CHAIN_NAMES == (ChainName.Tron,)
    assert ChainName.Ethereum in EVM_CHAIN_NAMES
    assert ChainName.Tron not in EVM_CHAIN_NAMES
