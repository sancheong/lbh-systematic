from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from lbh.core.config import Config


class RequestClassificationKind(str, Enum):
    SMALL = "small"
    BROAD = "broad"
    MULTI_COMPONENT = "multi_component"


@dataclass(frozen=True)
class RequestClassification:
    kind: RequestClassificationKind
    component_count: int = 1
    reasons: tuple[str, ...] = ()

    @classmethod
    def small(cls) -> "RequestClassification":
        return cls(RequestClassificationKind.SMALL)

    @property
    def is_small(self) -> bool:
        return self.kind is RequestClassificationKind.SMALL

    @property
    def is_broad_or_multi_component(self) -> bool:
        return not self.is_small

    @property
    def uses_normal_gateway_run(self) -> bool:
        return self.is_small


def classify_patch_request(request: str, config: Config | None = None) -> RequestClassification:
    cfg = config or Config({})
    if not cfg.enable_broad_request_planning:
        return RequestClassification.small()
    raw = request.lower()
    normalized = " ".join(raw.split())
    component_count = _estimate_component_count(raw, cfg.request_classification_component_separators)
    broad_terms = tuple(
        term
        for term in cfg.request_classification_broad_terms
        if term.lower() in normalized
    )

    if broad_terms:
        return RequestClassification(
            RequestClassificationKind.BROAD,
            component_count=max(component_count, 1),
            reasons=tuple(f"broad_term:{term}" for term in broad_terms),
        )

    component_limit = cfg.request_classification_component_limit
    if component_count > component_limit:
        return RequestClassification(
            RequestClassificationKind.MULTI_COMPONENT,
            component_count=component_count,
            reasons=(f"component_count>{component_limit}",),
        )

    return RequestClassification(
        RequestClassificationKind.SMALL,
        component_count=component_count,
    )


def _estimate_component_count(request: str, separators: list[str]) -> int:
    if not request.strip():
        return 0

    count = 1
    for separator in separators:
        if separator:
            count += request.count(separator.lower())
    return count
