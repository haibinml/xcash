from django.core.exceptions import ValidationError
from django.test import TestCase
from web3 import Web3

from chains.constants import ChainCode
from chains.models import Chain
from currencies.models import ChainToken
from currencies.models import Crypto


class ChainNativeCryptoMappingTests(TestCase):
    def test_creating_chain_auto_creates_native_crypto_mapping(self):
        chain = Chain.objects.create(
            code=ChainCode.Ethereum,
            rpc="",
            active=True,
        )
        native_coin = chain.native_coin

        native_mapping = ChainToken.objects.get(crypto=native_coin, chain=chain)
        self.assertEqual(native_mapping.address, "")
        # 原生币精度以 ChainToken 为唯一真相，取自链的 ChainSpec（ETH=18）。
        self.assertEqual(native_mapping.decimals, chain.spec.native_coin_decimals)


class ChainTokenImmutabilityTests(TestCase):
    """ChainToken 的「地址↔币」身份定死：crypto/chain 创建后不可经 save() 变更。"""

    def setUp(self):
        self.chain = Chain.objects.create(
            code=ChainCode.Ethereum,
            rpc="",
            active=True,
        )
        self.usdt = Crypto.objects.create(
            name="Tether", symbol="USDT", coingecko_id="tether"
        )
        self.usdc = Crypto.objects.create(
            name="USD Coin", symbol="USDC", coingecko_id="usd-coin"
        )
        self.token = ChainToken.objects.create(
            crypto=self.usdt,
            chain=self.chain,
            address=Web3.to_checksum_address("0x" + "11" * 20),
            decimals=6,
        )

    def test_changing_crypto_via_save_is_rejected(self):
        self.token.crypto = self.usdc
        with self.assertRaises(ValidationError):
            self.token.save()

        self.token.refresh_from_db()
        self.assertEqual(self.token.crypto_id, self.usdt.id)

    def test_changing_decimals_via_save_is_allowed(self):
        # 精度等非身份字段可正常更新，守卫只锁 crypto/chain。
        self.token.decimals = 8
        self.token.save(update_fields=["decimals"])

        self.token.refresh_from_db()
        self.assertEqual(self.token.decimals, 8)

    def test_merge_update_path_bypasses_guard(self):
        # 占位符合并走 QuerySet.update()，是变更 crypto 的唯一受控入口，不受守卫限制。
        ChainToken.objects.filter(pk=self.token.pk).update(crypto=self.usdc)

        self.token.refresh_from_db()
        self.assertEqual(self.token.crypto_id, self.usdc.id)
