from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from laoshiren.agent.parallel import count_search_tools_in_results
from laoshiren.agent.tools import ToolDefinition, ToolRisk
from laoshiren.application.search.service import extract_urls_from_search_payload
from laoshiren.domain.personal_state.value_objects import DateCertainty


class PolicyDecision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    REQUIRE_MORE_CONTEXT = "REQUIRE_MORE_CONTEXT"


@dataclass(frozen=True, slots=True)
class PolicyResult:
    decision: PolicyDecision
    code: str
    message: str


def _parse_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return default


def _has_source_provenance(arguments: dict[str, Any]) -> bool:
    source_id = arguments.get("source_id")
    if isinstance(source_id, str) and source_id.strip():
        try:
            UUID(source_id)
            return True
        except ValueError:
            return False
    source_refs = arguments.get("source_refs")
    return isinstance(source_refs, list) and len(source_refs) > 0


def _evidence_urls(arguments: dict[str, Any]) -> list[str]:
    raw = arguments.get("evidence_urls")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if isinstance(item, str) and item.strip()]


def _search_urls_from_state(state: dict[str, Any] | None) -> set[str]:
    if state is None:
        return set()
    tool_results = state.get("tool_results", [])
    if not isinstance(tool_results, list):
        return set()
    urls: set[str] = set()
    for result in tool_results:
        if not isinstance(result, dict):
            continue
        if result.get("status") != "SUCCESS":
            continue
        tool_name = result.get("tool_name")
        if tool_name not in {"search_web", "url_inspect", "search.official"}:
            continue
        data = result.get("data")
        if isinstance(data, dict):
            urls.update(extract_urls_from_search_payload(data))
    return urls


def _has_verified_search_evidence(state: dict[str, Any] | None, arguments: dict[str, Any]) -> bool:
    urls = _evidence_urls(arguments)
    if not urls:
        return False
    known = _search_urls_from_state(state)
    return any(url in known for url in urls)


def _prefetched_thing_has_deadline(state: dict[str, Any], thing_id: str) -> bool:
    prefetch = state.get("prefetched_state", {})
    if not isinstance(prefetch, dict):
        return False
    active = prefetch.get("active_thing_context", {})
    if isinstance(active, dict) and str(active.get("thing_id", "")) == thing_id:
        return active.get("deadline_at") is not None
    return False


class ToolPolicy:
    """Deterministic V1 policy matrix; prompts never override this decision."""

    def __init__(self, *, search_max_per_run: int = 6) -> None:
        self._search_max_per_run = search_max_per_run

    def evaluate(
        self,
        definition: ToolDefinition,
        *,
        state: dict[str, Any] | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> PolicyResult:
        if not definition.enabled:
            return PolicyResult(PolicyDecision.DENY, "TOOL_DISABLED", "Tool is disabled.")

        args = arguments or {}

        if definition.name in {"search_web", "url_inspect", "search.web", "search.official"}:
            if state is not None:
                tool_results = state.get("tool_results", [])
                if isinstance(tool_results, list):
                    used = count_search_tools_in_results(tool_results)
                    budget = state.get("budget_snapshot", {})
                    search_limit = (
                        int(budget.get("max_search_queries", self._search_max_per_run))
                        if isinstance(budget, dict)
                        else self._search_max_per_run
                    )
                    if used >= search_limit:
                        return PolicyResult(
                            PolicyDecision.DENY,
                            "SEARCH_QUOTA_EXCEEDED",
                            "Search quota for this run has been exceeded.",
                        )
            return PolicyResult(PolicyDecision.ALLOW, "ALLOWED", "Search is allowed.")

        if definition.name in {"thing_date_set", "state.set_deadline"}:
            certainty_raw = args.get("certainty")
            try:
                certainty = DateCertainty(str(certainty_raw))
            except ValueError:
                certainty = None
            is_primary = _parse_bool(args.get("is_primary"), default=True)
            thing_id = str(args.get("thing_id", ""))
            has_source = _has_source_provenance(args)
            has_search_evidence = _has_verified_search_evidence(state, args)

            if (
                certainty is DateCertainty.CONFIRMED
                and is_primary
                and not has_source
                and not has_search_evidence
            ):
                return PolicyResult(
                    PolicyDecision.REQUIRE_MORE_CONTEXT,
                    "DEADLINE_NEEDS_VERIFICATION",
                    "Confirmed primary deadlines require source evidence "
                    "or explicit user confirmation.",
                )

            if (
                certainty is DateCertainty.CONFIRMED
                and is_primary
                and (has_source or has_search_evidence)
                and state is not None
                and thing_id
                and _prefetched_thing_has_deadline(state, thing_id)
            ):
                return PolicyResult(
                    PolicyDecision.REQUIRE_CONFIRMATION,
                    "DEADLINE_OVERWRITE",
                    "Overwriting an existing deadline requires user confirmation "
                    "even with source evidence.",
                )

            if has_source and certainty is DateCertainty.CONFIRMED:
                return PolicyResult(
                    PolicyDecision.ALLOW,
                    "SOURCE_VERIFIED_DEADLINE",
                    "Source-backed confirmed deadline is allowed.",
                )

            if has_search_evidence and certainty is DateCertainty.CONFIRMED:
                return PolicyResult(
                    PolicyDecision.ALLOW,
                    "SEARCH_VERIFIED_DEADLINE",
                    "Search-backed confirmed deadline is allowed.",
                )

        if definition.risk in {ToolRisk.SENSITIVE_WRITE, ToolRisk.IRREVERSIBLE}:
            return PolicyResult(
                PolicyDecision.REQUIRE_CONFIRMATION,
                "CONFIRMATION_REQUIRED",
                "Explicit user confirmation is required.",
            )
        return PolicyResult(PolicyDecision.ALLOW, "ALLOWED", "Tool execution is allowed.")
