#!/usr/bin/env python3
"""
Circuit-Breaker Pattern for F1 Telemetry Streams
==================================================
Developed for the 2026 Telemetry Platform Initiative.

Implements a three-state circuit breaker (CLOSED → OPEN → HALF_OPEN) that
protects the simulation-ready data pipeline from corrupted or drifted
telemetry packets.  Bad data is isolated to a Dead Letter Queue (DLQ)
while the primary pit-wall feed remains clean.

Architecture
------------
              ┌─────────┐   failures >= threshold   ┌────────┐
              │ CLOSED  │ ────────────────────────►  │  OPEN  │
              │ (relay) │                            │ (block)│
              └────┬────┘  ◄──────────────────────── └───┬────┘
                   │          probe succeeds              │
                   │       ┌───────────┐                  │
                   └──────►│ HALF_OPEN │◄─────────────────┘
                           │  (probe)  │  after cooldown
                           └───────────┘
"""

from __future__ import annotations

import enum
import json
import logging
import sqlite3
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_KAFKA_EVENT_VERSION = "1.0"
DEFAULT_KAFKA_PRODUCER_CONFIG: Dict[str, Any] = {
    "acks": "all",
    "retries": 3,
    "max_in_flight_requests_per_connection": 5,
    "linger_ms": 10,
    "batch_size": 64 * 1024,
    "compression_type": "lz4",
    "request_timeout_ms": 30_000,
    "max_block_ms": 5_000,
}


def _default_kafka_key_serializer(key: Any) -> bytes:
    if isinstance(key, bytes):
        return key
    return str(key).encode("utf-8")


# ---------------------------------------------------------------------------
# Optional Kafka dependency
# ---------------------------------------------------------------------------
try:
    from kafka import KafkaProducer  # type: ignore
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    KafkaProducer = None  # type: ignore


# ---------------------------------------------------------------------------
# Circuit-Breaker States
# ---------------------------------------------------------------------------
class CircuitState(enum.Enum):
    """Three canonical states of the circuit breaker."""
    CLOSED = "CLOSED"         # Normal operation — packets flow through
    OPEN = "OPEN"             # Tripped — all packets routed to DLQ
    HALF_OPEN = "HALF_OPEN"   # Recovery probe — testing a limited batch


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------
@dataclass
class TelemetryPacket:
    """Single telemetry observation from the car."""
    packet_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    sensor: str = ""
    value: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    request_id: str = ""  # Correlation ID for end-to-end tracing


@dataclass
class DLQRecord:
    """A packet quarantined in the Dead Letter Queue."""
    packet: TelemetryPacket
    reason: str
    circuit_state: str
    quarantined_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    retry_count: int = 0


@dataclass
class CircuitBreakerMetrics:
    """Live metrics exposed to the Health Monitor."""
    state: str = CircuitState.CLOSED.value
    consecutive_failures: int = 0
    total_passed: int = 0
    total_rejected: int = 0
    total_dlq: int = 0
    last_failure_time: Optional[str] = None
    last_state_change: Optional[str] = None
    uptime_ratio: float = 1.0


# ---------------------------------------------------------------------------
# Validators — pluggable checks for Schema Drift & Bit-Flip Detection
# ---------------------------------------------------------------------------
class SchemaValidator:
    """
    Schema-on-Read guard.

    Validates that incoming telemetry conforms to the expected field types
    and value ranges.  Catches the two primary corruption modes:

    1. **Schema Drift** — field names or types change between firmware versions.
    2. **Bit-Flip / Sensor Fault** — values exceed physically plausible bounds.
    """

    # Physically plausible ranges for F1 telemetry sensors (SI units)
    DEFAULT_RANGES: Dict[str, Tuple[float, float]] = {
        "speed":               (0.0, 380.0),       # km/h
        "rpm":                 (0.0, 16_000.0),
        "throttle":            (0.0, 100.0),        # %
        "brake":               (0.0, 100.0),        # %
        "gear":                (0.0, 9.0),
        "drs":                 (0.0, 14.0),
        "engine_temp":         (-40.0, 1000.0),     # °C
        "engine_temperature":  (-40.0, 1000.0),
        "tyre_pressure":       (15.0, 35.0),        # psi
        "brake_temp":          (50.0, 1200.0),      # °C
        "ecu_canbus":          (-1e6, 1e6),
        "aero_load":           (-500.0, 3000.0),    # N
        "heart_rate":          (30.0, 250.0),       # bpm (driver biometrics)
        "g_force_lateral":     (-8.0, 8.0),         # G
        "g_force_longitudinal": (-8.0, 8.0),
        "g_force_vertical":    (-5.0, 5.0),
    }

    def __init__(
        self,
        expected_fields: Optional[List[str]] = None,
        value_ranges: Optional[Dict[str, Tuple[float, float]]] = None,
    ):
        self.expected_fields = expected_fields or []
        self.value_ranges = {**self.DEFAULT_RANGES, **(value_ranges or {})}
        # Match specific sensor keys before generic ones (e.g. "brake_temp"
        # before "brake") to avoid false range validation.
        self._range_keys = sorted(self.value_ranges.keys(), key=len, reverse=True)

    # ------------------------------------------------------------------
    def validate_packet(self, packet: TelemetryPacket) -> Tuple[bool, str]:
        """
        Returns (is_valid, reason).
        """
        sensor = packet.sensor.lower().replace(" ", "_").replace("(", "").replace(")", "")

        # --- Explicit duplicate timestamp marker -----------------
        if isinstance(packet.metadata, dict) and packet.metadata.get("duplicate_timestamp"):
            return False, (
                f"duplicate_timestamp|sensor={packet.sensor}|timestamp={packet.timestamp}"
            )

        # --- Null / missing value ----------------------------------
        if packet.value is None:
            return False, f"null_value|sensor={packet.sensor}"

        # --- Type guard: sensor values must be numeric -------------
        if isinstance(packet.value, str):
            return False, f"string_in_numeric_field|sensor={packet.sensor}|value={packet.value}"

        # --- Range check (bit-flip / impossible reading) -----------
        for key in self._range_keys:
            lo, hi = self.value_ranges[key]
            if key in sensor:
                try:
                    v = float(packet.value)
                    if v < lo or v > hi:
                        return False, (
                            f"out_of_range|sensor={packet.sensor}"
                            f"|value={v}|expected=[{lo},{hi}]"
                        )
                except (ValueError, TypeError):
                    return False, f"non_numeric|sensor={packet.sensor}|value={packet.value}"
                break

        return True, "OK"


