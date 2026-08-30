from laoshiren.infrastructure.auth.huawei_stub import resolve_external_subject
from laoshiren.infrastructure.auth.session_tokens import hash_access_token, issue_access_token


def test_huawei_stub_dev_prefix() -> None:
    assert resolve_external_subject(id_token="dev:alice", app_env="production") == "alice"


def test_huawei_stub_development_accepts_raw_token() -> None:
    assert resolve_external_subject(id_token="raw-subject", app_env="development") == "raw-subject"


def test_session_token_hash_is_stable() -> None:
    token = issue_access_token()
    assert hash_access_token(token) == hash_access_token(token)
