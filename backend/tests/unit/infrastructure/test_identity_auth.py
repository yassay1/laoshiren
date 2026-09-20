from urllib.parse import parse_qs

import httpx
import pytest

from laoshiren.application.identity.ports import (
    HuaweiAccountUnavailable,
    HuaweiAuthorizationCodeRejected,
)
from laoshiren.infrastructure.auth.huawei_account import HttpHuaweiAccountClient
from laoshiren.infrastructure.auth.huawei_stub import StubHuaweiAccountClient
from laoshiren.infrastructure.auth.session_tokens import hash_access_token, issue_access_token

pytestmark = pytest.mark.asyncio


async def test_huawei_stub_accepts_dev_code_without_external_configuration() -> None:
    client = StubHuaweiAccountClient(app_env="production")

    identity = await client.exchange_authorization_code(authorization_code="dev:alice")

    assert identity.external_subject == "alice"
    assert identity.union_id is None
    assert identity.open_id is None


async def test_huawei_stub_accepts_raw_subject_only_in_development() -> None:
    development_client = StubHuaweiAccountClient(app_env="development")
    production_client = StubHuaweiAccountClient(app_env="production")

    identity = await development_client.exchange_authorization_code(
        authorization_code="raw-subject"
    )
    assert identity.external_subject == "raw-subject"
    with pytest.raises(HuaweiAuthorizationCodeRejected):
        await production_client.exchange_authorization_code(
            authorization_code="raw-subject"
        )


async def test_huawei_http_adapter_exchanges_code_and_prefers_union_id() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        form = parse_qs(request.content.decode())
        if request.url.host == "oauth-login.test":
            assert form == {
                "grant_type": ["authorization_code"],
                "code": ["one-time-code"],
                "client_id": ["client-id"],
                "client_secret": ["server-secret"],
            }
            return httpx.Response(200, json={"access_token": "user-access-token"})
        assert request.url.host == "oauth-api.test"
        assert form == {
            "access_token": ["user-access-token"],
            "open_id": ["OPENID"],
        }
        return httpx.Response(
            200,
            headers={"NSP_STATUS": "0"},
            json={
                "client_id": "client-id",
                "union_id": "union-subject",
                "open_id": "open-subject",
            },
        )

    client = HttpHuaweiAccountClient(
        client_id="client-id",
        client_secret="server-secret",
        token_url="https://oauth-login.test/oauth2/v3/token",
        token_info_url="https://oauth-api.test/token-info",
        transport=httpx.MockTransport(handler),
    )

    identity = await client.exchange_authorization_code(
        authorization_code="one-time-code"
    )

    assert len(requests) == 2
    assert identity.external_subject == "union-subject"
    assert identity.union_id == "union-subject"
    assert identity.open_id == "open-subject"


async def test_huawei_http_adapter_maps_rejected_code_without_leaking_response() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": 1101,
                "sub_error": 20129,
                "error_description": "sensitive provider detail",
            },
        )

    client = HttpHuaweiAccountClient(
        client_id="client-id",
        client_secret="server-secret",
        token_url="https://oauth-login.test/token",
        token_info_url="https://oauth-api.test/token-info",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(HuaweiAuthorizationCodeRejected) as captured:
        await client.exchange_authorization_code(authorization_code="expired-code")
    assert "sensitive" not in str(captured.value)
    assert "server-secret" not in str(captured.value)


async def test_huawei_http_adapter_rejects_mismatched_client_identity() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth-login.test":
            return httpx.Response(200, json={"access_token": "user-access-token"})
        return httpx.Response(
            200,
            headers={"NSP_STATUS": "0"},
            json={"client_id": "another-client", "open_id": "open-subject"},
        )

    client = HttpHuaweiAccountClient(
        client_id="client-id",
        client_secret="server-secret",
        token_url="https://oauth-login.test/token",
        token_info_url="https://oauth-api.test/token-info",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(HuaweiAccountUnavailable):
        await client.exchange_authorization_code(authorization_code="one-time-code")


async def test_session_token_hash_is_stable() -> None:
    token = issue_access_token()
    assert hash_access_token(token) == hash_access_token(token)
