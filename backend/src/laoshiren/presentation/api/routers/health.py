from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/health", summary="Check backend health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
