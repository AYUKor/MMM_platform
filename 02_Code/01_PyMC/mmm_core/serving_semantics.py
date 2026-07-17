"""Stable product-serving semantics shared by forecast, optimizer and API layers.

Research packages may contain additional diagnostic targets.  The application
serving boundary deliberately exposes only the turnover model family.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SERVING_POLICY_VERSION = "turnover_serving_v1"
SERVING_TARGET_ID = "turnover"
SERVING_CORE_TARGET = "turnover_per_user"
SERVING_TARGETS = (SERVING_CORE_TARGET,)
SERVING_SEGMENTS_N = 4
ACTIVE_SERVING_MODELS_N = 4
RESEARCH_MODELS_N = 12

CHANNEL_CATALOG_VERSION = "channel_catalog_v1"
CHANNEL_DISPLAY_NAMES: dict[str, str] = {
    "Digital_Performance": "Цифровая реклама",
    "OOH_Total": "Наружная реклама",
    "Радио": "Радио",
    "Indoor": "Indoor",
    "Нац_ТВ": "Национальное ТВ",
    "Рег_ТВ": "Региональное ТВ",
}


class ServingSemanticsError(ValueError):
    """Raised when product-serving data falls outside an approved catalog."""


def serving_model_inventory(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Read the actual research/serving fit inventory from one model package."""

    fits = metadata.get("fits") or {}
    if not isinstance(fits, Mapping):
        raise ServingSemanticsError("Model package fit inventory is invalid")
    turnover_fits = [
        fit
        for fit in fits.values()
        if isinstance(fit, Mapping) and str(fit.get("target") or "") == SERVING_CORE_TARGET
    ]
    segments = [str(fit.get("segment") or "").strip() for fit in turnover_fits]
    return {
        "research_models_in_package_n": len(fits),
        "active_serving_models_n": len(turnover_fits),
        "serving_segments": sorted(segment for segment in segments if segment),
        "duplicate_serving_segments": sorted(
            {segment for segment in segments if segment and segments.count(segment) > 1}
        ),
        "missing_serving_segment_labels_n": sum(not segment for segment in segments),
    }


def validate_serving_model_inventory(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed unless the selected package is the approved 12-to-4 topology."""

    inventory = serving_model_inventory(metadata)
    valid = (
        inventory["research_models_in_package_n"] == RESEARCH_MODELS_N
        and inventory["active_serving_models_n"] == ACTIVE_SERVING_MODELS_N
        and len(inventory["serving_segments"]) == SERVING_SEGMENTS_N
        and not inventory["duplicate_serving_segments"]
        and inventory["missing_serving_segment_labels_n"] == 0
    )
    if not valid:
        raise ServingSemanticsError(
            "Selected model package does not contain the approved turnover serving inventory: "
            f"{inventory}"
        )
    return inventory


def channel_display_name(channel_id: Any) -> str:
    """Return the approved browser label for one canonical channel ID."""

    canonical = str(channel_id or "").strip()
    try:
        return CHANNEL_DISPLAY_NAMES[canonical]
    except KeyError as exc:
        raise ServingSemanticsError(
            f"Channel {canonical!r} is absent from {CHANNEL_CATALOG_VERSION}"
        ) from exc


def channel_identity(channel_id: Any) -> dict[str, str]:
    """Return a machine ID and its approved browser-safe display name."""

    canonical = str(channel_id or "").strip()
    return {
        "channel_id": canonical,
        "channel_display_name": channel_display_name(canonical),
    }
