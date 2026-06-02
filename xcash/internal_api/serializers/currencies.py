from rest_framework import serializers

from chains.models import Chain
from currencies.models import ChainCryptoDeployment
from currencies.models import Crypto


class ChainCryptoDeploymentSerializer(serializers.ModelSerializer):
    chain = serializers.SlugRelatedField(slug_field="chain", read_only=True)

    class Meta:
        model = ChainCryptoDeployment
        fields = ["chain", "address", "decimals"]


class InternalCryptoSerializer(serializers.ModelSerializer):
    chain_crypto_deployments = ChainCryptoDeploymentSerializer(many=True, read_only=True)

    class Meta:
        model = Crypto
        fields = [
            "name",
            "symbol",
            "is_native",
            "prices",
            "active",
            "chain_crypto_deployments",
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
