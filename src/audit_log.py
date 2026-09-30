#!/usr/bin/env python3
"""
Immutable Compliance Audit Log
================================
Developed for the 2026 Telemetry Platform Initiative.

Provides a tamper-evident, append-only audit trail for every data-handling
decision made by the geo-fence, circuit breaker, and edge buffer.  Each
log entry is hash-chained to its predecessor (SHA-256), forming an
immutable ledger that can be presented to a GDPR auditor or the FIA as
proof of data sovereignty compliance.

Design
------
- **Append-only**: INSERT only -- no UPDATE or DELETE permitted.
- **Hash-chained**: Each record's ``chain_hash`` = SHA-256(prev_chain_hash + entry_json).
- **Crash-safe**: SQLite WAL mode with NORMAL synchronous pragma.
- **Thread-safe**: Internal lock guards all writes.
- **Verifiable**: ``verify_chain()`` validates the entire ledger in O(n).

Usage
-----
>>> log = ComplianceAuditLog()
>>> log.record(action="PII_SCRUBBED", circuit="barcelona",
...            jurisdiction="EU", details={"fields": ["driver_name"]})
>>> assert log.verify_chain()  # Tamper check passes
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Seed hash for the very first entry in the chain
GENESIS_HASH = "0" * 64


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------
@dataclass
class AuditEntry:
    """A single immutable audit record."""
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    action: str = ""              # e.g. PII_SCRUBBED, BIOMETRIC_ANONYMISED, PACKET_RETAINED
    circuit: str = ""
    jurisdiction: str = ""
    session_id: str = ""
    request_id: str = ""          # Correlation ID for end-to-end tracing
    details: Dict[str, Any] = field(default_factory=dict)
    chain_hash: str = ""          # SHA-256 chain link


# ---------------------------------------------------------------------------
# Immutable Audit Log
# ---------------------------------------------------------------------------
class ComplianceAuditLog:
    """
    Append-only, hash-chained audit log for GDPR and data sovereignty compliance.

    Parameters
    ----------
    db_path : str
        Path for the SQLite audit database.
    """

    DDL = """
    CREATE TABLE IF NOT EXISTS audit_log (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_id      TEXT    UNIQUE NOT NULL,
        timestamp     TEXT    NOT NULL,
        action        TEXT    NOT NULL,
        circuit       TEXT,
        jurisdiction  TEXT,
        session_id    TEXT,
        request_id    TEXT,
        details       TEXT,
        chain_hash    TEXT    NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
    CREATE INDEX IF NOT EXISTS idx_audit_circuit ON audit_log(circuit);
    CREATE INDEX IF NOT EXISTS idx_audit_jurisdiction ON audit_log(jurisdiction);
    CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_log(request_id);
    CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);
    """

    def __init__(self, db_path: str = "data/audit_log.sqlite"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.executescript(self.DDL)
        self._lock = threading.Lock()
        self._last_hash = self._load_last_hash()
        logger.info(
            "ComplianceAuditLog online | db=%s | chain_tip=%s…",
            self.db_path, self._last_hash[:12])

    # -----------------------------------------------------------------
    # Core API
    # -----------------------------------------------------------------
    def record(
        self,
        action: str,
        circuit: str = "",
        jurisdiction: str = "",
        session_id: str = "",
        request_id: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """
        Append a new immutable entry to the audit log.

        The ``chain_hash`` is computed as:
            SHA-256(previous_chain_hash || json(entry_without_hash))
        """
        entry = AuditEntry(
            action=action,
            circuit=circuit,
            jurisdiction=jurisdiction,
            session_id=session_id,
            request_id=request_id,
            details=details or {},
        )

        with self._lock:
            # Compute chain hash (inside lock)
            entry_blob = json.dumps({
                "entry_id": entry.entry_id,
                "timestamp": entry.timestamp,
                "action": entry.action,
                "circuit": entry.circuit,
                "jurisdiction": entry.jurisdiction,
                "session_id": entry.session_id,
                "request_id": entry.request_id,
                "details": entry.details,
            }, sort_keys=True)

            chain_input = self._last_hash + entry_blob
            entry.chain_hash = hashlib.sha256(chain_input.encode()).hexdigest()

            self._conn.execute(
                """INSERT INTO audit_log
                   (entry_id, timestamp, action, circuit, jurisdiction,
                    session_id, request_id, details, chain_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.entry_id,
                    entry.timestamp,
                    entry.action,
                    entry.circuit,
                    entry.jurisdiction,
                    entry.session_id,
                    entry.request_id,
                    json.dumps(entry.details),
                    entry.chain_hash,
                ),
            )
            self._conn.commit()
            self._last_hash = entry.chain_hash

        return entry

    # -----------------------------------------------------------------
    # Verification
    # -----------------------------------------------------------------
    def verify_chain(self) -> bool:
        """
        Walk the entire ledger and verify every chain link.

        Returns True if the log is intact; False if any tampering is detected.
        """
        cur = self._conn.execute(
            "SELECT entry_id, timestamp, action, circuit, jurisdiction, "
            "session_id, request_id, details, chain_hash "
            "FROM audit_log ORDER BY id"
        )
        prev_hash = GENESIS_HASH

        for row in cur:
            entry_blob = json.dumps({
                "entry_id": row[0],
                "timestamp": row[1],
                "action": row[2],
                "circuit": row[3],
                "jurisdiction": row[4],
                "session_id": row[5],
                "request_id": row[6],
                "details": json.loads(row[7]) if row[7] else {},
            }, sort_keys=True)

            expected = hashlib.sha256((prev_hash + entry_blob).encode()).hexdigest()
            stored = row[8]

            if expected != stored:
                logger.error(
                    "AUDIT CHAIN BROKEN at entry_id=%s | expected=%s got=%s",
                    row[0], expected[:16], stored[:16],
                )
                return False

            prev_hash = stored

        return True

    # -----------------------------------------------------------------
    # Query Helpers
    # -----------------------------------------------------------------
    def count(self) -> int:
        """Total entries in the audit log."""
        cur = self._conn.execute("SELECT COUNT(*) FROM audit_log")
        return cur.fetchone()[0]

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch the most recent audit entries."""
        cur = self._conn.execute(
            "SELECT entry_id, timestamp, action, circuit, jurisdiction, "
            "session_id, request_id, details, chain_hash "
            "FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        rows = []
        for row in cur:
            d = dict(zip(cols, row))
            d["details"] = json.loads(d["details"]) if d["details"] else {}
            rows.append(d)
        return rows

    def query_by_jurisdiction(self, jurisdiction: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch audit entries filtered by jurisdiction."""
        cur = self._conn.execute(
            "SELECT entry_id, timestamp, action, circuit, jurisdiction, "
            "session_id, request_id, details, chain_hash "
            "FROM audit_log WHERE jurisdiction = ? ORDER BY id DESC LIMIT ?",
            (jurisdiction, limit),
        )
        cols = [d[0] for d in cur.description]
        rows = []
        for row in cur:
            d = dict(zip(cols, row))
            d["details"] = json.loads(d["details"]) if d["details"] else {}
            rows.append(d)
        return rows

    def query_by_request_id(self, request_id: str) -> List[Dict[str, Any]]:
        """Trace all audit entries for a given request/correlation ID."""
        cur = self._conn.execute(
            "SELECT entry_id, timestamp, action, circuit, jurisdiction, "
            "session_id, request_id, details, chain_hash "
            "FROM audit_log WHERE request_id = ? ORDER BY id",
            (request_id,),
        )
        cols = [d[0] for d in cur.description]
        rows = []
        for row in cur:
            d = dict(zip(cols, row))
            d["details"] = json.loads(d["details"]) if d["details"] else {}
            rows.append(d)
        return rows

    def summary(self, verify: bool = True) -> Dict[str, Any]:
        """Aggregate audit statistics.

        Parameters
        ----------
        verify : bool
            When *True* (default for backward compat), runs the O(n)
            ``verify_chain()`` check.  Set to *False* in hot paths to
            avoid re-hashing the entire ledger on every call.
        """
        total = self.count()
        cur = self._conn.execute(
            "SELECT action, COUNT(*) FROM audit_log GROUP BY action ORDER BY COUNT(*) DESC"
        )
        by_action = {row[0]: row[1] for row in cur}
        cur2 = self._conn.execute(
            "SELECT jurisdiction, COUNT(*) FROM audit_log "
            "WHERE jurisdiction != '' GROUP BY jurisdiction"
        )
        by_jurisdiction = {row[0]: row[1] for row in cur2}
        result: Dict[str, Any] = {
            "total_entries": total,
            "by_action": by_action,
            "by_jurisdiction": by_jurisdiction,
        }
        if verify:
            result["chain_intact"] = self.verify_chain()
        return result

    # -----------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------
    def _load_last_hash(self) -> str:
        """Load the chain tip from the DB, or return genesis hash."""
        cur = self._conn.execute(
            "SELECT chain_hash FROM audit_log ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row[0] if row else GENESIS_HASH

    def close(self) -> None:
        self._conn.close()
