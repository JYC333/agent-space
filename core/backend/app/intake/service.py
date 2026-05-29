"""Service layer for canonical Intake and Evidence."""
from __future__ import annotations

import hashlib
import html
import json
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings as _default_settings
from ..models import (
    ActivityRecord,
    Agent,
    Artifact,
    Credential,
    EvidenceLink,
    ExtractedEvidence,
    ExtractionJob,
    IntakeItem,
    KnowledgeItem,
    MemoryEntry,
    Policy,
    Project,
    ProjectWorkspace,
    Proposal,
    Run,
    RunEvent,
    SpaceMembership,
    SourceConnection,
    SourceConnector,
    SourceSnapshot,
    Task,
    User,
    Workspace,
    WorkspaceIntakeProfile,
    WorkspaceSourceBinding,
)
from .trust import (
    EVIDENCE_TRUST_VALUES,
    activity_source_trust_to_evidence_trust,
    source_connection_trust_to_evidence_trust,
)
from .url_validator import (
    InvalidIntakeURL,
    IntakeResponseTooLarge,
    extract_domain,
    safe_http_get,
    validate_intake_url,
)

_MAX_FEED_BYTES = 5 * 1024 * 1024
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
_MAX_EXTRACTED_CHARS = 1_000_000
_MAX_EXCERPT_CHARS = 2048
_MAX_INTERNAL_EXCERPT_CHARS = 4096
_NS_ATOM = "http://www.w3.org/2005/Atom"
_NS_DC = "http://purl.org/dc/elements/1.1/"
_NS_CONTENT = "http://purl.org/rss/1.0/modules/content/"

_FREQ_DELTAS: dict[str, timedelta | None] = {
    "manual": None,
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}

_SOURCE_CONNECTION_STATUSES = frozenset({"active", "paused", "archived"})
_CAPTURE_POLICIES = frozenset(
    {
        "metadata_only",
        "excerpt_only",
        "auto_extract_relevant",
        "auto_extract_all_text",
        "archive_all_snapshots",
    }
)
_EVIDENCE_TYPES = frozenset({"document", "excerpt", "event", "log", "artifact", "claim", "summary"})
_EVIDENCE_STATUSES = frozenset({"candidate", "active", "rejected", "archived"})
_EVIDENCE_LINK_TYPES = frozenset(
    {"supports", "contradicts", "derived_from", "mentions", "context_candidate", "used_in_context", "provenance"}
)
_EVIDENCE_LINK_STATUSES = frozenset({"candidate", "active", "rejected", "archived"})
_WORKSPACE_OBSERVATION_POLICIES = frozenset({"disabled", "manual", "auto_select", "auto_extract"})

_BUILTIN_CONNECTORS: tuple[dict, ...] = (
    {
        "connector_key": "rss",
        "display_name": "RSS Feed",
        "connector_type": "external_feed",
        "ingestion_mode": "pull",
        "capabilities_json": {"feed": True, "safe_http": True},
    },
    {
        "connector_key": "atom",
        "display_name": "Atom Feed",
        "connector_type": "external_feed",
        "ingestion_mode": "pull",
        "capabilities_json": {"feed": True, "safe_http": True},
    },
    {
        "connector_key": "manual_url",
        "display_name": "Manual URL",
        "connector_type": "external_url",
        "ingestion_mode": "manual",
        "capabilities_json": {"single_url": True, "safe_http": True},
    },
    {
        "connector_key": "activity_record",
        "display_name": "Activity Records",
        "connector_type": "internal_activity",
        "ingestion_mode": "internal",
        "capabilities_json": {"internal": True},
    },
    {
        "connector_key": "artifact",
        "display_name": "Artifacts",
        "connector_type": "internal_artifact",
        "ingestion_mode": "internal",
        "capabilities_json": {"internal": True},
    },
    {
        "connector_key": "run_event",
        "display_name": "Run Events",
        "connector_type": "internal_run",
        "ingestion_mode": "internal",
        "capabilities_json": {"internal": True},
    },
)

_SUPPORTED_EVIDENCE_TARGET_TYPES = {
    "space",
    "workspace",
    "project",
    "user",
    "agent",
    "run",
    "proposal",
    "artifact",
    "knowledge",
    "memory",
    "task",
}

_INTERNAL_SOURCE_OBJECT_TYPES = {"activity_record", "artifact", "run_event"}
_SUPPORTED_EVIDENCE_SOURCE_OBJECT_TYPES = _INTERNAL_SOURCE_OBJECT_TYPES | {"intake_item", "run"}


class IntakeNotFound(Exception):
    pass


class IntakeValidationError(Exception):
    pass


class IntakeDuplicateError(IntakeValidationError):
    pass


class ExtractionJobNotFound(Exception):
    pass


class ExtractionJobStateError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


def _next_check_at(frequency: str) -> datetime | None:
    delta = _FREQ_DELTAS.get(frequency)
    if delta is None:
        return None
    return _now() + delta


def _safe_error(exc: Exception, max_len: int = 256) -> str:
    raw = str(exc)
    raw = re.sub(r"<[^>]{0,200}>", "", raw)
    return raw[:max_len]


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str).replace(tzinfo=UTC)
    except Exception:
        pass
    try:
        from dateutil import parser as dp
        return dp.parse(date_str).astimezone(UTC)
    except Exception:
        return None


def _strip_tags(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", text).strip()


def _bounded_plain_text(text: object | None, *, max_chars: int = _MAX_INTERNAL_EXCERPT_CHARS) -> str:
    if text is None:
        return ""
    value = html.unescape(str(text))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_chars]


def _strip_html(raw_html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_MAX_EXTRACTED_CHARS]


def _hash_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _merge_metadata(*parts: dict | None) -> dict:
    merged: dict = {}
    for part in parts:
        if part:
            merged.update(part)
    return merged


def _validate_choice(field: str, value: str, allowed: frozenset[str]) -> None:
    if value not in allowed:
        raise IntakeValidationError(f"Unsupported {field}: {value}")


def _validate_confidence(confidence: float | None) -> None:
    if confidence is not None and not (0 <= confidence <= 1):
        raise IntakeValidationError("confidence must be between 0 and 1")


def _find_first(parent: ET.Element, *paths: str) -> ET.Element | None:
    for path in paths:
        found = parent.find(path)
        if found is not None:
            return found
    return None


