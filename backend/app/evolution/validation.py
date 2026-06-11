from __future__ import annotations

"""Configuration-driven validation evaluators for evolution targets."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..models import EvolutionSignal, EvolutionTarget

SUPPORTED_VALIDATION_EVALUATORS = frozenset({
    "count_signals",
    "rate",
})


@dataclass(frozen=True)
class SignalSelector:
    signal_types: tuple[str, ...] = ()
    severity: str | None = None


@dataclass(frozen=True)
class ValidationMetricDefinition:
    id: str
    label: str
    evaluator: str
    window: str | None = None
    signal_selector: SignalSelector | None = None
    numerator: SignalSelector | None = None
    denominator: SignalSelector | None = None
    goal: dict[str, Any] = field(default_factory=dict)
    metadata_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationResult:
    metric_id: str
    label: str
    evaluator: str
    target_id: str
    value: Any | None
    status: str
    window: str | None = None
    goal: dict[str, Any] = field(default_factory=dict)
    sample_size: int = 0
    numerator_count: int | None = None
    denominator_count: int | None = None
    updated_at: datetime | None = None
    metadata_json: dict[str, Any] = field(default_factory=dict)


def validation_config_from_target(target: EvolutionTarget) -> dict:
    meta = target.metadata_json or {}
    validation = meta.get("validation")
    return validation if isinstance(validation, dict) else {}


def validation_metric_definitions(target: EvolutionTarget) -> list[ValidationMetricDefinition]:
    validation = validation_config_from_target(target)
    inherited_window = validation.get("window")
    metric_rows = validation.get("metrics")
    if not isinstance(metric_rows, list):
        return []
    out: list[ValidationMetricDefinition] = []
    for raw in metric_rows:
        parsed = _parse_metric_definition(raw, inherited_window=inherited_window)
        if parsed is not None:
            out.append(parsed)
    return out


def evaluate_target_validation(
    db: Session,
    target: EvolutionTarget,
    *,
    space_id: str,
) -> list[ValidationResult]:
    definitions = validation_metric_definitions(target)
    if not definitions:
        return []

    rows = (
        db.query(EvolutionSignal)
        .filter(EvolutionSignal.space_id == space_id, EvolutionSignal.target_id == target.id)
        .order_by(EvolutionSignal.created_at.desc())
        .limit(1000)
        .all()
    )
    return [_evaluate_definition(defn, target=target, signals=rows) for defn in definitions]


def _parse_metric_definition(
    raw: object,
    *,
    inherited_window: object,
) -> ValidationMetricDefinition | None:
    if not isinstance(raw, dict):
        return None
    metric_id = raw.get("id")
    evaluator = raw.get("evaluator")
    if not isinstance(metric_id, str) or not metric_id.strip():
        return None
    if not isinstance(evaluator, str) or evaluator not in SUPPORTED_VALIDATION_EVALUATORS:
        return None

    label = raw.get("label")
    window = raw.get("window", inherited_window)
    goal = raw.get("goal")
    metadata = raw.get("metadata_json")
    if evaluator == "count_signals":
        selector = _parse_selector(raw)
        if selector is None:
            return None
        return ValidationMetricDefinition(
            id=metric_id.strip(),
            label=label.strip() if isinstance(label, str) and label.strip() else metric_id.strip(),
            evaluator=evaluator,
            window=window.strip() if isinstance(window, str) and window.strip() else None,
            signal_selector=selector,
            goal=dict(goal) if isinstance(goal, dict) else {},
            metadata_json=dict(metadata) if isinstance(metadata, dict) else {},
        )
    numerator = _parse_selector(raw.get("numerator"))
    denominator = _parse_selector(raw.get("denominator"))
    if numerator is None or denominator is None:
        return None
    return ValidationMetricDefinition(
        id=metric_id.strip(),
        label=label.strip() if isinstance(label, str) and label.strip() else metric_id.strip(),
        evaluator=evaluator,
        window=window.strip() if isinstance(window, str) and window.strip() else None,
        numerator=numerator,
        denominator=denominator,
        goal=dict(goal) if isinstance(goal, dict) else {},
        metadata_json=dict(metadata) if isinstance(metadata, dict) else {},
    )


def _parse_selector(raw: object) -> SignalSelector | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("source") not in {None, "signals"}:
        return None
    signal_types: list[str] = []
    signal_type = raw.get("signal_type")
    if isinstance(signal_type, str) and signal_type.strip():
        signal_types.append(signal_type.strip())
    raw_signal_types = raw.get("signal_types")
    if isinstance(raw_signal_types, list):
        signal_types.extend(item.strip() for item in raw_signal_types if isinstance(item, str) and item.strip())
    if not signal_types:
        return None
    severity = raw.get("severity")
    return SignalSelector(
        signal_types=tuple(dict.fromkeys(signal_types)),
        severity=severity.strip() if isinstance(severity, str) and severity.strip() else None,
    )


def _evaluate_definition(
    definition: ValidationMetricDefinition,
    *,
    target: EvolutionTarget,
    signals: list[EvolutionSignal],
) -> ValidationResult:
    cutoff = _window_cutoff(definition.window)
    scoped = [signal for signal in signals if cutoff is None or _is_after_window(signal.created_at, cutoff)]
    if definition.evaluator == "count_signals":
        matched = _matching_signals(scoped, definition.signal_selector)
        value = len(matched)
        return ValidationResult(
            metric_id=definition.id,
            label=definition.label,
            evaluator=definition.evaluator,
            target_id=target.id,
            value=value,
            status=_goal_status(value, definition.goal),
            window=definition.window,
            goal=definition.goal,
            sample_size=len(matched),
            updated_at=_latest_signal_time(matched),
            metadata_json=definition.metadata_json,
        )

    numerator = _matching_signals(scoped, definition.numerator)
    denominator = _matching_signals(scoped, definition.denominator)
    denominator_count = len(denominator)
    value = None if denominator_count == 0 else len(numerator) / denominator_count
    return ValidationResult(
        metric_id=definition.id,
        label=definition.label,
        evaluator=definition.evaluator,
        target_id=target.id,
        value=value,
        status="no_data" if value is None else _goal_status(value, definition.goal),
        window=definition.window,
        goal=definition.goal,
        sample_size=denominator_count,
        numerator_count=len(numerator),
        denominator_count=denominator_count,
        updated_at=_latest_signal_time(numerator + denominator),
        metadata_json=definition.metadata_json,
    )


def _matching_signals(
    signals: list[EvolutionSignal],
    selector: SignalSelector | None,
) -> list[EvolutionSignal]:
    if selector is None:
        return []
    signal_types = set(selector.signal_types)
    return [
        signal for signal in signals
        if signal.signal_type in signal_types
        and (selector.severity is None or signal.severity == selector.severity)
    ]


def _latest_signal_time(signals: list[EvolutionSignal]) -> datetime | None:
    latest = None
    for signal in signals:
        if latest is None or signal.created_at > latest:
            latest = signal.created_at
    return latest


def _goal_status(value: Any | None, goal: dict[str, Any]) -> str:
    if value is None:
        return "no_data"
    threshold = goal.get("threshold")
    direction = goal.get("direction")
    if not isinstance(threshold, (int, float)) or direction not in {"decrease", "increase", "equal"}:
        return "observed"
    numeric = float(value)
    if direction == "decrease":
        return "pass" if numeric <= float(threshold) else "fail"
    if direction == "increase":
        return "pass" if numeric >= float(threshold) else "fail"
    return "pass" if numeric == float(threshold) else "fail"


def _window_cutoff(window: str | None) -> datetime | None:
    if not window:
        return None
    amount_text = window[:-1]
    unit = window[-1]
    try:
        amount = int(amount_text)
    except ValueError:
        return None
    now = datetime.now(UTC)
    if unit == "d":
        return now - timedelta(days=amount)
    if unit == "h":
        return now - timedelta(hours=amount)
    if unit == "m":
        return now - timedelta(minutes=amount)
    return None


def _is_after_window(value: datetime, cutoff: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value >= cutoff
