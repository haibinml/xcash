from rest_framework import serializers

from chains.models import Chain
from currencies.models import ChainToken
from currencies.models import Crypto


class ChainTokenSerializer(serializers.ModelSerializer):
    chain = serializers.SlugRelatedField(slug_field="chain", read_only=True)

    class Meta:
        model = ChainToken
        fields = ["chain", "address", "decimals"]


class InternalCryptoSerializer(serializers.ModelSerializer):
    chain_tokens = ChainTokenSerializer(many=True, read_only=True)

    class Meta:
        model = Crypto
        fields = [
            "name",
            "symbol",
            "is_native",
            "prices",
            "active",
            "chain_tokens",
        ]


class InternalChainSerializer(serializers.ModelSerializer):
    native_coin = serializers.SerializerMethodField()

    class Meta:
        model = Chain
        fields = [
            "name",
            "chain",
            "type",
            "native_coin",
            "confirm_block_count",
            "active",
        ]

    def get_native_coin(self, obj) -> str:
        return obj.spec.native_coin_symbol
