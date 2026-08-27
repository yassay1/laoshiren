from laoshiren.application.search.ports import WebSearchPort
from laoshiren.config.settings import Settings
from laoshiren.infrastructure.search.recording import RecordingWebSearchAdapter
from laoshiren.infrastructure.search.tavily import TavilyWebSearchAdapter


def build_web_search_port(settings: Settings) -> WebSearchPort:
    provider = settings.search_provider.strip().lower()
    if provider == "tavily":
        if not settings.search_api_key.strip():
            raise ValueError("SEARCH_API_KEY is required when SEARCH_PROVIDER=tavily.")
        return TavilyWebSearchAdapter(
            api_key=settings.search_api_key,
            api_base=settings.search_api_base or "https://api.tavily.com",
            timeout_seconds=settings.search_timeout_seconds,
        )
    if provider in {"", "recording"}:
        return RecordingWebSearchAdapter()
    raise ValueError(f"Unsupported SEARCH_PROVIDER: {settings.search_provider}")