class TemporalSequenceValidator:
    """Detect duplicate timestamps within a bounded per-session window."""

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self._seen_timestamps: Dict[str, deque[str]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _session_key(packet: TelemetryPacket) -> str:
        metadata = packet.metadata if isinstance(packet.metadata, dict) else {}
        for key in ("session_id", "session"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                return value
        return "global"

    def validate(
        self, packet: TelemetryPacket, record: bool = True
    ) -> Tuple[bool, Optional[str]]:
        timestamp = packet.timestamp
        if not timestamp:
            return True, None

        session_key = self._session_key(packet)
        with self._lock:
            window = self._seen_timestamps.get(session_key)
            if window is None:
                window = deque(maxlen=self.window_size)
                self._seen_timestamps[session_key] = window

            if timestamp in window:
                return False, "duplicate_timestamp"

            if record:
                window.append(timestamp)
            return True, None

    def reset(self) -> None:
        with self._lock:
            self._seen_timestamps.clear()


class StrictTypeValidator:
    """Enforce exact runtime types for sensor values (no coercion)."""

    def __init__(self, field_types: Dict[str, Any]):
        self.field_types = {
            self._normalise_field_name(str(field)): expected
            for field, expected in field_types.items()
        }

    @staticmethod
    def _normalise_field_name(field: str) -> str:
        return (
            field.lower()
            .replace(" ", "_")
            .replace("(", "")
            .replace(")", "")
        )

    def validate(self, packet: TelemetryPacket) -> Tuple[bool, Optional[str]]:
        if packet.value is None:
            return True, None

        field = self._normalise_field_name(packet.sensor)
        expected_type = self.field_types.get(field)
        if expected_type is None:
            return True, None

        if not isinstance(packet.value, expected_type):
            return False, f"type_violation:{field}"

        return True, None


class SensorCadenceMonitor:
    """Detect anomalous per-sensor timing gaps before GPU processing."""

    def __init__(
        self,
        baseline_intervals: Optional[Dict[str, float]] = None,
        cadence_tolerance: float = 3.0,
        history_size: int = 16,
    ):
        self.cadence_tolerance = cadence_tolerance
        self.history_size = history_size
        self._baseline_intervals: Dict[str, float] = {}
        self._last_seen_ms: Dict[str, float] = {}
        self._rolling_intervals: Dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self.configure(baseline_intervals or {}, cadence_tolerance=cadence_tolerance)

    @staticmethod
    def _normalise_sensor(sensor_id: str) -> str:
        return (
            sensor_id.lower()
            .replace(" ", "_")
            .replace("(", "")
            .replace(")", "")
        )

    @staticmethod
    def _timestamp_to_ms(timestamp: str) -> Optional[float]:
        if not timestamp:
            return None
        try:
            return datetime.fromisoformat(timestamp).timestamp() * 1000.0
        except ValueError:
            return None

    def configure(
        self,
        baseline_intervals: Dict[str, float],
        cadence_tolerance: Optional[float] = None,
    ) -> None:
        with self._lock:
            if cadence_tolerance is not None:
                self.cadence_tolerance = cadence_tolerance
            self._baseline_intervals = {
                self._normalise_sensor(sensor_id): float(interval_ms)
                for sensor_id, interval_ms in baseline_intervals.items()
                if interval_ms and interval_ms > 0.0
            }
            self._last_seen_ms.clear()
            self._rolling_intervals.clear()

    def record(self, sensor_id: str, timestamp_ms: float) -> None:
        sensor_key = self._normalise_sensor(sensor_id)
        with self._lock:
            previous_ms = self._last_seen_ms.get(sensor_key)
            if previous_ms is not None:
                history = self._rolling_intervals.get(sensor_key)
                if history is None:
                    history = deque(maxlen=self.history_size)
                    self._rolling_intervals[sensor_key] = history
                history.append(timestamp_ms - previous_ms)
            self._last_seen_ms[sensor_key] = timestamp_ms

    def check(self, sensor_id: str, timestamp_ms: float) -> Tuple[bool, Optional[str]]:
        sensor_key = self._normalise_sensor(sensor_id)
        with self._lock:
            baseline_ms = self._baseline_intervals.get(sensor_key)
            previous_ms = self._last_seen_ms.get(sensor_key)
            if baseline_ms is None or previous_ms is None:
                return True, None

            observed_interval = timestamp_ms - previous_ms
            if observed_interval > baseline_ms * self.cadence_tolerance:
                return False, f"cadence_violation:{sensor_key}"
            return True, None

    def validate(
        self, packet: TelemetryPacket, record: bool = True
    ) -> Tuple[bool, Optional[str]]:
        timestamp_ms = self._timestamp_to_ms(packet.timestamp)
        if timestamp_ms is None:
            return True, None

        is_valid, reason = self.check(packet.sensor, timestamp_ms)
        if record:
            self.record(packet.sensor, timestamp_ms)
        return is_valid, reason

    def reset(self) -> None:
        with self._lock:
            self._last_seen_ms.clear()
            self._rolling_intervals.clear()


# ---------------------------------------------------------------------------
# Dead Letter Queue — SQLite-backed for crash resilience
# ---------------------------------------------------------------------------
class DeadLetterQueue:
    """
    Persistent quarantine for rejected telemetry packets.

    Uses SQLite WAL mode for concurrent read access from the Health Monitor
    while the pipeline writes.
    """

    DDL = """
    CREATE TABLE IF NOT EXISTS dead_letters (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        packet_id   TEXT    NOT NULL,
        timestamp   TEXT    NOT NULL,
        sensor      TEXT,
        value       TEXT,
        metadata    TEXT,
        reason      TEXT    NOT NULL,
        circuit_state TEXT  NOT NULL,
        quarantined_at TEXT NOT NULL,
        retry_count INTEGER DEFAULT 0,
        reprocessed INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_dl_sensor ON dead_letters(sensor);
    CREATE INDEX IF NOT EXISTS idx_dl_quarantined ON dead_letters(quarantined_at);
    """

    def __init__(
        self,
        db_path: str = "data/dlq.sqlite",
        commit_interval: int = 20,
        enable_kafka: bool = False,
        kafka_bootstrap_servers: Optional[List[str]] = None,
        kafka_topic_repairable: str = "dlq-repairable",
        kafka_topic_repaired: str = "dlq-repaired",
        kafka_topic_non_repairable: str = "dlq-non-repairable",
        kafka_topic_raw: Optional[str] = "telemetry-raw",
        kafka_topic_schema_drift: Optional[str] = "telemetry-schema-drift",
        kafka_topic_alerts: Optional[str] = "telemetry-alerts",
        kafka_producer_config: Optional[Dict[str, Any]] = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=60)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(self.DDL)
        self._lock = threading.Lock()
        self._commit_interval = commit_interval
        self._write_count = 0

        # ------------------------------------------------------------------
        # Kafka routing — three topics for each DLQ outcome
        # ------------------------------------------------------------------
        self.kafka_topic_repairable = kafka_topic_repairable
        self.kafka_topic_repaired = kafka_topic_repaired
        self.kafka_topic_non_repairable = kafka_topic_non_repairable
        self.kafka_topic_raw = kafka_topic_raw
        self.kafka_topic_schema_drift = kafka_topic_schema_drift
        self.kafka_topic_alerts = kafka_topic_alerts
        self.enable_kafka = enable_kafka and KAFKA_AVAILABLE
        self.kafka_producer_config = {
            **DEFAULT_KAFKA_PRODUCER_CONFIG,
            **(kafka_producer_config or {}),
        }
        self._kafka_producer: Optional[KafkaProducer] = None
        self._kafka_sent: int = 0
        self._kafka_failed: int = 0
        self._kafka_latency_total_ms: float = 0.0
        self._kafka_latency_samples: int = 0
        self._kafka_sent_by_topic: Dict[str, int] = {}
        self._kafka_failed_by_topic: Dict[str, int] = {}

        if self.enable_kafka:
            if not KAFKA_AVAILABLE:
                logger.warning(
                    "Kafka requested for DLQ but kafka-python is not installed. "
                    "Install with: pip install kafka-python"
                )
                self.enable_kafka = False
            elif kafka_bootstrap_servers:
                try:
                    self._kafka_producer = KafkaProducer(
                        bootstrap_servers=kafka_bootstrap_servers,
                        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                        key_serializer=_default_kafka_key_serializer,
                        **self.kafka_producer_config,
                    )
                    logger.info(
                        "DLQ Kafka producer initialised | servers=%s "
                        "topics=(%s, %s, %s, raw=%s, drift=%s, alerts=%s)",
                        kafka_bootstrap_servers,
                        kafka_topic_repairable,
                        kafka_topic_repaired,
                        kafka_topic_non_repairable,
                        kafka_topic_raw,
                        kafka_topic_schema_drift,
                        kafka_topic_alerts,
                    )
                except Exception as exc:
                    logger.error("Failed to initialise DLQ Kafka producer: %s", exc)
                    self.enable_kafka = False
            else:
                logger.warning(
                    "Kafka enabled for DLQ but no bootstrap_servers provided"
                )
                self.enable_kafka = False

    # ------------------------------------------------------------------
    def enqueue(self, record: DLQRecord) -> None:
        """Persist a rejected packet (batched commit)."""
        with self._lock:
            self._conn.execute(
                """INSERT INTO dead_letters
                   (packet_id, timestamp, sensor, value, metadata,
                    reason, circuit_state, quarantined_at, retry_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.packet.packet_id,
                    record.packet.timestamp,
                    record.packet.sensor,
                    json.dumps(record.packet.value),
                    json.dumps(record.packet.metadata),
                    record.reason,
                    record.circuit_state,
                    record.quarantined_at,
                    record.retry_count,
                ),
            )
            self._write_count += 1
            if self._write_count >= self._commit_interval:
                self._conn.commit()
                self._write_count = 0

        # Kafka: new quarantined packet is a repairable candidate
        if self.enable_kafka and self._kafka_producer:
            self._publish_to_kafka(
                self._build_event(
                    event_type="dlq.repairable",
                    payload={
                        "packet_id": record.packet.packet_id,
                        "sensor": record.packet.sensor,
                        "value": record.packet.value,
                        "metadata": record.packet.metadata,
                        "reason": record.reason,
                        "circuit_state": record.circuit_state,
                        "retry_count": record.retry_count,
                        "quarantined_at": record.quarantined_at,
                        "outcome": "repairable",
                        "published_at": datetime.utcnow().isoformat(),
                    },
                    source="dead_letter_queue",
                ),
                self.kafka_topic_repairable,
                key=record.packet.packet_id,
            )

    def enqueue_batch(self, records: List[DLQRecord]) -> None:
        """Persist multiple rejected packets in a single transaction."""
        with self._lock:
            for record in records:
                self._conn.execute(
                    """INSERT INTO dead_letters
                       (packet_id, timestamp, sensor, value, metadata,
                        reason, circuit_state, quarantined_at, retry_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.packet.packet_id,
                        record.packet.timestamp,
                        record.packet.sensor,
                        json.dumps(record.packet.value),
                        json.dumps(record.packet.metadata),
                        record.reason,
                        record.circuit_state,
                        record.quarantined_at,
                        record.retry_count,
                    ),
                )
            self._conn.commit()
            self._write_count = 0

        # Kafka: publish all new quarantined packets to the repairable topic
        if self.enable_kafka and self._kafka_producer:
            now = datetime.utcnow().isoformat()
            for record in records:
                self._publish_to_kafka(
                    self._build_event(
                        event_type="dlq.repairable",
                        payload={
                            "packet_id": record.packet.packet_id,
                            "sensor": record.packet.sensor,
                            "value": record.packet.value,
                            "metadata": record.packet.metadata,
                            "reason": record.reason,
                            "circuit_state": record.circuit_state,
                            "retry_count": record.retry_count,
                            "quarantined_at": record.quarantined_at,
                            "outcome": "repairable",
                            "published_at": now,
                        },
                        source="dead_letter_queue",
                    ),
                    self.kafka_topic_repairable,
                    key=record.packet.packet_id,
                )

    def flush(self) -> None:
        """Force-commit any buffered writes to disk."""
        with self._lock:
            if self._write_count > 0:
                self._conn.commit()
                self._write_count = 0

    # ------------------------------------------------------------------
    # Kafka helpers
    # ------------------------------------------------------------------
    def _build_event(self, event_type: str, payload: Dict[str, Any], source: str) -> Dict[str, Any]:
        return {
            "event_type": event_type,
            "event_version": DEFAULT_KAFKA_EVENT_VERSION,
            "source": source,
            "produced_at": datetime.utcnow().isoformat(),
            "payload": payload,
        }

    def _publish_to_kafka(self, payload: Dict[str, Any], topic: Optional[str], key: Optional[str] = None) -> None:
        """Send a DLQ record to a Kafka topic (non-blocking, fire-and-forget)."""
        if not self._kafka_producer or not topic:
            return
        started = time.perf_counter()
        try:
            future = self._kafka_producer.send(topic, key=key, value=payload)
            future.add_callback(lambda _: self._on_kafka_success(topic, started))
            future.add_errback(lambda e: self._on_kafka_error(e, topic))
        except Exception as exc:
            logger.warning("DLQ Kafka send exception (topic=%s): %s", topic, exc)
            self._on_kafka_error(exc, topic)

    def _on_kafka_success(self, topic: str, started: float) -> None:
        self._kafka_sent += 1
        self._kafka_sent_by_topic[topic] = self._kafka_sent_by_topic.get(topic, 0) + 1
        self._kafka_latency_total_ms += (time.perf_counter() - started) * 1000
        self._kafka_latency_samples += 1

    def _on_kafka_error(self, exc: Exception, topic: str) -> None:
        logger.warning("DLQ Kafka send failed to %s: %s", topic, exc)
        self._kafka_failed += 1
        self._kafka_failed_by_topic[topic] = self._kafka_failed_by_topic.get(topic, 0) + 1

    def publish_raw_ingress(self, packet: TelemetryPacket) -> None:
        if not self.enable_kafka or not self._kafka_producer or not self.kafka_topic_raw:
            return

        self._publish_to_kafka(
            self._build_event(
                event_type="telemetry.raw",
                payload={
                    "packet_id": packet.packet_id,
                    "timestamp": packet.timestamp,
                    "sensor": packet.sensor,
                    "value": packet.value,
                    "metadata": packet.metadata,
                    "request_id": packet.request_id,
                },
                source="telemetry_circuit_breaker",
            ),
            self.kafka_topic_raw,
            key=packet.packet_id,
        )

    def publish_validation_failure(
        self,
        packet: TelemetryPacket,
        reason: str,
        circuit_state: str,
    ) -> None:
        if not self.enable_kafka or not self._kafka_producer:
            return

        if self._is_schema_drift_reason(packet, reason):
            self._publish_to_kafka(
                self._build_event(
                    event_type="telemetry.schema_drift",
                    payload={
                        "packet_id": packet.packet_id,
                        "timestamp": packet.timestamp,
                        "sensor": packet.sensor,
                        "value": packet.value,
                        "metadata": packet.metadata,
                        "reason": reason,
                        "circuit_state": circuit_state,
                    },
                    source="telemetry_circuit_breaker",
                ),
                self.kafka_topic_schema_drift,
                key=packet.sensor or packet.packet_id,
            )

    def publish_alert(self, alert_type: str, payload: Dict[str, Any], key: Optional[str] = None) -> None:
        if not self.enable_kafka or not self._kafka_producer or not self.kafka_topic_alerts:
            return

        self._publish_to_kafka(
            self._build_event(
                event_type=f"telemetry.alert.{alert_type}",
                payload=payload,
                source="telemetry_circuit_breaker",
            ),
            self.kafka_topic_alerts,
            key=key or alert_type,
        )

    def _is_schema_drift_reason(self, packet: TelemetryPacket, reason: str) -> bool:
        if packet.sensor.lower().endswith("_new"):
            return True
        return reason.startswith(
            (
                "string_in_numeric_field",
                "non_numeric",
                "duplicate_timestamp",
                "type_violation:",
            )
        )

    def publish_repair_outcome(
        self, rec: Dict[str, Any], outcome: str
    ) -> None:
        """
        Route a DLQ reprocessing result to the appropriate Kafka topic.

        Call this immediately after each repair decision in the reprocessing
        loop — the caller already holds the full ``rec`` dict from
        :meth:`fetch_reprocessable`, so no extra DB round-trip is needed.

        Parameters
        ----------
        rec : dict
            A record dict as returned by :meth:`fetch_reprocessable`.
        outcome : str
            One of:

            * ``"repaired"``        — repair succeeded; packet recovered.
            * ``"non_repairable"``  — max retries exhausted; packet is dead.
            * ``"repairable"``      — repair failed this round but retries remain.
        """
        if not self.enable_kafka or not self._kafka_producer:
            return

        topic_map: Dict[str, str] = {
            "repaired": self.kafka_topic_repaired,
            "non_repairable": self.kafka_topic_non_repairable,
            "repairable": self.kafka_topic_repairable,
        }
        topic = topic_map.get(outcome)
        if topic is None:
            logger.warning(
                "Unknown DLQ repair outcome '%s' for packet %s — skipping Kafka publish",
                outcome,
                rec.get("packet_id"),
            )
            return

        payload = {
            "packet_id": rec.get("packet_id"),
            "sensor": rec.get("sensor"),
            "value": rec.get("value"),
            "reason": rec.get("reason"),
            "retry_count": rec.get("retry_count", 0),
            "outcome": outcome,
            "published_at": datetime.utcnow().isoformat(),
        }
        self._publish_to_kafka(payload, topic)

    @property
    def kafka_stats(self) -> Dict[str, int]:
        """Return sent/failed counts for monitoring."""
        avg_latency_ms = (
            round(self._kafka_latency_total_ms / self._kafka_latency_samples, 3)
            if self._kafka_latency_samples
            else 0.0
        )
        return {
            "sent": self._kafka_sent,
            "failed": self._kafka_failed,
            "avg_latency_ms": avg_latency_ms,
            "sent_by_topic": dict(self._kafka_sent_by_topic),
            "failed_by_topic": dict(self._kafka_failed_by_topic),
        }

    # ------------------------------------------------------------------
    def depth(self) -> int:
        """Number of un-reprocessed records in the queue."""
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM dead_letters WHERE reprocessed = 0"
        )
        return cur.fetchone()[0]

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch the most recent DLQ entries."""
        cur = self._conn.execute(
            "SELECT packet_id, sensor, value, reason, quarantined_at "
            "FROM dead_letters WHERE reprocessed = 0 "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def mark_reprocessed(self, packet_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE dead_letters SET reprocessed = 1 WHERE packet_id = ?",
                (packet_id,),
            )
            self._conn.commit()

    def fetch_reprocessable(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch DLQ records eligible for reprocessing.

        Returns packets that have NOT yet been reprocessed and whose
        retry_count is below the max (default 3).
        """
        cur = self._conn.execute(
            "SELECT id, packet_id, timestamp, sensor, value, metadata, reason, "
            "retry_count FROM dead_letters "
            "WHERE reprocessed = 0 AND retry_count < 3 "
            "ORDER BY id LIMIT ?",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def increment_retry(self, packet_id: str) -> None:
        """Bump the retry count for a DLQ record."""
        with self._lock:
            self._conn.execute(
                "UPDATE dead_letters SET retry_count = retry_count + 1 WHERE packet_id = ?",
                (packet_id,),
            )
            self._conn.commit()

    def close(self) -> None:
        self.flush()  # Commit any pending writes before closing
        if self._kafka_producer:
            try:
                self._kafka_producer.flush(timeout=5)
                self._kafka_producer.close()
            except Exception as exc:
                logger.warning("Error closing DLQ Kafka producer: %s", exc)
        self._conn.close()


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------
class TelemetryCircuitBreaker:
    """
    Production circuit breaker for the Telemetry Platform telemetry spine.

    Parameters
    ----------
    failure_threshold : int
        Consecutive bad packets before the breaker trips to OPEN.
    recovery_timeout : float
        Seconds to wait in OPEN before transitioning to HALF_OPEN.
    half_open_max_calls : int
        Number of probe packets allowed in HALF_OPEN before deciding.
    dlq_path : str
        File-system path for the SQLite Dead Letter Queue.
    validator : SchemaValidator | None
        Pluggable validation strategy.  Defaults to F1 telemetry ranges.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
        dlq_path: str = "data/dlq.sqlite",
        validator: Optional[SchemaValidator] = None,
        temporal_validator: Optional[TemporalSequenceValidator] = None,
        strict_type_validator: Optional[StrictTypeValidator] = None,
        enable_kafka: bool = False,
        kafka_bootstrap_servers: Optional[List[str]] = None,
        kafka_topic_repairable: str = "dlq-repairable",
        kafka_topic_repaired: str = "dlq-repaired",
        kafka_topic_non_repairable: str = "dlq-non-repairable",
        kafka_topic_raw: Optional[str] = "telemetry-raw",
        kafka_topic_schema_drift: Optional[str] = "telemetry-schema-drift",
        kafka_topic_alerts: Optional[str] = "telemetry-alerts",
        kafka_producer_config: Optional[Dict[str, Any]] = None,
    ):
        self._state = CircuitState.CLOSED
        self._lock = threading.Lock()

        # Thresholds
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        # Counters
        self._consecutive_failures = 0
        self._half_open_successes = 0
        self._half_open_calls = 0
        self._total_passed = 0
        self._total_rejected = 0

        # Timestamps
        self._last_failure_time: Optional[float] = None
        self._last_state_change: Optional[str] = None
        self._opened_at: Optional[float] = None
        self._start_time = time.time()

        # Dependencies
        self.validator = validator or SchemaValidator()
        self.temporal_validator = temporal_validator or TemporalSequenceValidator(
            window_size=100
        )
        strict_defaults = {
            key: float for key in SchemaValidator.DEFAULT_RANGES.keys()
        }
        self.strict_type_validator = strict_type_validator or StrictTypeValidator(
            field_types=strict_defaults
        )
        self.cadence_monitor = SensorCadenceMonitor(baseline_intervals={})
        self._pre_breaker_validators = [
            self.temporal_validator,
            self.strict_type_validator,
            self.cadence_monitor,
        ]
        self.dlq = DeadLetterQueue(
            db_path=dlq_path,
            enable_kafka=enable_kafka,
            kafka_bootstrap_servers=kafka_bootstrap_servers,
            kafka_topic_repairable=kafka_topic_repairable,
            kafka_topic_repaired=kafka_topic_repaired,
            kafka_topic_non_repairable=kafka_topic_non_repairable,
            kafka_topic_raw=kafka_topic_raw,
            kafka_topic_schema_drift=kafka_topic_schema_drift,
            kafka_topic_alerts=kafka_topic_alerts,
            kafka_producer_config=kafka_producer_config,
        )

        # Event hooks (for Health Monitor)
        self._on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None
        self._on_reject: Optional[Callable[[DLQRecord], None]] = None

        logger.info(
            "CircuitBreaker initialised | threshold=%d recovery=%.1fs kafka=%s",
            failure_threshold, recovery_timeout, enable_kafka,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    @property
    def metrics(self) -> CircuitBreakerMetrics:
        with self._lock:
            total = self._total_passed + self._total_rejected
            uptime = self._total_passed / total if total > 0 else 1.0
            return CircuitBreakerMetrics(
                state=self._state.value,
                consecutive_failures=self._consecutive_failures,
                total_passed=self._total_passed,
                total_rejected=self._total_rejected,
                total_dlq=self.dlq.depth(),
                last_failure_time=(
                    datetime.fromtimestamp(self._last_failure_time).isoformat()
                    if self._last_failure_time else None
                ),
                last_state_change=self._last_state_change,
                uptime_ratio=round(uptime, 4),
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def validate_packet(
        self, packet: TelemetryPacket, record_temporal: bool = True
    ) -> Tuple[bool, str]:
        """
        Run pre-breaker validators then schema/range validation.

        Pre-breaker validator failures are routed to DLQ but do not count as
        breaker-state transition failures.
        """
        for validator in self._pre_breaker_validators:
            if isinstance(validator, (TemporalSequenceValidator, SensorCadenceMonitor)):
                is_valid, reason = validator.validate(packet, record=record_temporal)
            else:
                is_valid, reason = validator.validate(packet)
            if not is_valid:
                return False, reason or "validation_failed"

        return self.validator.validate_packet(packet)

    def process(self, packet: TelemetryPacket) -> Tuple[bool, str]:
        """
        Submit a telemetry packet to the circuit breaker.

        Returns
        -------
        (accepted, reason) — True if the packet was forwarded to the
        primary pipeline; False if it was routed to the DLQ.
        """
        with self._lock:
            self.dlq.publish_raw_ingress(packet)
            self._maybe_transition_to_half_open()

            # ---- OPEN: reject everything until cooldown expires ----
            if self._state == CircuitState.OPEN:
                return self._reject(packet, "circuit_open")

            # ---- Validate the packet --------------------------------
            is_valid, reason = self.validate_packet(packet, record_temporal=False)

            if is_valid:
                return self._on_success(packet)
            else:
                pre_breaker_failure = (
                    reason == "duplicate_timestamp"
                    or reason.startswith("type_violation:")
                    or reason.startswith("cadence_violation:")
                )
                if pre_breaker_failure:
                    return self._reject(packet, reason)
                return self._on_failure(packet, reason)

    def process_batch(self, packets: List[TelemetryPacket]) -> Dict[str, int]:
        """
        Process a list of packets.  Returns summary counts.

        Acquires the lock once for the entire batch and flushes
        DLQ writes at the end, reducing per-packet overhead.
        """
        accepted = 0
        rejected = 0
        with self._lock:
            self._maybe_transition_to_half_open()
            for pkt in packets:
                self.dlq.publish_raw_ingress(pkt)
                # ---- OPEN: reject everything until cooldown expires ----
                if self._state == CircuitState.OPEN:
                    self._total_rejected += 1
                    record = DLQRecord(
                        packet=pkt, reason="circuit_open",
                        circuit_state=self._state.value,
                    )
                    self.dlq.enqueue(record)
                    if self._on_reject:
                        self._on_reject(record)
                    rejected += 1
                    continue

                is_valid, reason = self.validate_packet(pkt)
                if is_valid:
                    self._total_passed += 1
                    if self._state == CircuitState.HALF_OPEN:
                        self._half_open_successes += 1
                        self._half_open_calls += 1
                        if self._half_open_successes >= self.half_open_max_calls:
                            self._transition(CircuitState.CLOSED)
                            self._consecutive_failures = 0
                    else:
                        self._consecutive_failures = 0
                    accepted += 1
                else:
                    pre_breaker_failure = (
                        reason == "duplicate_timestamp"
                        or reason.startswith("type_violation:")
                        or reason.startswith("cadence_violation:")
                    )
                    if pre_breaker_failure:
                        self._total_rejected += 1
                        if isinstance(pkt.metadata, dict):
                            pkt.metadata.setdefault("chaos_mode", reason)
                        record = DLQRecord(
                            packet=pkt, reason=reason,
                            circuit_state=self._state.value,
                        )
                        self.dlq.enqueue(record)
                        if self._on_reject:
                            self._on_reject(record)
                        rejected += 1
                        continue

                    self._consecutive_failures += 1
                    self._last_failure_time = time.time()
                    if self._state == CircuitState.HALF_OPEN:
                        self._transition(CircuitState.OPEN)
                    elif self._consecutive_failures >= self.failure_threshold:
                        self._transition(CircuitState.OPEN)
                    self._total_rejected += 1
                    record = DLQRecord(
                        packet=pkt, reason=reason,
                        circuit_state=self._state.value,
                    )
                    self.dlq.enqueue(record)
                    if self._on_reject:
                        self._on_reject(record)
                    rejected += 1
        # Flush any buffered DLQ writes after the batch
        self.dlq.flush()
        return {"accepted": accepted, "rejected": rejected}

    def configure_cadence_monitor(
        self,
        baseline_intervals: Dict[str, float],
        cadence_tolerance: float = 3.0,
    ) -> None:
        """Configure per-sensor cadence baselines without changing process APIs."""
        self.cadence_monitor.configure(
            baseline_intervals=baseline_intervals,
            cadence_tolerance=cadence_tolerance,
        )

    def reset(self) -> None:
        """Force-close the breaker (manual override from pit wall)."""
        with self._lock:
            old = self._state
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._half_open_calls = 0
            self._half_open_successes = 0
            self._record_state_change(old, CircuitState.CLOSED)
            for validator in self._pre_breaker_validators:
                reset_fn = getattr(validator, "reset", None)
                if callable(reset_fn):
                    reset_fn()
            self.dlq.publish_alert(
                "reset",
                {"old_state": old.value, "new_state": CircuitState.CLOSED.value},
                key="circuit-reset",
            )
        logger.info("CircuitBreaker manually RESET → CLOSED")

    def reprocess_dlq(self, limit: int = 50) -> Dict[str, int]:
        """
        Re-validate quarantined packets from the Dead Letter Queue.

        Packets whose sensor data now falls within acceptable ranges (e.g.
        after a validator range update or a firmware correction) are
        re-admitted to the pipeline.  Packets that still fail validation
        have their retry_count incremented.

        Parameters
        ----------
        limit : int
            Maximum number of DLQ records to attempt in one pass.

        Returns
        -------
        dict with keys ``recovered``, ``still_invalid``, ``max_retries``.
        """
        candidates = self.dlq.fetch_reprocessable(limit=limit)
        recovered = 0
        still_invalid = 0
        max_retries = 0

        for rec in candidates:
            packet = TelemetryPacket(
                packet_id=rec["packet_id"],
                timestamp=rec["timestamp"],
                sensor=rec["sensor"] or "",
                value=json.loads(rec["value"]) if isinstance(rec["value"], str) else rec["value"],
                metadata=json.loads(rec["metadata"]) if isinstance(rec["metadata"], str) else (rec["metadata"] or {}),
            )

            is_valid, reason = self.validate_packet(packet, record_temporal=False)

            if is_valid:
                self.dlq.mark_reprocessed(rec["packet_id"])
                self._total_passed += 1
                self.dlq.publish_alert(
                    "recovered",
                    {
                        "packet_id": rec["packet_id"],
                        "sensor": rec.get("sensor"),
                        "retry_count": rec.get("retry_count", 0),
                    },
                    key=rec["packet_id"],
                )
                recovered += 1
                logger.info("DLQ packet %s recovered via reprocessing", rec["packet_id"])
            else:
                self.dlq.increment_retry(rec["packet_id"])
                retry_count = rec.get("retry_count", 0) + 1
                if retry_count >= 3:
                    self.dlq.publish_alert(
                        "non_repairable",
                        {
                            "packet_id": rec["packet_id"],
                            "sensor": rec.get("sensor"),
                            "reason": reason,
                            "retry_count": retry_count,
                        },
                        key=rec["packet_id"],
                    )
                    max_retries += 1
                else:
                    self.dlq.publish_validation_failure(packet, reason, self._state.value)
                    still_invalid += 1

        logger.info(
            "DLQ reprocessing complete: recovered=%d still_invalid=%d max_retries=%d",
            recovered, still_invalid, max_retries,
        )
        return {
            "recovered": recovered,
            "still_invalid": still_invalid,
            "max_retries": max_retries,
        }

    # ------------------------------------------------------------------
    # Internal state machine
    # ------------------------------------------------------------------
    def _on_success(self, packet: TelemetryPacket) -> Tuple[bool, str]:
        self._total_passed += 1

        if self._state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            self._half_open_calls += 1
            if self._half_open_successes >= self.half_open_max_calls:
                self._transition(CircuitState.CLOSED)
                self._consecutive_failures = 0
        else:
            # CLOSED — reset failure counter on each success
            self._consecutive_failures = 0

        return True, "OK"

    def _on_failure(self, packet: TelemetryPacket, reason: str) -> Tuple[bool, str]:
        self._consecutive_failures += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # Probe failed — reopen immediately
            self._transition(CircuitState.OPEN)
            return self._reject(packet, reason)

        if self._consecutive_failures >= self.failure_threshold:
            self._transition(CircuitState.OPEN)

        return self._reject(packet, reason)

    def _reject(self, packet: TelemetryPacket, reason: str) -> Tuple[bool, str]:
        self._total_rejected += 1
        if isinstance(packet.metadata, dict):
            packet.metadata.setdefault("chaos_mode", reason)
        record = DLQRecord(
            packet=packet,
            reason=reason,
            circuit_state=self._state.value,
        )
        self.dlq.enqueue(record)
        self.dlq.publish_validation_failure(packet, reason, self._state.value)
        self.dlq.publish_alert(
            "validation_failure",
            {
                "packet_id": packet.packet_id,
                "sensor": packet.sensor,
                "reason": reason,
                "circuit_state": self._state.value,
            },
            key=packet.packet_id,
        )

        if self._on_reject:
            self._on_reject(record)

        return False, reason

    def _transition(self, new_state: CircuitState) -> None:
        old = self._state
        self._state = new_state
        if new_state == CircuitState.OPEN:
            self._opened_at = time.time()
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._half_open_successes = 0
        self._record_state_change(old, new_state)
        logger.info("CircuitBreaker %s → %s", old.value, new_state.value)
        self.dlq.publish_alert(
            "state_change",
            {
                "old_state": old.value,
                "new_state": new_state.value,
                "consecutive_failures": self._consecutive_failures,
            },
            key=f"{old.value}-{new_state.value}",
        )

        if self._on_state_change:
            self._on_state_change(old, new_state)

    def _maybe_transition_to_half_open(self) -> None:
        """Auto-promote from OPEN → HALF_OPEN after the recovery timeout."""
        if (
            self._state == CircuitState.OPEN
            and self._opened_at is not None
            and (time.time() - self._opened_at) >= self.recovery_timeout
        ):
            self._transition(CircuitState.HALF_OPEN)

    def _record_state_change(self, old: CircuitState, new: CircuitState) -> None:
        self._last_state_change = (
            f"{old.value}→{new.value} @ {datetime.utcnow().isoformat()}"
        )
