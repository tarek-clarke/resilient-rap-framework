#!/usr/bin/env python3
"""
Local-First Persistence Layer (Trackside Edge Buffer)
======================================================
Developed for the 2026 Telemetry Platform Initiative.

Guarantees zero data loss during trackside connectivity drops by persisting
every telemetry packet to a local SQLite WAL database before attempting the
cloud sync.  This is the "write-ahead" layer that sits between the car's
RF downlink and the global data sink.

Architecture
------------
    Car RF  ──►  Edge Buffer (SQLite WAL)  ──►  Cloud Sink (async drain)
                      │
                 Local replay always available
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from kafka import KafkaProducer
    from kafka.errors import KafkaError
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    KafkaProducer = None
    KafkaError = None

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
# Data Structures
# ---------------------------------------------------------------------------
class SyncStatus(Enum):
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    FAILED = "FAILED"


@dataclass
class BufferedPacket:
    """A telemetry packet stored in the local buffer."""
    packet_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    sensor: str = ""
    value: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    sync_status: str = SyncStatus.PENDING.value


@dataclass
class BufferHealth:
    """Real-time health metrics for the edge buffer."""
    total_buffered: int = 0
    pending_sync: int = 0
    synced: int = 0
    failed: int = 0
    buffer_utilisation: float = 0.0      # 0.0–1.0
    last_write_time: Optional[str] = None
    last_sync_time: Optional[str] = None
    connectivity: bool = True
    db_size_bytes: int = 0


# ---------------------------------------------------------------------------
# Edge Buffer
# ---------------------------------------------------------------------------
class TracksideEdgeBuffer:
    """
    SQLite WAL-backed write-ahead buffer for F1 telemetry.

    Every packet is persisted locally *before* any cloud sync is attempted.
    If the uplink drops, the buffer accumulates and drains automatically
    when connectivity is restored.

    Parameters
    ----------
    db_path : str
        Path for the SQLite database.
    max_buffer_size : int
        Soft cap (rows) before the buffer raises a back-pressure warning.
    sync_callback : callable | None
        Async function called to push packets to the global sink.
        Signature: ``(List[Dict]) -> bool``  (returns True on success).
    batch_size : int
        Number of packets to drain per sync cycle.
    """

    DDL = """
    CREATE TABLE IF NOT EXISTS telemetry_buffer (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        packet_id   TEXT    UNIQUE NOT NULL,
        session_id  TEXT,
        timestamp   TEXT    NOT NULL,
        sensor      TEXT,
        value       TEXT,
        metadata    TEXT,
        sync_status TEXT    DEFAULT 'PENDING',
        created_at  TEXT    DEFAULT (datetime('now')),
        synced_at   TEXT,
        drain_batch_id TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_buf_sync ON telemetry_buffer(sync_status);
    CREATE INDEX IF NOT EXISTS idx_buf_session ON telemetry_buffer(session_id);
    CREATE INDEX IF NOT EXISTS idx_buf_drain ON telemetry_buffer(drain_batch_id);

    CREATE TABLE IF NOT EXISTS drain_batches (
        batch_id    TEXT    PRIMARY KEY,
        created_at  TEXT    NOT NULL,
        packet_count INTEGER NOT NULL,
        status      TEXT    DEFAULT 'DRAINING',
        acked_at    TEXT
    );
    """

    def __init__(
        self,
        db_path: str = "data/edge_buffer.sqlite",
        max_buffer_size: int = 100_000,
        sync_callback: Optional[Callable] = None,
        batch_size: int = 500,
        kafka_bootstrap_servers: Optional[List[str]] = None,
        kafka_topic: str = "telemetry-validated",
        kafka_dlq_topic: str = "telemetry-dlq",
        kafka_sync_event_topic: Optional[str] = "telemetry-sync-events",
        kafka_producer_config: Optional[Dict[str, Any]] = None,
        enable_kafka: bool = False,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_buffer_size = max_buffer_size
        self.sync_callback = sync_callback
        self.batch_size = batch_size

        # Kafka configuration
        self.enable_kafka = enable_kafka and KAFKA_AVAILABLE
        self.kafka_topic = kafka_topic
        self.kafka_dlq_topic = kafka_dlq_topic
        self.kafka_sync_event_topic = kafka_sync_event_topic
        self.kafka_producer_config = {
            **DEFAULT_KAFKA_PRODUCER_CONFIG,
            **(kafka_producer_config or {}),
        }
        self._kafka_producer: Optional[KafkaProducer] = None

        if self.enable_kafka:
            if not KAFKA_AVAILABLE:
                logger.warning("Kafka requested but kafka-python not installed. Install with: pip install kafka-python")
                self.enable_kafka = False
            elif kafka_bootstrap_servers:
                try:
                    self._kafka_producer = KafkaProducer(
                        bootstrap_servers=kafka_bootstrap_servers,
                        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                        key_serializer=_default_kafka_key_serializer,
                        **self.kafka_producer_config,
                    )
                    logger.info(
                        "Kafka producer initialized | servers=%s topic=%s dlq=%s sync=%s",
                        kafka_bootstrap_servers, kafka_topic, kafka_dlq_topic,
                        kafka_sync_event_topic,
                    )
                except Exception as exc:
                    logger.error("Failed to initialize Kafka producer: %s", exc)
                    self.enable_kafka = False
            else:
                logger.warning("Kafka enabled but no bootstrap_servers provided")
                self.enable_kafka = False

        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=60)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.executescript(self.DDL)
        self._lock = threading.Lock()

        self._last_write_time: Optional[str] = None
        self._last_sync_time: Optional[str] = None
        self._connectivity = True

        # Write-behind buffer for batched commits
        self._commit_interval = 50
        self._write_count = 0

        # Background drain thread
        self._drain_active = False
        self._drain_thread: Optional[threading.Thread] = None

        # Kafka stats
        self._kafka_sent = 0
        self._kafka_failed = 0
        self._kafka_latency_total_ms = 0.0
        self._kafka_latency_samples = 0
        self._kafka_sent_by_topic: Dict[str, int] = {}
        self._kafka_failed_by_topic: Dict[str, int] = {}

        logger.info(
            "TracksideEdgeBuffer online | db=%s max=%d kafka=%s",
            self.db_path, self.max_buffer_size, self.enable_kafka,
        )

    # -----------------------------------------------------------------
    # Write Path — guaranteed local persistence + optional Kafka output
    # -----------------------------------------------------------------
    def write(self, packet: BufferedPacket) -> None:
        """Persist a single telemetry packet to the local buffer.

        Writes are batched: ``commit()`` is deferred until
        ``_commit_interval`` packets have accumulated (default 50).
        Call :meth:`flush` to force an immediate commit.

        If Kafka is enabled, also publishes to Kafka topic (fire-and-forget,
        non-blocking). SQLite write still succeeds even if Kafka fails.
        """
        with self._lock:
            self._conn.execute(
                """INSERT OR IGNORE INTO telemetry_buffer
                   (packet_id, session_id, timestamp, sensor, value, metadata, sync_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    packet.packet_id,
                    packet.session_id,
                    packet.timestamp,
                    packet.sensor,
                    json.dumps(packet.value),
                    json.dumps(packet.metadata),
                    packet.sync_status,
                ),
            )
            self._write_count += 1
            if self._write_count >= self._commit_interval:
                self._conn.commit()
                self._write_count = 0
            self._last_write_time = datetime.utcnow().isoformat()

        # Kafka output (async, non-blocking)
        if self.enable_kafka and self._kafka_producer:
            self._send_to_kafka(packet)

    def _send_to_kafka(self, packet: BufferedPacket, is_dlq: bool = False) -> None:
        """Send packet to Kafka topic (non-blocking, fire-and-forget)."""
        if not self._kafka_producer:
            return

        topic = self.kafka_dlq_topic if is_dlq else self.kafka_topic
        key = packet.session_id or packet.packet_id

        payload = {
            "packet_id": packet.packet_id,
            "session_id": packet.session_id,
            "timestamp": packet.timestamp,
            "sensor": packet.sensor,
            "value": packet.value,
            "metadata": packet.metadata,
            "sync_status": packet.sync_status,
        }

        event = self._build_event(
            event_type="telemetry.dlq" if is_dlq else "telemetry.validated",
            payload=payload,
            source="trackside_edge_buffer",
        )
        started = time.perf_counter()

        try:
            future = self._kafka_producer.send(topic, key=key, value=event)
            # Add callback for tracking (non-blocking)
            future.add_callback(lambda _: self._on_kafka_success(topic, started))
            future.add_errback(lambda e: self._on_kafka_error(e, topic))
        except Exception as exc:
            logger.warning("Kafka send exception: %s", exc)
            self._on_kafka_error(exc, topic)

    def _build_event(self, event_type: str, payload: Dict[str, Any], source: str) -> Dict[str, Any]:
        return {
            "event_type": event_type,
            "event_version": DEFAULT_KAFKA_EVENT_VERSION,
            "source": source,
            "produced_at": datetime.utcnow().isoformat(),
            "payload": payload,
        }

    def _publish_sync_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self._kafka_producer or not self.kafka_sync_event_topic:
            return

        batch_id = payload.get("batch_id") or payload.get("packet_id") or "buffer"
        event = self._build_event(
            event_type=event_type,
            payload=payload,
            source="trackside_edge_buffer",
        )
        started = time.perf_counter()
        topic = self.kafka_sync_event_topic
        try:
            future = self._kafka_producer.send(topic, key=batch_id, value=event)
            future.add_callback(lambda _: self._on_kafka_success(topic, started))
            future.add_errback(lambda e: self._on_kafka_error(e, topic))
        except Exception as exc:
            self._on_kafka_error(exc, topic)

    def _on_kafka_success(self, topic: str, started: float) -> None:
        """Callback when Kafka message is ACKed."""
        self._kafka_sent += 1
        self._kafka_sent_by_topic[topic] = self._kafka_sent_by_topic.get(topic, 0) + 1
        self._kafka_latency_total_ms += (time.perf_counter() - started) * 1000
        self._kafka_latency_samples += 1

    def _on_kafka_error(self, exc: Exception, topic: str) -> None:
        """Callback when Kafka message fails."""
        logger.warning("Kafka send failed to %s: %s", topic, exc)
        self._kafka_failed += 1
        self._kafka_failed_by_topic[topic] = self._kafka_failed_by_topic.get(topic, 0) + 1

    def flush(self) -> None:
        """Force-commit any buffered writes to disk."""
        with self._lock:
            if self._write_count > 0:
                self._conn.commit()
                self._write_count = 0

    def write_batch(self, packets: List[BufferedPacket]) -> int:
        """Persist a batch; returns the count of newly inserted rows.

        Also publishes to Kafka if enabled (non-blocking).
        """
        inserted = 0
        with self._lock:
            for pkt in packets:
                try:
                    self._conn.execute(
                        """INSERT OR IGNORE INTO telemetry_buffer
                           (packet_id, session_id, timestamp, sensor, value, metadata, sync_status)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            pkt.packet_id,
                            pkt.session_id,
                            pkt.timestamp,
                            pkt.sensor,
                            json.dumps(pkt.value),
                            json.dumps(pkt.metadata),
                            pkt.sync_status,
                        ),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass  # de-dup on packet_id
            self._conn.commit()
            self._last_write_time = datetime.utcnow().isoformat()

        # Kafka batch output (async, non-blocking)
        if self.enable_kafka and self._kafka_producer:
            for pkt in packets:
                self._send_to_kafka(pkt)

        return inserted

    # -----------------------------------------------------------------
    # Sync / Drain Path — best-effort cloud push
    # -----------------------------------------------------------------
    def drain_pending(self) -> Dict[str, Any]:
        """
        Attempt to sync pending packets to the global sink with exactly-once
        semantics.

        Each drain cycle is assigned a unique ``batch_id``.  Packets are
        marked as DRAINING *before* the sync callback fires.  The batch is
        only promoted to SYNCED after the cloud sink ACKs.  On failure the
        batch is rolled back to PENDING so it can be retried.

        Returns summary: ``{"synced": n, "failed": m, "batch_id": ...}``.
        """
        if not self.sync_callback:
            return {"synced": 0, "failed": 0, "reason": "no_sync_callback"}

        batch_id = uuid.uuid4().hex[:16]
        now = datetime.utcnow().isoformat()

        # Phase 1 — claim a batch of PENDING rows
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, packet_id, session_id, timestamp, sensor, value, metadata "
                "FROM telemetry_buffer WHERE sync_status = 'PENDING' "
                "ORDER BY id LIMIT ?",
                (self.batch_size,),
            )
            rows = cur.fetchall()
            if not rows:
                return {"synced": 0, "failed": 0, "batch_id": batch_id}

            row_ids = [r[0] for r in rows]

            # Mark as DRAINING + tag with batch_id (atomically)
            self._conn.executemany(
                "UPDATE telemetry_buffer SET sync_status = 'DRAINING', drain_batch_id = ? WHERE id = ?",
                [(batch_id, rid) for rid in row_ids],
            )
            self._conn.execute(
                "INSERT INTO drain_batches (batch_id, created_at, packet_count, status) "
                "VALUES (?, ?, ?, 'DRAINING')",
                (batch_id, now, len(row_ids)),
            )
            self._conn.commit()

        # Phase 2 — call the sync callback (outside lock to avoid blocking writes)
        payloads = []
        for row in rows:
            payloads.append({
                "packet_id": row[1],
                "session_id": row[2],
                "timestamp": row[3],
                "sensor": row[4],
                "value": json.loads(row[5]) if row[5] else None,
                "metadata": json.loads(row[6]) if row[6] else {},
                "_batch_id": batch_id,
            })

        try:
            success = self.sync_callback(payloads)
        except Exception as exc:
            logger.warning("Sync callback raised: %s", exc)
            success = False

        # Phase 3 — finalise the batch
        ack_time = datetime.utcnow().isoformat()

        with self._lock:
            if success:
                new_status = SyncStatus.SYNCED.value
                self._conn.executemany(
                    "UPDATE telemetry_buffer SET sync_status = ?, synced_at = ? WHERE id = ?",
                    [(new_status, ack_time, rid) for rid in row_ids],
                )
                self._conn.execute(
                    "UPDATE drain_batches SET status = 'ACKED', acked_at = ? WHERE batch_id = ?",
                    (ack_time, batch_id),
                )
            else:
                # Roll back to PENDING so the next drain cycle retries
                self._conn.executemany(
                    "UPDATE telemetry_buffer SET sync_status = 'PENDING', drain_batch_id = NULL WHERE id = ?",
                    [(rid,) for rid in row_ids],
                )
                self._conn.execute(
                    "UPDATE drain_batches SET status = 'FAILED' WHERE batch_id = ?",
                    (batch_id,),
                )
            self._conn.commit()

        self._connectivity = success
        if success:
            self._last_sync_time = ack_time

        if self.enable_kafka and self._kafka_producer:
            self._publish_sync_event(
                event_type="telemetry.sync.acked" if success else "telemetry.sync.failed",
                payload={
                    "batch_id": batch_id,
                    "packet_count": len(row_ids),
                    "ack_time": ack_time,
                    "connectivity": success,
                },
            )

        return {
            "synced": len(row_ids) if success else 0,
            "failed": 0 if success else len(row_ids),
            "batch_id": batch_id,
        }

    def start_background_drain(self, interval: float = 5.0) -> None:
        """Start a daemon thread that drains pending packets periodically."""
        if self._drain_active:
            return
        self._drain_active = True

        def _loop():
            while self._drain_active:
                try:
                    self.drain_pending()
                except Exception as exc:
                    logger.error("Background drain error: %s", exc)
                time.sleep(interval)

        self._drain_thread = threading.Thread(target=_loop, daemon=True, name="edge-drain")
        self._drain_thread.start()
        logger.info("Background drain thread started (interval=%.1fs)", interval)

    def stop_background_drain(self) -> None:
        self._drain_active = False
        if self._drain_thread and self._drain_thread.is_alive():
            self._drain_thread.join(timeout=10)

    def recover_incomplete_batches(self) -> int:
        """
        On startup, recover any batches left in DRAINING state (crash recovery).

        Rolls them back to PENDING so they will be retried on the next drain cycle.
        Returns the number of packets recovered.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM telemetry_buffer WHERE sync_status = 'DRAINING'"
            )
            stuck = cur.fetchone()[0]
            if stuck > 0:
                self._conn.execute(
                    "UPDATE telemetry_buffer SET sync_status = 'PENDING', drain_batch_id = NULL "
                    "WHERE sync_status = 'DRAINING'"
                )
                self._conn.execute(
                    "UPDATE drain_batches SET status = 'RECOVERED' WHERE status = 'DRAINING'"
                )
                self._conn.commit()
                logger.warning("Recovered %d packets from incomplete drain batches", stuck)
                if self.enable_kafka and self._kafka_producer:
                    self._publish_sync_event(
                        event_type="telemetry.sync.recovered",
                        payload={
                            "packet_count": stuck,
                            "connectivity": self._connectivity,
                        },
                    )
            return stuck

    @property
    def drain_history(self) -> List[Dict[str, Any]]:
        """Recent drain batch history for observability."""
        cur = self._conn.execute(
            "SELECT batch_id, created_at, packet_count, status, acked_at "
            "FROM drain_batches ORDER BY rowid DESC LIMIT 20"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # -----------------------------------------------------------------
    # Health metrics
    # -----------------------------------------------------------------
    @property
    def health(self) -> BufferHealth:
        """Snapshot of current buffer health."""
        with self._lock:
            # Single GROUP BY query instead of 3 separate COUNT queries
            cur = self._conn.execute(
                "SELECT sync_status, COUNT(*) FROM telemetry_buffer GROUP BY sync_status"
            )
            counts = {"PENDING": 0, "SYNCED": 0, "FAILED": 0}
            for row in cur.fetchall():
                if row[0] in counts:
                    counts[row[0]] = row[1]

            total = sum(counts.values())
            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

            return BufferHealth(
                total_buffered=total,
                pending_sync=counts["PENDING"],
                synced=counts["SYNCED"],
                failed=counts["FAILED"],
                buffer_utilisation=round(total / self.max_buffer_size, 4) if self.max_buffer_size else 0,
                last_write_time=self._last_write_time,
                last_sync_time=self._last_sync_time,
                connectivity=self._connectivity,
                db_size_bytes=db_size,
            )

    # -----------------------------------------------------------------
    # Replay (for post-race analysis)
    # -----------------------------------------------------------------
    def replay(self, session_id: Optional[str] = None, limit: int = 1000) -> List[Dict]:
        """
        Read telemetry back from the local buffer (regardless of sync state).
        Enables full local replay even when the cloud link is severed.
        """
        if session_id:
            cur = self._conn.execute(
                "SELECT packet_id, session_id, timestamp, sensor, value, metadata, sync_status "
                "FROM telemetry_buffer WHERE session_id = ? ORDER BY id LIMIT ?",
                (session_id, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT packet_id, session_id, timestamp, sensor, value, metadata, sync_status "
                "FROM telemetry_buffer ORDER BY id LIMIT ?",
                (limit,),
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # -----------------------------------------------------------------
    def close(self) -> None:
        self.stop_background_drain()
        self.flush()  # Commit any pending writes before closing

        # Flush Kafka producer
        if self._kafka_producer:
            try:
                self._kafka_producer.flush(timeout=5)
                self._kafka_producer.close()
                logger.info(
                    "Kafka producer closed | sent=%d failed=%d",
                    self._kafka_sent, self._kafka_failed
                )
            except Exception as exc:
                logger.warning("Error closing Kafka producer: %s", exc)

        self._conn.close()

    @property
    def kafka_stats(self) -> Dict[str, int]:
        """Return Kafka send statistics."""
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
