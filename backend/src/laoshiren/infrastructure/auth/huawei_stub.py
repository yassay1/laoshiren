"""Development-oriented Huawei ID token validation stub."""


def resolve_external_subject(*, id_token: str, app_env: str) -> str:
    clean = id_token.strip()
    if not clean:
        raise ValueError("id_token must not be empty.")
    if clean.startswith("dev:"):
        subject = clean.removeprefix("dev:").strip()
        if not subject:
            raise ValueError("dev id_token must include a subject.")
        return subject
    if app_env == "development":
        return clean
    raise ValueError("Huawei ID token validation is not configured for production.")
