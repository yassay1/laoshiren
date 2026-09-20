"""Development-only Huawei Account authorization-code adapter."""

from laoshiren.application.identity.dto import HuaweiAccountIdentityDTO
from laoshiren.application.identity.ports import HuaweiAuthorizationCodeRejected


class StubHuaweiAccountClient:
    """Resolve deterministic subjects without contacting Huawei Account."""

    def __init__(self, *, app_env: str) -> None:
        self._app_env = app_env

    async def exchange_authorization_code(
        self,
        *,
        authorization_code: str,
    ) -> HuaweiAccountIdentityDTO:
        try:
            subject = resolve_external_subject(
                authorization_code=authorization_code,
                app_env=self._app_env,
            )
        except ValueError as exception:
            raise HuaweiAuthorizationCodeRejected(str(exception)) from exception
        return HuaweiAccountIdentityDTO(external_subject=subject)


def resolve_external_subject(*, authorization_code: str, app_env: str) -> str:
    """Compatibility helper used by the development adapter and focused tests."""

    clean = authorization_code.strip()
    if not clean:
        raise ValueError("authorization_code must not be empty.")
    if clean.startswith("dev:"):
        subject = clean.removeprefix("dev:").strip()
        if not subject:
            raise ValueError("dev authorization_code must include a subject.")
        return subject
    if app_env == "development":
        return clean
    raise ValueError("Stub Huawei authorization codes are disabled outside development.")
