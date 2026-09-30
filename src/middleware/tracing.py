#!/usr/bin/env python3
"""
Request-ID Correlation Tracing
================================
Developed for the 2026 Telemetry Platform Initiative.

Provides structured, end-to-end packet tracing through the telemetry
pipeline.  Every telemetry packet is assigned a unique ``request_id``
that accompanies it through:

    RF Downlink -> Circuit Breaker -> Edge Buffer -> Geo-Fence -> Cloud Sink

This enables:
- **Distributed tracing**: follow a single packet across all subsystems.
- **Incident forensics**: trace a DLQ quarantine back to the originating sensor.
- **Audit compliance**: link geo-fence scrub decisions to specific packets.
- **Performance profiling**: measure latency between pipeline stages.

Usage
-----
>>> ctx = RequestContext.new(session_id="validation_run_01", source="rf_downlink")
>>> ctx = ctx.add_stage("circuit_breaker", status="PASSED")
>>> ctx = ctx.add_stage("geo_fence", status="PII_SCRUBBED")
>>> print(ctx.trace_summary())
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TraceStage:
    """A single pipeline stage in the request trace."""
    stage: str
    status: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    latency_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RequestContext:
    """
    Correlation context that flows through the entire telemetry pipeline.

    Immutable by convention - ``add_stage()`` returns a new context
    with the stage appended (functional style).
    """
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    session_id: str = ""
    source: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    stages: List[TraceStage] = field(default_factory=list)
    _stage_start: float = field(default_factory=time.time, repr=False)

    @classmethod
    def new(cls, session_id: str = "", source: str = "unknown") -> RequestContext:
        """Factory for a fresh request context."""
        return cls(session_id=session_id, source=source)

    def add_stage(
        self,
        stage: str,
        status: str = "OK",
        details: Optional[Dict[str, Any]] = None,
    ) -> RequestContext:
        """Record a pipeline stage and return self for chaining."""
        now = time.time()
        latency = round((now - self._stage_start) * 1000, 2)

        self.stages.append(TraceStage(
            stage=stage,
            status=status,
            latency_ms=latency,
            details=details or {},
        ))
        self._stage_start = now
        return self

    def trace_summary(self) -> Dict[str, Any]:
        """Serialisable summary of the full trace."""
        total_ms = sum(s.latency_ms for s in self.stages)
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "source": self.source,
            "created_at": self.created_at,
            "total_latency_ms": round(total_ms, 2),
            "stage_count": len(self.stages),
            "stages": [
                {
                    "stage": s.stage,
                    "status": s.status,
                    "latency_ms": s.latency_ms,
                    "timestamp": s.timestamp,
                    "details": s.details,
                }
                for s in self.stages
            ],
        }

    @property
    def last_stage(self) -> Optional[str]:
        return self.stages[-1].stage if self.stages else None

    @property
    def is_failed(self) -> bool:
        return any(s.status in ("REJECTED", "FAILED", "ERROR") for s in self.stages)
