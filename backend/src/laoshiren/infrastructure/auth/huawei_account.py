"""Huawei Account server-side authorization-code adapter."""

from typing import Any

import httpx

from laoshiren.application.identity.dto import HuaweiAccountIdentityDTO
from laoshiren.application.identity.ports import (
    HuaweiAccountUnavailable,
    HuaweiAuthorizationCodeRejected,
)


class HttpHuaweiAccountClient:
    """Exchange a one-time code and resolve its trusted UnionID/OpenID."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        token_url: str = "https://oauth-login.cloud.huawei.com/oauth2/v3/token",
        token_info_url: str = (
            "https://oauth-api.cloud.huawei.com/rest.php"
            "?nsp_fmt=JSON&nsp_svc=huawei.oauth2.user.getTokenInfo"
        ),
        redirect_uri: str = "",
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not client_id.strip() or not client_secret.strip():
            raise ValueError("Huawei Account client ID and client secret are required.")
        if not token_url.startswith("https://") or not token_info_url.startswith("https://"):
            raise ValueError("Huawei Account endpoints must use HTTPS.")
        if timeout_seconds <= 0:
            raise ValueError("Huawei Account timeout must be positive.")
        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self._token_url = token_url
        self._token_info_url = token_info_url
        self._redirect_uri = redirect_uri.strip()
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def exchange_authorization_code(
        self,
        *,
        authorization_code: str,
    ) -> HuaweiAccountIdentityDTO:
        clean_code = authorization_code.strip()
        if not clean_code:
            raise HuaweiAuthorizationCodeRejected("Huawei authorization code is empty.")

        token_form = {
            "grant_type": "authorization_code",
            "code": clean_code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._redirect_uri:
            token_form["redirect_uri"] = self._redirect_uri

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                token_response = await client.post(self._token_url, data=token_form)
                if token_response.status_code == httpx.codes.BAD_REQUEST:
                    raise HuaweiAuthorizationCodeRejected(
                        "Huawei rejected the authorization code."
                    )
                token_response.raise_for_status()
                token_body: Any = token_response.json()
                access_token = _required_string(token_body, "access_token")

                identity_response = await client.post(
                    self._token_info_url,
                    data={"access_token": access_token, "open_id": "OPENID"},
                )
                identity_response.raise_for_status()
                nsp_status = identity_response.headers.get("NSP_STATUS")
                if nsp_status not in (None, "", "0"):
                    raise HuaweiAccountUnavailable(
                        "Huawei could not validate the exchanged credential."
                    )
                identity_body: Any = identity_response.json()
        except HuaweiAuthorizationCodeRejected:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exception:
            raise HuaweiAccountUnavailable("Huawei Account exchange failed.") from exception

        response_client_id = _optional_string(identity_body, "client_id")
        if response_client_id is not None and response_client_id != self._client_id:
            raise HuaweiAccountUnavailable("Huawei Account client identity did not match.")

        union_id = _optional_string(identity_body, "union_id")
        open_id = _optional_string(identity_body, "open_id")
        external_subject = union_id or open_id
        if external_subject is None:
            raise HuaweiAccountUnavailable("Huawei Account response contained no user subject.")
        return HuaweiAccountIdentityDTO(
            external_subject=external_subject,
            union_id=union_id,
            open_id=open_id,
        )


def _required_string(body: Any, key: str) -> str:
    value = _optional_string(body, key)
    if value is None:
        raise ValueError(f"Huawei Account response is missing {key}.")
    return value


def _optional_string(body: Any, key: str) -> str | None:
    if not isinstance(body, dict):
        raise TypeError("Huawei Account response must be an object.")
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"Huawei Account response field {key} must be a string.")
    clean = value.strip()
    return clean or None
