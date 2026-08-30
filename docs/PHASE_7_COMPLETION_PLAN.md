# Phase 7 Completion Plan — Identity and Production Platform

**Status**: Core complete (2026-08-30). Alembic head: `20260830_0041`.

## Delivered

### Identity data model (`20260830_0041`)
- Extended `users` with `status`, `external_subject`, `updated_at`
- `devices` table (client-provided `device_id`, platform, timezone, last_seen)
- `business_sessions` (hashed opaque access tokens)
- FK `push_endpoints.device_id → devices.id` with backfill for existing rows

### Domain / Application
- `domain/identity/` — `User`, `Device`, `BusinessSession`, `UserStatus`, `DevicePlatform`
- `application/identity/service.py` — Huawei login stub, session issue/revoke, device register, push token upsert/delete, account deletion enqueue
- `apply_account_deletion()` — cancel automations, invalidate push, deactivate devices, revoke sessions, mark `DELETED`

### API (frozen V2.2 surface)
- `POST /auth/huawei/login`
- `POST /auth/logout`
- `GET /me`
- `DELETE /me` → `202` + `ACCOUNT_DELETION` durable job
- `POST /devices/register`
- `PUT /devices/{device_id}/push-token`
- `DELETE /devices/{device_id}/push-token`

### Auth
- Session bearer tokens (SHA-256 stored); development keeps `Bearer {dev_auth_token}` fallback

### Workers / infra
- `AccountDeletionWorker` + scheduler (wired in bootstrap/main)
- `RedisRateLimitMiddleware` — per-IP fail-open rate limit

### Settings
- `session_ttl_hours`, `rate_limit_enabled`, `rate_limit_requests_per_minute`, `object_storage_backend` (local default)

## Deferred (documented)

- Production Huawei ID token validation (JWKS)
- Huawei Push Kit adapter (still `RecordingNotificationAdapter` for push delivery worker)
- S3 / production object storage adapter switch
- `POST /auth/refresh`
- Full account data purge/anonymization beyond lifecycle disable (Files/Memory bulk delete)
- Redis session cache optimization

## Tests

- `tests/unit/infrastructure/test_identity_auth.py`
- `tests/integration/api/test_identity_api.py` (login → device → push token → delete account)