class IntakeService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Connector catalog
    # ------------------------------------------------------------------

    def seed_builtin_connectors(self) -> None:
        existing = {
            row.connector_key
            for row in self.db.query(SourceConnector).filter(
                SourceConnector.connector_key.in_([c["connector_key"] for c in _BUILTIN_CONNECTORS])
            )
        }
        for spec in _BUILTIN_CONNECTORS:
            if spec["connector_key"] in existing:
                continue
            self.db.add(
                SourceConnector(
                    connector_key=spec["connector_key"],
                    display_name=spec["display_name"],
                    connector_type=spec["connector_type"],
                    ingestion_mode=spec["ingestion_mode"],
                    status="active",
                    capabilities_json=dict(spec["capabilities_json"]),
                    config_schema_json=None,
                )
            )
        self.db.flush()

    def list_connectors(self) -> list[SourceConnector]:
        self.seed_builtin_connectors()
        return (
            self.db.query(SourceConnector)
            .filter(SourceConnector.status == "active")
            .order_by(SourceConnector.connector_key.asc())
            .all()
        )

    def get_connector_by_key(self, connector_key: str) -> SourceConnector:
        self.seed_builtin_connectors()
        row = (
            self.db.query(SourceConnector)
            .filter(SourceConnector.connector_key == connector_key, SourceConnector.status == "active")
            .first()
        )
        if row is None:
            raise IntakeValidationError(f"Unsupported connector_key: {connector_key}")
        return row

    # ------------------------------------------------------------------
    # Source connections
    # ------------------------------------------------------------------

    def _validate_credential_reference(self, space_id: str, credential_id: str | None) -> None:
        if credential_id is None:
            return
        exists = (
            self.db.query(Credential.id)
            .filter(Credential.id == credential_id, Credential.space_id == space_id)
            .first()
        )
        if exists is None:
            raise IntakeNotFound(credential_id)

    def create_connection(
        self,
        *,
        space_id: str,
        owner_user_id: str,
        connector_key: str,
        name: str,
        endpoint_url: str | None = None,
        credential_id: str | None = None,
        fetch_frequency: str = "manual",
        capture_policy: str = "metadata_only",
        trust_level: str = "normal",
        topic_hints: list[str] | None = None,
        consent: dict | None = None,
        policy: dict | None = None,
        config: dict | None = None,
    ) -> SourceConnection:
        connector = self.get_connector_by_key(connector_key)
        validated_url = None
        if endpoint_url:
            try:
                validated_url = validate_intake_url(endpoint_url)
            except InvalidIntakeURL as exc:
                raise IntakeValidationError(str(exc)) from exc
        elif connector.connector_type == "external_feed":
            raise IntakeValidationError("endpoint_url is required for feed connectors")

        if fetch_frequency not in _FREQ_DELTAS:
            raise IntakeValidationError(f"Unsupported fetch_frequency: {fetch_frequency}")
        _validate_choice("capture_policy", capture_policy, _CAPTURE_POLICIES)
        _validate_choice("trust_level", trust_level, EVIDENCE_TRUST_VALUES)
        self._validate_credential_reference(space_id, credential_id)

        if validated_url:
            existing = (
                self.db.query(SourceConnection)
                .filter(
                    SourceConnection.space_id == space_id,
                    SourceConnection.connector_id == connector.id,
                    SourceConnection.endpoint_url == validated_url,
                    SourceConnection.deleted_at.is_(None),
                    SourceConnection.status != "archived",
                )
                .first()
            )
            if existing:
                raise IntakeDuplicateError("An active source connection already exists for this endpoint")

        row = SourceConnection(
            space_id=space_id,
            connector_id=connector.id,
            owner_user_id=owner_user_id,
            credential_id=credential_id,
            name=name.strip()[:512],
            endpoint_url=validated_url,
            fetch_frequency=fetch_frequency,
            capture_policy=capture_policy,
            trust_level=trust_level,
            topic_hints_json=topic_hints,
            consent_json=dict(consent or {}),
            policy_json=dict(policy or {}),
            config_json=dict(config or {}),
            next_check_at=_next_check_at(fetch_frequency),
        )
        with self.db.begin_nested() as sp:
            try:
                self.db.add(row)
                self.db.flush()
                return row
            except IntegrityError as exc:
                sp.rollback()
                raise IntakeDuplicateError("A matching active source connection already exists") from exc

    def get_connection(self, space_id: str, connection_id: str) -> SourceConnection:
        row = (
            self.db.query(SourceConnection)
            .filter(
                SourceConnection.id == connection_id,
                SourceConnection.space_id == space_id,
                SourceConnection.deleted_at.is_(None),
            )
            .first()
        )
        if row is None:
            raise IntakeNotFound(connection_id)
        return row

    def list_connections(
        self,
        space_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[SourceConnection]]:
        q = self.db.query(SourceConnection).filter(
            SourceConnection.space_id == space_id,
            SourceConnection.deleted_at.is_(None),
        )
        if status:
            q = q.filter(SourceConnection.status == status)
        total = q.count()
        rows = q.order_by(SourceConnection.created_at.desc()).offset(offset).limit(limit).all()
        return total, rows

    def update_connection(self, space_id: str, connection_id: str, **updates) -> SourceConnection:
        row = self.get_connection(space_id, connection_id)
        credential_id = updates.get("credential_id")
        if credential_id is not None:
            self._validate_credential_reference(space_id, credential_id)
        for key, value in updates.items():
            if value is None:
                continue
            if key == "name":
                row.name = value.strip()[:512]
            elif key == "status":
                _validate_choice("status", value, _SOURCE_CONNECTION_STATUSES)
                row.status = value
            elif key == "credential_id":
                row.credential_id = value
            elif key == "fetch_frequency":
                if value not in _FREQ_DELTAS:
                    raise IntakeValidationError(f"Unsupported fetch_frequency: {value}")
                row.fetch_frequency = value
                row.next_check_at = _next_check_at(value)
            elif key == "capture_policy":
                _validate_choice("capture_policy", value, _CAPTURE_POLICIES)
                row.capture_policy = value
            elif key == "trust_level":
                _validate_choice("trust_level", value, EVIDENCE_TRUST_VALUES)
                row.trust_level = value
            elif key == "topic_hints":
                row.topic_hints_json = value
            elif key == "consent":
                row.consent_json = dict(value)
            elif key == "policy":
                row.policy_json = dict(value)
            elif key == "config":
                row.config_json = dict(value)
        self.db.flush()
        return row

    def list_due_connections(self) -> list[SourceConnection]:
        return (
            self.db.query(SourceConnection)
            .filter(
                SourceConnection.status == "active",
                SourceConnection.deleted_at.is_(None),
                SourceConnection.next_check_at <= _now(),
                SourceConnection.next_check_at.isnot(None),
            )
            .all()
        )

    # ------------------------------------------------------------------
    # Intake items
    # ------------------------------------------------------------------

    def find_existing_item(
        self,
        space_id: str,
        *,
        source_uri: str | None = None,
        canonical_uri: str | None = None,
        source_object_type: str | None = None,
        source_object_id: str | None = None,
    ) -> IntakeItem | None:
        if source_object_type and source_object_id:
            row = (
                self.db.query(IntakeItem)
                .filter(
                    IntakeItem.space_id == space_id,
                    IntakeItem.source_object_type == source_object_type,
                    IntakeItem.source_object_id == source_object_id,
                    IntakeItem.deleted_at.is_(None),
                )
                .first()
            )
            if row:
                return row
        if canonical_uri:
            row = (
                self.db.query(IntakeItem)
                .filter(
                    IntakeItem.space_id == space_id,
                    IntakeItem.canonical_uri == canonical_uri,
                    IntakeItem.deleted_at.is_(None),
                )
                .first()
            )
            if row:
                return row
        if source_uri:
            return (
                self.db.query(IntakeItem)
                .filter(
                    IntakeItem.space_id == space_id,
                    IntakeItem.source_uri == source_uri,
                    IntakeItem.deleted_at.is_(None),
                )
                .first()
            )
        return None

    def create_item(
        self,
        *,
        space_id: str,
        item_type: str,
        title: str,
        source_uri: str | None = None,
        canonical_uri: str | None = None,
        connection_id: str | None = None,
        source_object_type: str | None = None,
        source_object_id: str | None = None,
        source_external_id: str | None = None,
        author: str | None = None,
        occurred_at: datetime | None = None,
        excerpt: str | None = None,
        content_hash: str | None = None,
        metadata: dict | None = None,
        content_state: str = "metadata_only",
        retention_policy: str = "metadata_only",
    ) -> IntakeItem:
        if bool(source_object_type) != bool(source_object_id):
            raise IntakeValidationError("source_object_type and source_object_id must be provided together")
        if source_object_type in _INTERNAL_SOURCE_OBJECT_TYPES and source_uri:
            raise IntakeValidationError("Internal intake items must use source_object_type/source_object_id, not source_uri")
        if source_object_type in _INTERNAL_SOURCE_OBJECT_TYPES:
            self._validate_source_object(space_id, source_object_type, source_object_id)

        validated_uri = None
        if source_uri:
            try:
                validated_uri = validate_intake_url(source_uri)
            except InvalidIntakeURL as exc:
                raise IntakeValidationError(str(exc)) from exc
        canon = canonical_uri or validated_uri
        safe_excerpt = (excerpt or "")[:_MAX_EXCERPT_CHARS] if excerpt else None

        if connection_id:
            self.get_connection(space_id, connection_id)

        row = IntakeItem(
            space_id=space_id,
            connection_id=connection_id,
            item_type=item_type,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            title=(title or validated_uri or source_object_id or "Untitled intake item").strip()[:1024],
            source_uri=validated_uri,
            canonical_uri=canon,
            source_domain=extract_domain(validated_uri),
            source_external_id=source_external_id,
            author=(author or "")[:512] or None,
            occurred_at=occurred_at,
            excerpt=safe_excerpt,
            content_hash=content_hash,
            metadata_json=metadata,
            content_state=content_state,
            retention_policy=retention_policy,
        )
        with self.db.begin_nested() as sp:
            try:
                self.db.add(row)
                self.db.flush()
                return row
            except IntegrityError:
                sp.rollback()
        existing = self.find_existing_item(
            space_id,
            source_uri=validated_uri,
            canonical_uri=canon,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
        )
        if existing:
            existing.last_seen_at = _now()
            self.db.flush()
            return existing
        raise IntakeValidationError("Duplicate intake item could not be resolved")

    def get_item(self, space_id: str, item_id: str) -> IntakeItem:
        row = (
            self.db.query(IntakeItem)
            .filter(IntakeItem.id == item_id, IntakeItem.space_id == space_id, IntakeItem.deleted_at.is_(None))
            .first()
        )
        if row is None:
            raise IntakeNotFound(item_id)
        return row

    def list_items(
        self,
        space_id: str,
        *,
        status: str | None = None,
        read_status: str | None = None,
        content_state: str | None = None,
        connection_id: str | None = None,
        source_domain: str | None = None,
        created_after: datetime | None = None,
        occurred_after: datetime | None = None,
        include_ignored: bool = False,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[IntakeItem]]:
        q = self.db.query(IntakeItem).filter(
            IntakeItem.space_id == space_id,
            IntakeItem.deleted_at.is_(None),
        )
        if status:
            q = q.filter(IntakeItem.status == status)
        else:
            excluded = []
            if not include_ignored:
                excluded.append("ignored")
            if not include_archived:
                excluded.append("archived")
            if excluded:
                q = q.filter(IntakeItem.status.notin_(excluded))
        if read_status:
            q = q.filter(IntakeItem.read_status == read_status)
        if content_state:
            q = q.filter(IntakeItem.content_state == content_state)
        if connection_id:
            q = q.filter(IntakeItem.connection_id == connection_id)
        if source_domain:
            q = q.filter(IntakeItem.source_domain == source_domain)
        if created_after:
            q = q.filter(IntakeItem.created_at >= created_after)
        if occurred_after:
            q = q.filter(IntakeItem.occurred_at >= occurred_after)
        total = q.count()
        rows = q.order_by(IntakeItem.first_seen_at.desc()).offset(offset).limit(limit).all()
        return total, rows

    def mark_selected(self, space_id: str, item_id: str) -> IntakeItem:
        item = self.get_item(space_id, item_id)
        item.status = "selected"
        self.db.flush()
        return item

    def mark_ignored(self, space_id: str, item_id: str) -> IntakeItem:
        item = self.get_item(space_id, item_id)
        item.status = "ignored"
        self.db.flush()
        return item

    def mark_discussed(self, space_id: str, item_id: str) -> IntakeItem:
        item = self.get_item(space_id, item_id)
        item.read_status = "discussed"
        self.db.flush()
        return item

    def mark_read_later(self, space_id: str, item_id: str) -> IntakeItem:
        item = self.get_item(space_id, item_id)
        item.status = "triaged"
        self.db.flush()
        return item

    # ------------------------------------------------------------------
    # Connection scans and manual URL intake
    # ------------------------------------------------------------------

    def fetch_manual_url(
        self,
        *,
        space_id: str,
        url: str,
        title: str | None = None,
        connection_id: str | None = None,
        queue_content: bool = False,
    ) -> tuple[IntakeItem, ExtractionJob]:
        try:
            validated_url = validate_intake_url(url)
        except InvalidIntakeURL as exc:
            raise IntakeValidationError(str(exc)) from exc

        job = self._start_job(space_id=space_id, job_type="manual_url", connection_id=connection_id)
        item: IntakeItem | None = None
        try:
            existing = self.find_existing_item(space_id, source_uri=validated_url, canonical_uri=validated_url)
            if existing:
                existing.last_seen_at = _now()
                item = existing
                job.intake_item_id = item.id
                job.items_updated = 1
                job.items_created = 0
            else:
                item = self.create_item(
                    space_id=space_id,
                    item_type="external_url",
                    source_uri=validated_url,
                    canonical_uri=validated_url,
                    connection_id=connection_id,
                    title=title or validated_url,
                    content_state="metadata_only",
                    metadata={"created_by": "manual_url"},
                )
                self._create_snapshot(
                    space_id=space_id,
                    intake_item=item,
                    connection_id=connection_id,
                    snapshot_type="metadata",
                    capture_method="manual",
                    metadata={"source_uri": validated_url},
                )
                job.intake_item_id = item.id
                job.items_created = 1
                job.items_updated = 0

            job.status = "succeeded"
            job.items_seen = 1
            if queue_content:
                self.create_pending_extract_text(space_id, item.id)
        except Exception as exc:
            job.status = "failed"
            job.error_code = getattr(exc, "error_code", "manual_url_error")
            job.error_message = _safe_error(exc)
            raise
        finally:
            job.completed_at = _now()
            self.db.flush()

        self._record_activity(
            space_id=space_id,
            activity_type="intake_manual_url",
            title="Manual URL intake",
            payload={"job_id": job.id, "intake_item_id": item.id, "status": job.status},
        )
        return item, job

    def scan_connection(self, space_id: str, connection_id: str) -> ExtractionJob:
        connection = self.get_connection(space_id, connection_id)
        connector = self.db.get(SourceConnector, connection.connector_id)
        if connector is None or connector.connector_key not in ("rss", "atom"):
            raise IntakeValidationError("Only rss and atom connections support scans")

        job = self._start_job(space_id=space_id, connection_id=connection.id, job_type="connection_scan")
        try:
            seen, created, updated = self._do_feed_scan(connection)
            job.status = "succeeded"
            job.items_seen = seen
            job.items_created = created
            job.items_updated = updated
            connection.last_checked_at = _now()
            connection.next_check_at = _next_check_at(connection.fetch_frequency)
        except Exception as exc:
            job.status = "failed"
            job.error_code = getattr(exc, "error_code", "scan_error")
            job.error_message = _safe_error(exc)
        finally:
            job.completed_at = _now()
            self.db.flush()

        self._record_activity(
            space_id=space_id,
            activity_type="intake_connection_scan",
            title=f"Connection scan: {connection.name[:256]}",
            payload={
                "job_id": job.id,
                "connection_id": connection.id,
                "status": job.status,
                "items_seen": job.items_seen,
                "items_created": job.items_created,
                "items_updated": job.items_updated,
            },
        )
        return job

    def _do_feed_scan(self, connection: SourceConnection) -> tuple[int, int, int]:
        if not connection.endpoint_url:
            raise IntakeValidationError("connection has no endpoint_url")
        try:
            raw_bytes, _ = safe_http_get(connection.endpoint_url, timeout=15, max_bytes=_MAX_FEED_BYTES)
        except IntakeResponseTooLarge as exc:
            raise IntakeValidationError(str(exc)) from exc
        except InvalidIntakeURL as exc:
            raise IntakeValidationError(str(exc)) from exc
        except Exception as exc:
            raise IntakeValidationError(_safe_error(exc)) from exc

        try:
            root = ET.fromstring(raw_bytes.decode("utf-8", errors="replace"))
        except ET.ParseError as exc:
            raise IntakeValidationError("Feed XML parse error") from exc

        entries = self._extract_feed_entries(root)
        seen = created = updated = 0
        created_items: list[tuple[IntakeItem, dict]] = []
        for entry in entries:
            seen += 1
            url = entry.get("url") or ""
            if not url:
                continue
            try:
                validated_url = validate_intake_url(url)
            except InvalidIntakeURL:
                continue
            canonical_uri = entry.get("canonical_uri") or validated_url
            existing = self.find_existing_item(
                connection.space_id,
                source_uri=validated_url,
                canonical_uri=canonical_uri,
            )
            if existing:
                existing.last_seen_at = _now()
                updated += 1
                continue
            excerpt = (entry.get("excerpt") or "")[:_MAX_EXCERPT_CHARS]
            item = self.create_item(
                space_id=connection.space_id,
                item_type="feed_entry",
                source_uri=validated_url,
                canonical_uri=canonical_uri,
                connection_id=connection.id,
                source_external_id=entry.get("external_id"),
                title=entry.get("title") or validated_url,
                author=entry.get("author"),
                occurred_at=entry.get("occurred_at"),
                excerpt=excerpt or None,
                content_state="excerpt_saved" if excerpt else "metadata_only",
                retention_policy=self._resolve_retention(connection.capture_policy),
                metadata={"feed_entry": True},
            )
            self._create_snapshot(
                space_id=connection.space_id,
                intake_item=item,
                connection_id=connection.id,
                snapshot_type="metadata",
                capture_method="connection_scan",
                metadata={"entry": {k: str(v) for k, v in entry.items() if v is not None}},
            )
            if excerpt:
                self.create_evidence_from_item(
                    connection.space_id,
                    item.id,
                    status="candidate",
                    extraction_method="feed_excerpt",
                )
            created_items.append((item, entry))
            created += 1

        if connection.capture_policy == "auto_extract_all_text":
            for item, _ in created_items:
                self.create_pending_extract_text(connection.space_id, item.id)
        elif connection.capture_policy == "archive_all_snapshots":
            for item, _ in created_items:
                self.create_pending_snapshot(connection.space_id, item.id)
        elif connection.capture_policy == "auto_extract_relevant":
            hints = connection.topic_hints_json or []
            for item, entry in created_items:
                if self._matches_topic_hints(entry, hints):
                    self.create_pending_extract_text(connection.space_id, item.id)
        return seen, created, updated

    @staticmethod
    def _resolve_retention(capture_policy: str) -> str:
        mapping = {
            "metadata_only": "metadata_only",
            "excerpt_only": "summary_only",
            "auto_extract_relevant": "full_text",
            "auto_extract_all_text": "full_text",
            "archive_all_snapshots": "full_snapshot",
        }
        return mapping.get(capture_policy, "metadata_only")

    @staticmethod
    def _matches_topic_hints(entry: dict, topic_hints: list[str]) -> bool:
        if not topic_hints:
            return False
        searchable = " ".join(
            filter(None, [entry.get("title") or "", entry.get("excerpt") or "", entry.get("author") or "", entry.get("url") or ""])
        ).lower()
        return any(h.lower() in searchable for h in topic_hints)

    @staticmethod
    def _extract_feed_entries(root: ET.Element) -> list[dict]:
        entries: list[dict] = []
        atom_entries = root.findall(f"{{{_NS_ATOM}}}entry") or root.findall("entry")
        for entry in atom_entries:
            url = ""
            for link in entry.findall(f"{{{_NS_ATOM}}}link") or entry.findall("link"):
                if link.get("rel") in (None, "alternate"):
                    url = link.get("href", "")
                    break
            title_el = _find_first(entry, f"{{{_NS_ATOM}}}title", "title")
            author_el = _find_first(
                entry,
                f"{{{_NS_ATOM}}}author/{{{_NS_ATOM}}}name",
                "author/name",
                f"{{{_NS_DC}}}creator",
            )
            pub_el = _find_first(
                entry,
                f"{{{_NS_ATOM}}}published",
                f"{{{_NS_ATOM}}}updated",
                "published",
                "updated",
            )
            summary_el = _find_first(
                entry,
                f"{{{_NS_ATOM}}}summary",
                f"{{{_NS_ATOM}}}content",
                "summary",
                "content",
            )
            entries.append(
                {
                    "url": url,
                    "title": (title_el.text or "") if title_el is not None else "",
                    "author": (author_el.text or "") if author_el is not None else None,
                    "occurred_at": _parse_date(pub_el.text if pub_el is not None else None),
                    "excerpt": _strip_tags(summary_el.text if summary_el is not None else None),
                }
            )
        if entries:
            return entries

        for item in root.findall(".//item"):
            url_el = item.find("link")
            guid_el = item.find("guid")
            title_el = item.find("title")
            author_el = _find_first(item, "author", f"{{{_NS_DC}}}creator")
            pub_el = item.find("pubDate")
            desc_el = _find_first(item, f"{{{_NS_CONTENT}}}encoded", "description")
            canonical = (
                guid_el.text
                if guid_el is not None and guid_el.get("isPermaLink", "true") == "true"
                else None
            )
            entries.append(
                {
                    "url": (url_el.text or "") if url_el is not None else "",
                    "canonical_uri": canonical,
                    "external_id": (guid_el.text or "") if guid_el is not None else None,
                    "title": (title_el.text or "") if title_el is not None else "",
                    "author": (author_el.text or None) if author_el is not None else None,
                    "occurred_at": _parse_date(pub_el.text if pub_el is not None else None),
                    "excerpt": _strip_tags(desc_el.text if desc_el is not None else None),
                }
            )
        return entries

    # ------------------------------------------------------------------
    # Extraction jobs and snapshots
    # ------------------------------------------------------------------

    def create_pending_extract_text(self, space_id: str, item_id: str) -> ExtractionJob:
        item = self.get_item(space_id, item_id)
        if item.content_state in ("content_saved", "snapshot_saved"):
            existing = self._get_completed_job(space_id, item_id, "extract_text")
            if existing:
                return existing
            return self._create_skipped_job(space_id, item, "extract_text", "content_already_saved")
        active = self._get_active_job(space_id, item_id, "extract_text")
        if active:
            return active
        item.content_state = "content_queued"
        job = ExtractionJob(
            space_id=space_id,
            connection_id=item.connection_id,
            intake_item_id=item.id,
            job_type="extract_text",
            status="pending",
        )
        self.db.add(job)
        self.db.flush()
        return job

    def create_pending_snapshot(self, space_id: str, item_id: str) -> ExtractionJob:
        item = self.get_item(space_id, item_id)
        if item.content_state == "snapshot_saved":
            existing = self._get_completed_job(space_id, item_id, "snapshot")
            if existing:
                return existing
            return self._create_skipped_job(space_id, item, "snapshot", "snapshot_already_saved")
        active = self._get_active_job(space_id, item_id, "snapshot")
        if active:
            return active
        item.content_state = "snapshot_queued"
        job = ExtractionJob(
            space_id=space_id,
            connection_id=item.connection_id,
            intake_item_id=item.id,
            job_type="snapshot",
            status="pending",
        )
        self.db.add(job)
        self.db.flush()
        return job

    def create_pending_normalize_activity(self, space_id: str, activity_record_id: str) -> ExtractionJob:
        return self._create_pending_internal_normalization(
            space_id,
            job_type="normalize_activity",
            source_object_type="activity_record",
            source_object_id=activity_record_id,
        )

    def create_pending_normalize_artifact(self, space_id: str, artifact_id: str) -> ExtractionJob:
        return self._create_pending_internal_normalization(
            space_id,
            job_type="normalize_artifact",
            source_object_type="artifact",
            source_object_id=artifact_id,
        )

    def create_pending_normalize_run_event(self, space_id: str, run_event_id: str) -> ExtractionJob:
        return self._create_pending_internal_normalization(
            space_id,
            job_type="normalize_run_event",
            source_object_type="run_event",
            source_object_id=run_event_id,
        )

    def normalize_activity_record(
        self,
        *,
        space_id: str,
        activity_record_id: str,
        created_by_user_id: str | None = None,
    ) -> tuple[IntakeItem, ExtractedEvidence, ExtractionJob]:
        return self._normalize_internal_now(
            space_id=space_id,
            job_type="normalize_activity",
            source_object_type="activity_record",
            source_object_id=activity_record_id,
            created_by_user_id=created_by_user_id,
        )

    def normalize_artifact(
        self,
        *,
        space_id: str,
        artifact_id: str,
        created_by_user_id: str | None = None,
    ) -> tuple[IntakeItem, ExtractedEvidence, ExtractionJob]:
        return self._normalize_internal_now(
            space_id=space_id,
            job_type="normalize_artifact",
            source_object_type="artifact",
            source_object_id=artifact_id,
            created_by_user_id=created_by_user_id,
        )

    def normalize_run_event(
        self,
        *,
        space_id: str,
        run_event_id: str,
        created_by_user_id: str | None = None,
    ) -> tuple[IntakeItem, ExtractedEvidence, ExtractionJob]:
        return self._normalize_internal_now(
            space_id=space_id,
            job_type="normalize_run_event",
            source_object_type="run_event",
            source_object_id=run_event_id,
            created_by_user_id=created_by_user_id,
        )

    def _create_pending_internal_normalization(
        self,
        space_id: str,
        *,
        job_type: str,
        source_object_type: str,
        source_object_id: str,
    ) -> ExtractionJob:
        self._validate_source_object(space_id, source_object_type, source_object_id)
        existing = self._get_active_source_object_job(space_id, source_object_type, source_object_id, job_type)
        if existing:
            return existing
        completed = self._get_completed_source_object_job(space_id, source_object_type, source_object_id, job_type)
        if completed:
            return completed
        job = ExtractionJob(
            space_id=space_id,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            job_type=job_type,
            status="pending",
        )
        self.db.add(job)
        self.db.flush()
        return job

    def _normalize_internal_now(
        self,
        *,
        space_id: str,
        job_type: str,
        source_object_type: str,
        source_object_id: str,
        created_by_user_id: str | None,
    ) -> tuple[IntakeItem, ExtractedEvidence, ExtractionJob]:
        self._validate_source_object(space_id, source_object_type, source_object_id)
        completed = self._get_completed_source_object_job(space_id, source_object_type, source_object_id, job_type)
        if completed:
            data = self._internal_source_payload(space_id, source_object_type, source_object_id)
            item = self.find_existing_item(
                space_id,
                source_object_type=source_object_type,
                source_object_id=source_object_id,
            )
            evidence = self._find_active_candidate_internal_evidence(
                space_id,
                source_object_type,
                source_object_id,
                evidence_type=data["evidence_type"],
            )
            if item is not None and evidence is not None:
                job = self._create_skipped_internal_normalization_job(
                    space_id=space_id,
                    job_type=job_type,
                    source_object_type=source_object_type,
                    source_object_id=source_object_id,
                    item=item,
                    evidence=evidence,
                    previous_job_id=completed.id,
                )
                return item, evidence, job

        job = self._start_job(
            space_id=space_id,
            job_type=job_type,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
        )
        try:
            item, evidence = self._upsert_internal_intake_and_evidence(job, created_by_user_id=created_by_user_id)
            job.status = "succeeded"
            job.items_seen = 1
            job.items_created = 1 if (job.metadata_json or {}).get("created_item") else 0
            job.items_updated = 0 if job.items_created else 1
        except Exception as exc:
            job.status = "failed"
            job.error_code = getattr(exc, "error_code", "internal_normalization_error")
            job.error_message = _safe_error(exc)
            raise
        finally:
            job.completed_at = _now()
            self.db.flush()

        self._record_activity(
            space_id=space_id,
            activity_type="intake_internal_normalization",
            title=f"Internal intake normalization: {source_object_type}",
            payload={
                "job_id": job.id,
                "intake_item_id": job.intake_item_id,
                "source_object_type": source_object_type,
                "source_object_id": source_object_id,
                "status": job.status,
            },
        )
        return item, evidence, job

    def run_pending_job(self, job_id: str, space_id: str) -> ExtractionJob:
        job = self.db.query(ExtractionJob).filter(ExtractionJob.id == job_id, ExtractionJob.space_id == space_id).first()
        if job is None:
            raise ExtractionJobNotFound(job_id)
        if job.status == "running":
            raise ExtractionJobStateError(f"ExtractionJob {job_id!r} is already running")
        if job.status in ("succeeded", "failed", "skipped"):
            return job
        if job.status != "pending":
            raise ExtractionJobStateError(f"Unexpected ExtractionJob status {job.status!r}")

        job.status = "running"
        job.started_at = _now()
        self.db.flush()
        try:
            if job.job_type == "extract_text":
                self._execute_text_extraction(job)
            elif job.job_type == "snapshot":
                self._execute_snapshot(job)
            elif job.job_type in ("normalize_activity", "normalize_artifact", "normalize_run_event"):
                self._execute_internal_normalization(job)
            else:
                raise IntakeValidationError(f"Unsupported pending job_type: {job.job_type}")
        except Exception as exc:
            job.status = "failed"
            job.error_code = getattr(exc, "error_code", "run_error")
            job.error_message = _safe_error(exc)
            if job.intake_item_id:
                try:
                    self.get_item(space_id, job.intake_item_id).content_state = "extraction_failed"
                except Exception:
                    pass
        finally:
            job.completed_at = _now()
            self.db.flush()

        self._record_activity(
            space_id=space_id,
            activity_type="intake_extraction_job",
            title=f"Intake extraction: {job.job_type}",
            payload={
                "job_id": job.id,
                "intake_item_id": job.intake_item_id,
                "job_type": job.job_type,
                "status": job.status,
            },
        )
        return job

    def list_jobs(
        self,
        space_id: str,
        *,
        status: str | None = None,
        intake_item_id: str | None = None,
        connection_id: str | None = None,
        job_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[ExtractionJob]]:
        q = self.db.query(ExtractionJob).filter(ExtractionJob.space_id == space_id)
        if status:
            q = q.filter(ExtractionJob.status == status)
        if intake_item_id:
            q = q.filter(ExtractionJob.intake_item_id == intake_item_id)
        if connection_id:
            q = q.filter(ExtractionJob.connection_id == connection_id)
        if job_type:
            q = q.filter(ExtractionJob.job_type == job_type)
        total = q.count()
        rows = q.order_by(ExtractionJob.created_at.desc()).offset(offset).limit(limit).all()
        return total, rows

    def _get_active_job(self, space_id: str, item_id: str, job_type: str) -> ExtractionJob | None:
        return (
            self.db.query(ExtractionJob)
            .filter(
                ExtractionJob.space_id == space_id,
                ExtractionJob.intake_item_id == item_id,
                ExtractionJob.job_type == job_type,
                ExtractionJob.status.in_(["pending", "running"]),
            )
            .first()
        )

    def _get_completed_job(self, space_id: str, item_id: str, job_type: str) -> ExtractionJob | None:
        return (
            self.db.query(ExtractionJob)
            .filter(
                ExtractionJob.space_id == space_id,
                ExtractionJob.intake_item_id == item_id,
                ExtractionJob.job_type == job_type,
                ExtractionJob.status.in_(["succeeded", "skipped"]),
            )
            .order_by(ExtractionJob.created_at.desc())
            .first()
        )

    def _get_active_source_object_job(
        self,
        space_id: str,
        source_object_type: str,
        source_object_id: str,
        job_type: str,
    ) -> ExtractionJob | None:
        return (
            self.db.query(ExtractionJob)
            .filter(
                ExtractionJob.space_id == space_id,
                ExtractionJob.source_object_type == source_object_type,
                ExtractionJob.source_object_id == source_object_id,
                ExtractionJob.job_type == job_type,
                ExtractionJob.status.in_(["pending", "running"]),
            )
            .first()
        )

    def _get_completed_source_object_job(
        self,
        space_id: str,
        source_object_type: str,
        source_object_id: str,
        job_type: str,
    ) -> ExtractionJob | None:
        return (
            self.db.query(ExtractionJob)
            .filter(
                ExtractionJob.space_id == space_id,
                ExtractionJob.source_object_type == source_object_type,
                ExtractionJob.source_object_id == source_object_id,
                ExtractionJob.job_type == job_type,
                ExtractionJob.status.in_(["succeeded", "skipped"]),
            )
            .order_by(ExtractionJob.created_at.desc())
            .first()
        )

    def _create_skipped_job(self, space_id: str, item: IntakeItem, job_type: str, reason: str) -> ExtractionJob:
        job = ExtractionJob(
            space_id=space_id,
            connection_id=item.connection_id,
            intake_item_id=item.id,
            job_type=job_type,
            status="skipped",
            completed_at=_now(),
            metadata_json={"reason": reason, "content_state": item.content_state},
        )
        self.db.add(job)
        self.db.flush()
        return job

    def _create_skipped_internal_normalization_job(
        self,
        *,
        space_id: str,
        job_type: str,
        source_object_type: str,
        source_object_id: str,
        item: IntakeItem,
        evidence: ExtractedEvidence,
        previous_job_id: str,
    ) -> ExtractionJob:
        job = ExtractionJob(
            space_id=space_id,
            intake_item_id=item.id,
            source_snapshot_id=evidence.source_snapshot_id,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            job_type=job_type,
            status="skipped",
            completed_at=_now(),
            items_seen=1,
            items_created=0,
            items_updated=0,
            metadata_json={
                "reason": "already_normalized",
                "previous_job_id": previous_job_id,
                "intake_item_id": item.id,
                "source_snapshot_id": evidence.source_snapshot_id,
                "evidence_id": evidence.id,
            },
        )
        self.db.add(job)
        self.db.flush()
        return job

    def _execute_internal_normalization(self, job: ExtractionJob) -> None:
        source_object_type = job.source_object_type or self._source_object_type_for_job(job.job_type)
        if not source_object_type or not job.source_object_id:
            raise IntakeValidationError(f"{job.job_type} job is missing source object reference")
        self._validate_source_object(job.space_id, source_object_type, job.source_object_id)
        job.source_object_type = source_object_type
        item, _evidence = self._upsert_internal_intake_and_evidence(job, created_by_user_id=None)
        job.intake_item_id = item.id
        job.status = "succeeded"
        job.items_seen = 1
        job.items_created = 1 if (job.metadata_json or {}).get("created_item") else 0
        job.items_updated = 0 if job.items_created else 1

    @staticmethod
    def _source_object_type_for_job(job_type: str) -> str | None:
        return {
            "normalize_activity": "activity_record",
            "normalize_artifact": "artifact",
            "normalize_run_event": "run_event",
        }.get(job_type)

    def _upsert_internal_intake_and_evidence(
        self,
        job: ExtractionJob,
        *,
        created_by_user_id: str | None,
    ) -> tuple[IntakeItem, ExtractedEvidence]:
        if not job.source_object_type or not job.source_object_id:
            raise IntakeValidationError("Internal normalization requires source_object_type and source_object_id")
        data = self._internal_source_payload(job.space_id, job.source_object_type, job.source_object_id)
        existing_item = self.find_existing_item(
            job.space_id,
            source_object_type=job.source_object_type,
            source_object_id=job.source_object_id,
        )
        created_item = existing_item is None
        item = existing_item or self.create_item(
            space_id=job.space_id,
            item_type=data["item_type"],
            title=data["title"],
            source_object_type=job.source_object_type,
            source_object_id=job.source_object_id,
            occurred_at=data.get("occurred_at"),
            excerpt=data.get("excerpt"),
            content_hash=data.get("content_hash"),
            metadata=data.get("metadata"),
            content_state="excerpt_saved" if data.get("excerpt") else "metadata_only",
            retention_policy="summary_only",
        )
        if not created_item:
            item.last_seen_at = _now()
            item.excerpt = data.get("excerpt") or item.excerpt
            item.content_hash = data.get("content_hash") or item.content_hash
            item.metadata_json = _merge_metadata(item.metadata_json, data.get("metadata"))
            self.db.flush()

        snapshot = self._create_snapshot(
            space_id=job.space_id,
            intake_item=item,
            connection_id=None,
            snapshot_type="metadata",
            capture_method="internal",
            metadata=data.get("metadata"),
        )
        job.intake_item_id = item.id
        job.source_snapshot_id = snapshot.id

        evidence = self._find_active_candidate_internal_evidence(
            job.space_id,
            job.source_object_type,
            job.source_object_id,
            evidence_type=data["evidence_type"],
        )
        if evidence is None:
            evidence = self.create_evidence(
                space_id=job.space_id,
                intake_item_id=item.id,
                extraction_job_id=job.id,
                source_snapshot_id=snapshot.id,
                source_object_type=job.source_object_type,
                source_object_id=job.source_object_id,
                evidence_type=data["evidence_type"],
                title=data["title"],
                content_excerpt=data.get("excerpt"),
                content_hash=data.get("content_hash"),
                artifact_id=data.get("artifact_id"),
                source_title=data["title"],
                occurred_at=data.get("occurred_at"),
                trust_level=data["trust_level"],
                extraction_method=job.job_type,
                status="candidate",
                metadata=data.get("metadata"),
                created_by_user_id=created_by_user_id,
                created_by_run_id=data.get("created_by_run_id"),
            )
        else:
            evidence.extraction_job_id = job.id
            evidence.source_snapshot_id = snapshot.id
            evidence.intake_item_id = item.id
            evidence.content_excerpt = data.get("excerpt") or evidence.content_excerpt
            evidence.content_hash = data.get("content_hash") or evidence.content_hash
            evidence.metadata_json = _merge_metadata(evidence.metadata_json, data.get("metadata"))
            self.db.flush()
        job.metadata_json = {
            "created_item": created_item,
            "intake_item_id": item.id,
            "source_snapshot_id": snapshot.id,
            "evidence_id": evidence.id,
        }
        self.db.flush()
        return item, evidence

    def _find_active_candidate_internal_evidence(
        self,
        space_id: str,
        source_object_type: str,
        source_object_id: str,
        *,
        evidence_type: str | None = None,
    ) -> ExtractedEvidence | None:
        q = self.db.query(ExtractedEvidence).filter(
            ExtractedEvidence.space_id == space_id,
            ExtractedEvidence.source_object_type == source_object_type,
            ExtractedEvidence.source_object_id == source_object_id,
            ExtractedEvidence.status.in_(["candidate", "active"]),
            ExtractedEvidence.deleted_at.is_(None),
        )
        if evidence_type:
            q = q.filter(ExtractedEvidence.evidence_type == evidence_type)
        return q.order_by(ExtractedEvidence.created_at.desc()).first()

    def _internal_source_payload(self, space_id: str, source_object_type: str, source_object_id: str) -> dict:
        if source_object_type == "activity_record":
            row = self.db.query(ActivityRecord).filter(ActivityRecord.id == source_object_id, ActivityRecord.space_id == space_id).first()
            if row is None:
                raise IntakeNotFound(source_object_id)
            payload_text = json.dumps(row.payload_json or {}, sort_keys=True, default=str)
            excerpt = _bounded_plain_text(row.content or payload_text)
            trust = activity_source_trust_to_evidence_trust(row.source_trust)
            return {
                "item_type": "activity_record",
                "evidence_type": "event",
                "title": row.title or f"Activity: {row.activity_type}",
                "excerpt": excerpt,
                "content_hash": _hash_content(excerpt) if excerpt else None,
                "occurred_at": row.occurred_at,
                "trust_level": trust,
                "created_by_run_id": row.source_run_id,
                "metadata": {
                    "internal_ref": {"type": "activity_record", "id": row.id},
                    "activity_type": row.activity_type,
                    "source_kind": row.source_kind,
                    "activity_source_trust": row.source_trust,
                    "workspace_id": row.workspace_id,
                    "project_id": row.project_id,
                    "source_run_id": row.source_run_id,
                },
            }
        if source_object_type == "artifact":
            row = self.db.query(Artifact).filter(Artifact.id == source_object_id, Artifact.space_id == space_id).first()
            if row is None:
                raise IntakeNotFound(source_object_id)
            excerpt = _bounded_plain_text(row.content or row.title)
            return {
                "item_type": "artifact",
                "evidence_type": "artifact",
                "title": row.title,
                "excerpt": excerpt,
                "content_hash": _hash_content(excerpt) if excerpt else None,
                "occurred_at": row.created_at,
                "trust_level": "normal",
                "artifact_id": row.id,
                "created_by_run_id": row.run_id,
                "metadata": {
                    "internal_ref": {"type": "artifact", "id": row.id},
                    "artifact_type": row.artifact_type,
                    "runtime_trust_level": row.trust_level,
                    "run_id": row.run_id,
                    "project_id": row.project_id,
                    "mime_type": row.mime_type,
                },
            }
        if source_object_type == "run_event":
            row = self.db.query(RunEvent).filter(RunEvent.id == source_object_id, RunEvent.space_id == space_id).first()
            if row is None:
                raise IntakeNotFound(source_object_id)
            parts = [row.summary, row.error_code, row.error_message]
            metadata_text = json.dumps(row.metadata_json or {}, sort_keys=True, default=str)
            excerpt = _bounded_plain_text(" ".join(part for part in parts if part) or metadata_text or row.event_type)
            evidence_type = "log" if row.error_message or row.error_code else "event"
            return {
                "item_type": "run_event",
                "evidence_type": evidence_type,
                "title": f"Run event: {row.event_type}",
                "excerpt": excerpt,
                "content_hash": _hash_content(excerpt) if excerpt else None,
                "occurred_at": row.created_at,
                "trust_level": "normal",
                "artifact_id": row.artifact_id,
                "created_by_run_id": row.run_id,
                "metadata": {
                    "internal_ref": {"type": "run_event", "id": row.id},
                    "run_id": row.run_id,
                    "event_type": row.event_type,
                    "status": row.status,
                    "runtime_trust_level": row.trust_level,
                    "data_exposure_level": row.data_exposure_level,
                    "workspace_id": row.workspace_id,
                    "artifact_id": row.artifact_id,
                    "proposal_id": row.proposal_id,
                },
            }
        raise IntakeValidationError(f"Unsupported internal source_object_type: {source_object_type}")

    def _start_job(
        self,
        *,
        space_id: str,
        job_type: str,
        connection_id: str | None = None,
        intake_item_id: str | None = None,
        source_object_type: str | None = None,
        source_object_id: str | None = None,
    ) -> ExtractionJob:
        job = ExtractionJob(
            space_id=space_id,
            connection_id=connection_id,
            intake_item_id=intake_item_id,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            job_type=job_type,
            status="running",
            started_at=_now(),
        )
        self.db.add(job)
        self.db.flush()
        return job

    def _artifact_storage_root(self) -> Path:
        return Path(_default_settings.artifact_storage_root)

    def _write_artifact_file(self, content: str, suffix: str) -> tuple[str, str]:
        artifact_id = _new_id()
        rel_dir = Path("intake") / artifact_id[:2]
        full_dir = self._artifact_storage_root() / rel_dir
        full_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{artifact_id}{suffix}"
        full_path = full_dir / filename
        full_path.write_text(content, encoding="utf-8")
        return str(rel_dir / filename), artifact_id

    def _delete_artifact_file(self, storage_path: str) -> None:
        try:
            (self._artifact_storage_root() / storage_path).unlink(missing_ok=True)
        except OSError:
            pass

    def _create_artifact(
        self,
        *,
        space_id: str,
        artifact_id: str,
        title: str,
        storage_path: str,
        mime_type: str,
        artifact_type: str,
        trust_level: str = "low",
    ) -> Artifact:
        row = Artifact(
            id=artifact_id,
            space_id=space_id,
            artifact_type=artifact_type,
            title=title,
            storage_path=storage_path,
            mime_type=mime_type,
            exportable=False,
            trust_level=trust_level,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _write_and_create_artifact(
        self,
        *,
        space_id: str,
        content: str,
        suffix: str,
        title: str,
        mime_type: str,
        artifact_type: str,
        trust_level: str = "low",
    ) -> Artifact:
        rel_path, artifact_id = self._write_artifact_file(content, suffix)
        try:
            return self._create_artifact(
                space_id=space_id,
                artifact_id=artifact_id,
                title=title,
                storage_path=rel_path,
                mime_type=mime_type,
                artifact_type=artifact_type,
                trust_level=trust_level,
            )
        except Exception:
            self._delete_artifact_file(rel_path)
            raise

    def _fetch_text_artifact(self, item: IntakeItem) -> tuple[Artifact, str, str]:
        if not item.source_uri:
            raise IntakeValidationError("intake item has no source_uri")
        try:
            raw_bytes, content_type = safe_http_get(item.source_uri, timeout=15, max_bytes=_MAX_RESPONSE_BYTES)
        except IntakeResponseTooLarge as exc:
            raise IntakeValidationError(str(exc)) from exc
        except InvalidIntakeURL as exc:
            raise IntakeValidationError(str(exc)) from exc
        except Exception as exc:
            raise IntakeValidationError(_safe_error(exc)) from exc

        try:
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()
            raw_text = raw_bytes.decode(charset, errors="replace")
        except Exception:
            raw_text = raw_bytes.decode("utf-8", errors="replace")

        extracted = _strip_html(raw_text) if "html" in content_type.lower() else raw_text[:_MAX_EXTRACTED_CHARS]
        content_hash = _hash_content(extracted)
        artifact = self._write_and_create_artifact(
            space_id=item.space_id,
            content=extracted,
            suffix=".txt",
            title=f"Extracted text: {item.title[:256]}",
            mime_type="text/plain",
            artifact_type="intake_extracted_text",
            trust_level="low",
        )
        return artifact, content_hash, extracted

    def _execute_text_extraction(self, job: ExtractionJob) -> None:
        if not job.intake_item_id:
            raise IntakeValidationError("extract_text job is missing intake_item_id")
        item = self.get_item(job.space_id, job.intake_item_id)
        artifact, content_hash, extracted = self._fetch_text_artifact(item)
        item.extracted_artifact_id = artifact.id
        item.content_hash = content_hash
        item.content_state = "content_saved"
        snapshot = self._create_snapshot(
            space_id=job.space_id,
            intake_item=item,
            connection_id=item.connection_id,
            snapshot_type="extracted",
            artifact_id=artifact.id,
            content_hash=content_hash,
            capture_method="full_text",
        )
        job.source_snapshot_id = snapshot.id
        evidence = self.create_evidence_from_item(
            job.space_id,
            item.id,
            extraction_job_id=job.id,
            source_snapshot_id=snapshot.id,
            artifact_id=artifact.id,
            content_excerpt=extracted[:4096],
            content_hash=content_hash,
            status="candidate",
            extraction_method="full_text",
        )
        job.metadata_json = {"evidence_id": evidence.id}
        job.status = "succeeded"
        job.items_seen = 1
        self.db.flush()

    def _execute_snapshot(self, job: ExtractionJob) -> None:
        if not job.intake_item_id:
            raise IntakeValidationError("snapshot job is missing intake_item_id")
        item = self.get_item(job.space_id, job.intake_item_id)
        if not item.source_uri:
            raise IntakeValidationError("intake item has no source_uri")
        try:
            raw_bytes, content_type = safe_http_get(item.source_uri, timeout=15, max_bytes=_MAX_RESPONSE_BYTES)
        except IntakeResponseTooLarge as exc:
            raise IntakeValidationError(str(exc)) from exc
        except InvalidIntakeURL as exc:
            raise IntakeValidationError(str(exc)) from exc
        except Exception as exc:
            raise IntakeValidationError(_safe_error(exc)) from exc

        raw_text = raw_bytes.decode("utf-8", errors="replace")
        raw_artifact = self._write_and_create_artifact(
            space_id=item.space_id,
            content=raw_text,
            suffix=".html",
            title=f"Raw snapshot: {item.title[:256]}",
            mime_type=content_type.split(";")[0].strip() or "text/html",
            artifact_type="intake_raw_snapshot",
            trust_level="low",
        )
        content_hash = _hash_content(raw_text)
        raw_snapshot = self._create_snapshot(
            space_id=job.space_id,
            intake_item=item,
            connection_id=item.connection_id,
            snapshot_type="raw",
            artifact_id=raw_artifact.id,
            content_hash=content_hash,
            capture_method="snapshot",
        )
        item.raw_artifact_id = raw_artifact.id
        item.content_hash = content_hash
        item.content_state = "snapshot_saved"
        job.source_snapshot_id = raw_snapshot.id
        job.status = "succeeded"
        job.items_seen = 1

        try:
            extracted = _strip_html(raw_text) if "html" in content_type.lower() else raw_text[:_MAX_EXTRACTED_CHARS]
            extracted_hash = _hash_content(extracted)
            ext_artifact = self._write_and_create_artifact(
                space_id=item.space_id,
                content=extracted,
                suffix=".txt",
                title=f"Extracted text: {item.title[:256]}",
                mime_type="text/plain",
                artifact_type="intake_extracted_text",
                trust_level="low",
            )
            item.extracted_artifact_id = ext_artifact.id
            ext_snapshot = self._create_snapshot(
                space_id=job.space_id,
                intake_item=item,
                connection_id=item.connection_id,
                snapshot_type="extracted",
                artifact_id=ext_artifact.id,
                content_hash=extracted_hash,
                capture_method="snapshot",
            )
            evidence = self.create_evidence_from_item(
                job.space_id,
                item.id,
                extraction_job_id=job.id,
                source_snapshot_id=ext_snapshot.id,
                artifact_id=ext_artifact.id,
                content_excerpt=extracted[:4096],
                content_hash=extracted_hash,
                status="candidate",
                extraction_method="snapshot",
            )
            job.metadata_json = {"raw_snapshot_id": raw_snapshot.id, "extracted_snapshot_id": ext_snapshot.id, "evidence_id": evidence.id}
        except Exception as exc:
            job.metadata_json = {"raw_snapshot_id": raw_snapshot.id, "extraction_error": _safe_error(exc)}
        self.db.flush()

    def _create_snapshot(
        self,
        *,
        space_id: str,
        intake_item: IntakeItem,
        connection_id: str | None,
        snapshot_type: str,
        artifact_id: str | None = None,
        content_hash: str | None = None,
        capture_method: str,
        metadata: dict | None = None,
    ) -> SourceSnapshot:
        row = SourceSnapshot(
            space_id=space_id,
            intake_item_id=intake_item.id,
            connection_id=connection_id,
            snapshot_type=snapshot_type,
            artifact_id=artifact_id,
            content_hash=content_hash,
            source_uri=intake_item.source_uri,
            capture_method=capture_method,
            trust_level=self._connection_trust(connection_id) if connection_id else "normal",
            metadata_json=metadata,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _connection_trust(self, connection_id: str | None) -> str:
        if not connection_id:
            return "normal"
        row = self.db.get(SourceConnection, connection_id)
        return source_connection_trust_to_evidence_trust(row.trust_level if row else None)

    def _validate_source_object(self, space_id: str, source_object_type: str, source_object_id: str | None) -> None:
        if not source_object_id:
            raise IntakeValidationError("source_object_id is required")
        if source_object_type == "intake_item":
            self.get_item(space_id, source_object_id)
            return
        if source_object_type == "activity_record" and self.db.query(ActivityRecord).filter(
            ActivityRecord.id == source_object_id,
            ActivityRecord.space_id == space_id,
        ).first():
            return
        if source_object_type == "artifact" and self.db.query(Artifact).filter(
            Artifact.id == source_object_id,
            Artifact.space_id == space_id,
        ).first():
            return
        if source_object_type == "run" and self.db.query(Run).filter(
            Run.id == source_object_id,
            Run.space_id == space_id,
        ).first():
            return
        if source_object_type == "run_event" and self.db.query(RunEvent).filter(
            RunEvent.id == source_object_id,
            RunEvent.space_id == space_id,
        ).first():
            return
        if source_object_type not in _SUPPORTED_EVIDENCE_SOURCE_OBJECT_TYPES:
            raise IntakeValidationError(f"Unsupported source_object_type: {source_object_type}")
        raise IntakeNotFound(source_object_id)

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def create_evidence(
        self,
        *,
        space_id: str,
        title: str,
        evidence_type: str = "excerpt",
        content_excerpt: str | None = None,
        intake_item_id: str | None = None,
        extraction_job_id: str | None = None,
        source_snapshot_id: str | None = None,
        source_object_type: str | None = None,
        source_object_id: str | None = None,
        artifact_id: str | None = None,
        source_uri: str | None = None,
        source_title: str | None = None,
        source_author: str | None = None,
        occurred_at: datetime | None = None,
        trust_level: str = "normal",
        extraction_method: str = "manual",
        confidence: float | None = None,
        status: str = "candidate",
        metadata: dict | None = None,
        created_by_user_id: str | None = None,
        created_by_agent_id: str | None = None,
        created_by_run_id: str | None = None,
        content_hash: str | None = None,
    ) -> ExtractedEvidence:
        _validate_choice("evidence_type", evidence_type, _EVIDENCE_TYPES)
        _validate_choice("trust_level", trust_level, EVIDENCE_TRUST_VALUES)
        _validate_choice("status", status, _EVIDENCE_STATUSES)
        _validate_confidence(confidence)
        if not title or not title.strip():
            raise IntakeValidationError("title is required")
        if intake_item_id:
            self.get_item(space_id, intake_item_id)
        if extraction_job_id and not self.db.query(ExtractionJob).filter(
            ExtractionJob.id == extraction_job_id,
            ExtractionJob.space_id == space_id,
        ).first():
            raise IntakeNotFound(extraction_job_id)
        if source_snapshot_id and not self.db.query(SourceSnapshot).filter(
            SourceSnapshot.id == source_snapshot_id,
            SourceSnapshot.space_id == space_id,
        ).first():
            raise IntakeNotFound(source_snapshot_id)
        if artifact_id and not self.db.query(Artifact).filter(Artifact.id == artifact_id, Artifact.space_id == space_id).first():
            raise IntakeNotFound(artifact_id)
        if bool(source_object_type) != bool(source_object_id):
            raise IntakeValidationError("source_object_type and source_object_id must be provided together")
        if source_object_type and source_object_id:
            self._validate_source_object(space_id, source_object_type, source_object_id)
        if source_object_type in _INTERNAL_SOURCE_OBJECT_TYPES and source_uri:
            raise IntakeValidationError("Internal evidence must use source_object_type/source_object_id, not source_uri")
        validated_source_uri = None
        if source_uri:
            try:
                validated_source_uri = validate_intake_url(source_uri)
            except InvalidIntakeURL as exc:
                raise IntakeValidationError(str(exc)) from exc

        excerpt = content_excerpt[:4096] if content_excerpt else None
        row = ExtractedEvidence(
            space_id=space_id,
            intake_item_id=intake_item_id,
            extraction_job_id=extraction_job_id,
            source_snapshot_id=source_snapshot_id,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            evidence_type=evidence_type,
            title=title.strip()[:1024],
            content_excerpt=excerpt,
            content_hash=content_hash or (_hash_content(excerpt) if excerpt else None),
            artifact_id=artifact_id,
            source_uri=validated_source_uri,
            source_title=source_title,
            source_author=source_author,
            occurred_at=occurred_at,
            trust_level=trust_level,
            extraction_method=extraction_method,
            confidence=confidence,
            status=status,
            metadata_json=metadata,
            created_by_user_id=created_by_user_id,
            created_by_agent_id=created_by_agent_id,
            created_by_run_id=created_by_run_id,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def create_evidence_from_item(
        self,
        space_id: str,
        item_id: str,
        *,
        extraction_job_id: str | None = None,
        source_snapshot_id: str | None = None,
        artifact_id: str | None = None,
        content_excerpt: str | None = None,
        content_hash: str | None = None,
        status: str = "candidate",
        extraction_method: str = "manual",
        created_by_user_id: str | None = None,
    ) -> ExtractedEvidence:
        item = self.get_item(space_id, item_id)
        return self.create_evidence(
            space_id=space_id,
            intake_item_id=item.id,
            extraction_job_id=extraction_job_id,
            source_snapshot_id=source_snapshot_id,
            source_object_type="intake_item",
            source_object_id=item.id,
            evidence_type="document" if artifact_id else "excerpt",
            title=item.title,
            content_excerpt=content_excerpt or item.excerpt,
            content_hash=content_hash or item.content_hash,
            artifact_id=artifact_id or item.extracted_artifact_id,
            source_uri=item.source_uri,
            source_title=item.title,
            source_author=item.author,
            occurred_at=item.occurred_at,
            trust_level=self._connection_trust(item.connection_id),
            extraction_method=extraction_method,
            status=status,
            metadata={"intake_item_id": item.id},
            created_by_user_id=created_by_user_id,
        )

    def get_evidence(self, space_id: str, evidence_id: str) -> ExtractedEvidence:
        row = (
            self.db.query(ExtractedEvidence)
            .filter(
                ExtractedEvidence.id == evidence_id,
                ExtractedEvidence.space_id == space_id,
                ExtractedEvidence.deleted_at.is_(None),
            )
            .first()
        )
        if row is None:
            raise IntakeNotFound(evidence_id)
        return row

    def list_evidence(
        self,
        space_id: str,
        *,
        status: str | None = None,
        evidence_type: str | None = None,
        intake_item_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[ExtractedEvidence]]:
        q = self.db.query(ExtractedEvidence).filter(
            ExtractedEvidence.space_id == space_id,
            ExtractedEvidence.deleted_at.is_(None),
        )
        if status:
            q = q.filter(ExtractedEvidence.status == status)
        if evidence_type:
            q = q.filter(ExtractedEvidence.evidence_type == evidence_type)
        if intake_item_id:
            q = q.filter(ExtractedEvidence.intake_item_id == intake_item_id)
        total = q.count()
        rows = q.order_by(ExtractedEvidence.created_at.desc()).offset(offset).limit(limit).all()
        return total, rows

    def update_evidence(
        self,
        space_id: str,
        evidence_id: str,
        *,
        status: str | None = None,
        confidence: float | None = None,
        metadata: dict | None = None,
    ) -> ExtractedEvidence:
        row = self.get_evidence(space_id, evidence_id)
        if status is not None:
            _validate_choice("status", status, _EVIDENCE_STATUSES)
            row.status = status
        if confidence is not None:
            _validate_confidence(confidence)
            row.confidence = confidence
        if metadata is not None:
            row.metadata_json = metadata
        self.db.flush()
        return row

    def create_evidence_link(
        self,
        *,
        space_id: str,
        evidence_id: str,
        target_type: str,
        target_id: str | None = None,
        link_type: str = "context_candidate",
        status: str = "active",
        confidence: float | None = None,
        reason: str | None = None,
        created_by_user_id: str | None = None,
        created_by_agent_id: str | None = None,
        created_by_run_id: str | None = None,
    ) -> EvidenceLink:
        _validate_choice("link_type", link_type, _EVIDENCE_LINK_TYPES)
        _validate_choice("status", status, _EVIDENCE_LINK_STATUSES)
        _validate_confidence(confidence)
        self.get_evidence(space_id, evidence_id)
        target_id = self._validate_evidence_target(space_id, target_type, target_id)
        existing = (
            self.db.query(EvidenceLink)
            .filter(
                EvidenceLink.space_id == space_id,
                EvidenceLink.evidence_id == evidence_id,
                EvidenceLink.target_type == target_type,
                EvidenceLink.target_id == target_id,
                EvidenceLink.link_type == link_type,
                EvidenceLink.status == status,
            )
            .first()
        )
        if existing:
            return existing
        row = EvidenceLink(
            space_id=space_id,
            evidence_id=evidence_id,
            target_type=target_type,
            target_id=target_id,
            link_type=link_type,
            status=status,
            confidence=confidence,
            reason=reason,
            created_by_user_id=created_by_user_id,
            created_by_agent_id=created_by_agent_id,
            created_by_run_id=created_by_run_id,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _validate_evidence_target(self, space_id: str, target_type: str, target_id: str | None) -> str:
        if target_type not in _SUPPORTED_EVIDENCE_TARGET_TYPES:
            raise IntakeValidationError(f"Unsupported evidence link target_type: {target_type}")
        if target_type == "space":
            normalized_target_id = target_id or space_id
            if normalized_target_id != space_id:
                raise IntakeNotFound(normalized_target_id)
            return normalized_target_id
        if target_id is None:
            raise IntakeValidationError(f"target_id is required for target_type={target_type!r}")

        exists = False
        if target_type == "workspace":
            exists = self.db.query(Workspace).filter(Workspace.id == target_id, Workspace.space_id == space_id).first() is not None
        elif target_type == "project":
            exists = self.db.query(Project).filter(Project.id == target_id, Project.space_id == space_id).first() is not None
        elif target_type == "user":
            exists = (
                self.db.query(SpaceMembership)
                .join(User, User.id == SpaceMembership.user_id)
                .filter(
                    SpaceMembership.space_id == space_id,
                    SpaceMembership.user_id == target_id,
                    SpaceMembership.status == "active",
                    User.status == "active",
                )
                .first()
                is not None
            )
        elif target_type == "agent":
            exists = self.db.query(Agent).filter(Agent.id == target_id, Agent.space_id == space_id).first() is not None
        elif target_type == "run":
            exists = self.db.query(Run).filter(Run.id == target_id, Run.space_id == space_id).first() is not None
        elif target_type == "proposal":
            exists = self.db.query(Proposal).filter(Proposal.id == target_id, Proposal.space_id == space_id).first() is not None
        elif target_type == "artifact":
            exists = self.db.query(Artifact).filter(Artifact.id == target_id, Artifact.space_id == space_id).first() is not None
        elif target_type == "knowledge":
            exists = self.db.query(KnowledgeItem).filter(KnowledgeItem.id == target_id, KnowledgeItem.space_id == space_id).first() is not None
        elif target_type == "memory":
            exists = self.db.query(MemoryEntry).filter(MemoryEntry.id == target_id, MemoryEntry.space_id == space_id).first() is not None
        elif target_type == "task":
            exists = self.db.query(Task).filter(Task.id == target_id, Task.space_id == space_id).first() is not None
        if not exists:
            raise IntakeNotFound(target_id)
        return target_id

    def list_evidence_links(
        self,
        space_id: str,
        *,
        evidence_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[int, list[EvidenceLink]]:
        q = self.db.query(EvidenceLink).filter(EvidenceLink.space_id == space_id)
        if evidence_id:
            q = q.filter(EvidenceLink.evidence_id == evidence_id)
        if target_type:
            q = q.filter(EvidenceLink.target_type == target_type)
        if target_id:
            q = q.filter(EvidenceLink.target_id == target_id)
        if status:
            q = q.filter(EvidenceLink.status == status)
        total = q.count()
        rows = q.order_by(EvidenceLink.created_at.desc()).offset(offset).limit(limit).all()
        return total, rows

    # ------------------------------------------------------------------
    # Workspace intake configuration
    # ------------------------------------------------------------------

    def create_workspace_profile(
        self,
        *,
        space_id: str,
        workspace_id: str,
        name: str,
        observation_policy: str = "manual",
        routing_policy: dict | None = None,
        filters: dict | None = None,
        extraction_policy: dict | None = None,
        context_policy: dict | None = None,
        created_by_user_id: str | None = None,
    ) -> WorkspaceIntakeProfile:
        _validate_choice("observation_policy", observation_policy, _WORKSPACE_OBSERVATION_POLICIES)
        workspace = self.db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.space_id == space_id).first()
        if workspace is None:
            raise IntakeNotFound(workspace_id)
        existing = (
            self.db.query(WorkspaceIntakeProfile)
            .filter(WorkspaceIntakeProfile.space_id == space_id, WorkspaceIntakeProfile.workspace_id == workspace_id)
            .first()
        )
        if existing:
            raise IntakeDuplicateError("workspace already has an intake profile")
        row = WorkspaceIntakeProfile(
            space_id=space_id,
            workspace_id=workspace_id,
            name=name.strip()[:256],
            observation_policy=observation_policy,
            routing_policy_json=dict(routing_policy or {}),
            filters_json=dict(filters or {}),
            extraction_policy_json=dict(extraction_policy or {}),
            context_policy_json=dict(context_policy or {}),
            created_by_user_id=created_by_user_id,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def list_workspace_profiles(self, space_id: str, *, workspace_id: str | None = None) -> list[WorkspaceIntakeProfile]:
        q = self.db.query(WorkspaceIntakeProfile).filter(WorkspaceIntakeProfile.space_id == space_id)
        if workspace_id:
            q = q.filter(WorkspaceIntakeProfile.workspace_id == workspace_id)
        return q.order_by(WorkspaceIntakeProfile.created_at.desc()).all()

    def create_workspace_binding(
        self,
        *,
        space_id: str,
        workspace_id: str,
        source_connection_id: str,
        binding_key: str = "default",
        project_id: str | None = None,
        priority: int = 0,
        filters: dict | None = None,
        routing_policy: dict | None = None,
        extraction_policy: dict | None = None,
        created_by_user_id: str | None = None,
    ) -> WorkspaceSourceBinding:
        workspace = self.db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.space_id == space_id).first()
        if workspace is None:
            raise IntakeNotFound(workspace_id)
        normalized_binding_key = (binding_key or "default").strip()[:128] or "default"
        if project_id:
            if not self.db.query(Project).filter(Project.id == project_id, Project.space_id == space_id).first():
                raise IntakeNotFound(project_id)
            link = (
                self.db.query(ProjectWorkspace)
                .filter(
                    ProjectWorkspace.project_id == project_id,
                    ProjectWorkspace.workspace_id == workspace_id,
                )
                .first()
            )
            if link is None:
                raise IntakeValidationError("Project is not linked to the workspace")
        self.get_connection(space_id, source_connection_id)
        row = WorkspaceSourceBinding(
            space_id=space_id,
            workspace_id=workspace_id,
            project_id=project_id,
            source_connection_id=source_connection_id,
            binding_key=normalized_binding_key,
            priority=priority,
            filters_json=dict(filters or {}),
            routing_policy_json=dict(routing_policy or {}),
            extraction_policy_json=dict(extraction_policy or {}),
            created_by_user_id=created_by_user_id,
        )
        with self.db.begin_nested() as sp:
            try:
                self.db.add(row)
                self.db.flush()
                return row
            except IntegrityError as exc:
                sp.rollback()
                raise IntakeDuplicateError("workspace source binding already exists") from exc

    def list_workspace_bindings(
        self,
        space_id: str,
        *,
        workspace_id: str | None = None,
        source_connection_id: str | None = None,
    ) -> list[WorkspaceSourceBinding]:
        q = self.db.query(WorkspaceSourceBinding).filter(WorkspaceSourceBinding.space_id == space_id)
        if workspace_id:
            q = q.filter(WorkspaceSourceBinding.workspace_id == workspace_id)
        if source_connection_id:
            q = q.filter(WorkspaceSourceBinding.source_connection_id == source_connection_id)
        return q.order_by(WorkspaceSourceBinding.priority.desc(), WorkspaceSourceBinding.created_at.desc()).all()

    # ------------------------------------------------------------------
    # Boundaries
    # ------------------------------------------------------------------

    def assert_no_durable_mutation_side_effects(self, space_id: str, before: dict[str, int]) -> None:
        after = {
            "memory": self.db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count(),
            "knowledge": self.db.query(KnowledgeItem).filter(KnowledgeItem.space_id == space_id).count(),
            "proposals": self.db.query(Proposal).filter(Proposal.space_id == space_id).count(),
            "policies": self.db.query(Policy).filter(Policy.space_id == space_id).count(),
            "tasks": self.db.query(Task).filter(Task.space_id == space_id).count(),
        }
        comparable_after = {key: after[key] for key in before}
        if comparable_after != before:
            raise RuntimeError(f"Intake boundary violation: before={before!r} after={after!r}")

    def _record_activity(self, *, space_id: str, activity_type: str, title: str, payload: dict) -> None:
        record = ActivityRecord(
            space_id=space_id,
            activity_type=activity_type,
            source_kind="intake",
            source_trust="internal_system",
            title=title[:512],
            payload_json={**payload, "kind": "intake_provenance"},
            status="processed",
            lifecycle_status="active",
            consolidation_status="skipped",
            visibility="space_shared",
        )
        self.db.add(record)
        self.db.flush()
