"""Model cards: what a model can do, merged from three layers.

    catalog (litellm's bundled table)  <  discovered (from a provider listing)  <  user override

Rules carried over from the reference design:
  * an unknown value is None, never 0 and never inferred from another field;
  * the card never carries credentials or endpoints;
  * resolving never raises on a request path: unusable overrides are dropped and reported.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._litellm import litellm

# Field name -> (type, group). Anything else in an override is rejected.
FIELDS: dict[str, tuple[type, str]] = {
    "max_input_tokens": (int, "limits"),
    "max_output_tokens": (int, "limits"),
    "supports_function_calling": (bool, "capabilities"),
    "supports_vision": (bool, "capabilities"),
    "supports_response_schema": (bool, "capabilities"),
    "supports_reasoning": (bool, "capabilities"),
    "supports_prompt_caching": (bool, "capabilities"),
    "supports_web_search": (bool, "capabilities"),
    "input_cost_per_token": (float, "pricing"),
    "output_cost_per_token": (float, "pricing"),
}
_FORBIDDEN = {"apikey", "api_key", "accesstoken", "access_token", "authorization", "password", "secret", "proxyurl", "api_base"}


@dataclass
class ModelCard:
    model: str
    values: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)  # field -> catalog|discovered|override
    matched_catalog_key: str | None = None
    warnings: list[str] = field(default_factory=list)

    def get(self, name: str) -> Any:
        """None means unknown, which is different from False or 0."""
        return self.values.get(name)

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "matched_catalog_key": self.matched_catalog_key,
            **{k: self.values.get(k) for k in FIELDS},
            "sources": dict(self.sources),
            "warnings": list(self.warnings),
        }


def _coerce(name: str, value: Any) -> Any:
    kind = FIELDS[name][0]
    if value is None:
        return None
    if kind is bool:
        if isinstance(value, bool):
            return value
        raise ValueError("must be true or false")
    if isinstance(value, bool):
        raise ValueError("must be a number")
    if kind is int:
        if isinstance(value, (int, float)) and value == int(value) and value > 0:
            return int(value)
        raise ValueError("must be a positive integer")
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    raise ValueError("must be a non-negative number")


def _apply(card: ModelCard, layer: str, raw: dict[str, Any] | None) -> None:
    for name, value in (raw or {}).items():
        if name.replace("-", "_").lower() in _FORBIDDEN:
            card.warnings.append(f"{layer}: '{name}' is not allowed on a model card and was ignored")
            continue
        if name not in FIELDS:
            card.warnings.append(f"{layer}: unknown field '{name}' ignored")
            continue
        try:
            coerced = _coerce(name, value)
        except ValueError as exc:
            card.warnings.append(f"{layer}: '{name}' {exc}; ignored")
            continue
        if coerced is None:
            continue  # unknown stays unknown; it does not erase a lower layer
        card.values[name] = coerced
        card.sources[name] = layer


def catalog_entry(upstream_model: str, litellm_provider: str | None = None) -> tuple[str | None, dict]:
    """Find a catalog row, trying the provider-qualified key first."""
    table = litellm.model_cost
    candidates = []
    if litellm_provider:
        candidates.append(f"{litellm_provider}/{upstream_model}")
    candidates.append(upstream_model)
    for key in candidates:
        row = table.get(key)
        if isinstance(row, dict):
            return key, row
    return None, {}


def resolve(
    upstream_model: str,
    *,
    litellm_provider: str | None = None,
    discovered: dict[str, Any] | None = None,
    override: dict[str, Any] | None = None,
) -> ModelCard:
    card = ModelCard(model=upstream_model)
    key, row = catalog_entry(upstream_model, litellm_provider)
    card.matched_catalog_key = key
    _apply(card, "catalog", {k: row.get(k) for k in FIELDS if k in row})
    _apply(card, "discovered", discovered)
    _apply(card, "override", override)
    return card


def clamp_max_tokens(card: ModelCard, requested: int | None) -> int | None:
    """A request may lower the output ceiling, never raise it above what the card declares."""
    limit = card.get("max_output_tokens")
    if requested is None:
        return limit
    if requested <= 0:
        raise ValueError("max_tokens must be positive")
    return requested if limit is None else min(requested, limit)
