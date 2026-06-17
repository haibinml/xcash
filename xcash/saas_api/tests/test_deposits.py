import pytest

from chains.constants import ChainCode
from chains.tests_fixtures import make_evm_chain
from common.error_codes import ErrorCode
from projects.models import Customer
from projects.models import Project

AUTH_HEADER = "Bearer test-saas-token"


@pytest.mark.django_db
class TestSaasDepositEndpoint:
    def test_address_requires_crypto(self, client, settings):
        settings.SAAS_API_TOKEN = "test-saas-token"
        project = Project.objects.create(name="saas-deposit-project")
        make_evm_chain(code=ChainCode.Ethereum)

        response = client.get(
            f"/saas/v1/projects/{project.appid}/deposits/address",
            {"uid": "user-1", "chain": ChainCode.Ethereum},
            HTTP_AUTHORIZATION=AUTH_HEADER,
        )

        assert response.status_code == ErrorCode.INVALID_CRYPTO.status
        assert response.json() == {
            "code": ErrorCode.INVALID_CRYPTO.code,
            "message": "无效加密货币",
            "detail": "crypto is required",
        }
        assert not Customer.objects.filter(project=project, uid="user-1").exists()

    def test_unknown_chain_code_still_returns_invalid_chain(self, client, settings):
        settings.SAAS_API_TOKEN = "test-saas-token"
        project = Project.objects.create(
            name="saas-deposit-project-2",
        )

        response = client.get(
            f"/saas/v1/projects/{project.appid}/deposits/address",
            {"uid": "user-1", "chain": "missing-chain"},
            HTTP_AUTHORIZATION=AUTH_HEADER,
        )

        assert response.status_code == 400
        assert response.json() == {
            "code": "2000",
            "message": "无效链",
            "detail": "",
        }
