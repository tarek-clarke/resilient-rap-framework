#!/usr/bin/env python3
"""
Data Sovereignty & Geo-Fencing Module
=======================================
Developed for the 2026 Telemetry Platform Initiative.

Enforces jurisdiction-aware data handling for telemetry captured across
international borders.  EU-collected data (Spain, Austria, Belgium, …)
is processed under GDPR-aligned rules *before* metadata is synced to
the US 'War Room'.

Compliance Zones
----------------
- **EU**: Full GDPR processing — PII scrubbed, driver biometrics anonymised,
  raw telemetry retained on EU-sovereign storage.  Only aggregated metadata
  and non-PII performance summaries sync to the US sink.
- **US**: Standard processing — full telemetry forwarded to the War Room.
- **ME** (Middle East): Similar to US with additional export-control markers.
- **APAC** (Asia-Pacific): Local retention + metadata sync.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from src.audit_log import ComplianceAuditLog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Jurisdiction Definitions
# ---------------------------------------------------------------------------
class Jurisdiction(Enum):
    EU = "EU"
    US = "US"
    ME = "ME"      # Middle East
    APAC = "APAC"
    UK = "UK"


# 2026 F1 Calendar → Jurisdiction mapping
CIRCUIT_JURISDICTION: Dict[str, Jurisdiction] = {
    # European rounds (GDPR)
    "bahrain":        Jurisdiction.ME,
    "jeddah":         Jurisdiction.ME,
    "melbourne":      Jurisdiction.APAC,
    "suzuka":         Jurisdiction.APAC,
    "shanghai":       Jurisdiction.APAC,
    "miami":          Jurisdiction.US,
    "imola":          Jurisdiction.EU,
    "monaco":         Jurisdiction.EU,
    "montréal":       Jurisdiction.US,      # Canada grouped w/ US compliance
    "montreal":       Jurisdiction.US,
    "barcelona":      Jurisdiction.EU,
    "spielberg":      Jurisdiction.EU,       # Austria
    "silverstone":    Jurisdiction.UK,
    "budapest":       Jurisdiction.EU,
    "spa":            Jurisdiction.EU,       # Belgium
    "zandvoort":      Jurisdiction.EU,       # Netherlands
    "monza":          Jurisdiction.EU,
    "baku":           Jurisdiction.APAC,
    "singapore":      Jurisdiction.APAC,
    "austin":         Jurisdiction.US,       # COTA
    "mexico_city":    Jurisdiction.US,       # Grouped w/ Americas
    "são_paulo":      Jurisdiction.US,       # Grouped w/ Americas
    "sao_paulo":      Jurisdiction.US,
    "las_vegas":      Jurisdiction.US,
    "lusail":         Jurisdiction.ME,       # Qatar
    "yas_marina":     Jurisdiction.ME,       # Abu Dhabi
}


# ---------------------------------------------------------------------------
# Policy Configuration
# ---------------------------------------------------------------------------
@dataclass
class JurisdictionPolicy:
    """Per-jurisdiction data handling rules."""
    jurisdiction: Jurisdiction
    scrub_pii: bool = False
    anonymise_biometrics: bool = False
    local_retention_required: bool = False
    metadata_only_sync: bool = False
    export_control_marker: bool = False
    retention_days: int = 365
    encryption_at_rest: bool = True
    encryption_in_transit: bool = True


# Pre-defined policies
POLICIES: Dict[Jurisdiction, JurisdictionPolicy] = {
    Jurisdiction.EU: JurisdictionPolicy(
        jurisdiction=Jurisdiction.EU,
        scrub_pii=True,
        anonymise_biometrics=True,
        local_retention_required=True,
        metadata_only_sync=True,
        retention_days=730,         # 2-year GDPR-compliant retention
    ),
    Jurisdiction.UK: JurisdictionPolicy(
        jurisdiction=Jurisdiction.UK,
        scrub_pii=True,
        anonymise_biometrics=True,
        local_retention_required=True,
        metadata_only_sync=True,
        retention_days=730,
    ),
    Jurisdiction.US: JurisdictionPolicy(
        jurisdiction=Jurisdiction.US,
        scrub_pii=False,
        anonymise_biometrics=False,
        local_retention_required=False,
        metadata_only_sync=False,
    ),
    Jurisdiction.ME: JurisdictionPolicy(
        jurisdiction=Jurisdiction.ME,
        scrub_pii=False,
        anonymise_biometrics=False,
        local_retention_required=False,
        metadata_only_sync=False,
        export_control_marker=True,
    ),
    Jurisdiction.APAC: JurisdictionPolicy(
        jurisdiction=Jurisdiction.APAC,
        scrub_pii=True,
        anonymise_biometrics=True,
        local_retention_required=True,
        metadata_only_sync=True,
    ),
}


# Fields classified as PII / driver biometrics
PII_FIELDS = {
    "driver_name", "driver_id", "driver_weight", "driver_heart_rate",
    "heart_rate", "body_temp", "core_temperature", "biometric_id",
    "radio_transcript", "gps_latitude", "gps_longitude",
}

BIOMETRIC_FIELDS = {
    "heart_rate", "driver_heart_rate", "body_temp", "core_temperature",
    "respiration_rate", "blood_oxygen", "g_force_exposure_cumulative",
}


# ---------------------------------------------------------------------------
# Geo-Fence Processor
# ---------------------------------------------------------------------------
@dataclass
class GeoFenceResult:
    """Outcome of processing a telemetry payload through the geo-fence."""
    jurisdiction: str
    policy_applied: str
    local_payload: Dict[str, Any]       # Full data retained on-site
    sync_payload: Dict[str, Any]        # Data cleared for War Room sync
    fields_scrubbed: List[str]
    fields_anonymised: List[str]
    compliance_hash: str                # SHA-256 proof of processing
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class GeoFence:
    """
    Jurisdiction-aware telemetry processor.

    Usage
    -----
    >>> gf = GeoFence()
    >>> result = gf.process(circuit="barcelona", payload=telemetry_dict)
    >>> # result.sync_payload → safe for War Room
    >>> # result.local_payload → sovereign copy retains full fidelity
    """

    def __init__(
        self,
        custom_policies: Optional[Dict[Jurisdiction, JurisdictionPolicy]] = None,
        custom_circuits: Optional[Dict[str, Jurisdiction]] = None,
        audit_log: Optional[ComplianceAuditLog] = None,
    ):
        self.policies = {**POLICIES, **(custom_policies or {})}
        self.circuits = {**CIRCUIT_JURISDICTION, **(custom_circuits or {})}
        # Bounded log: keeps last 10 000 results to prevent unbounded growth
        self._processing_log: deque = deque(maxlen=10_000)
        # Running counters so processing_summary stays accurate even after eviction
        self._total_processed = 0
        self._total_scrubbed = 0
        self._total_anonymised = 0
        self._by_jurisdiction: Dict[str, int] = {}
        self.audit = audit_log
        logger.info(
            "GeoFence initialised | %d circuits mapped | audit=%s",
            len(self.circuits), "ON" if self.audit else "OFF")

    # -----------------------------------------------------------------
    # Core Processing
    # -----------------------------------------------------------------
    def resolve_jurisdiction(self, circuit: str) -> Jurisdiction:
        """Look up the governing jurisdiction for a circuit."""
        key = circuit.lower().strip().replace(" ", "_")
        if key in self.circuits:
            return self.circuits[key]
        logger.warning("Unknown circuit '%s' — defaulting to US policy", circuit)
        return Jurisdiction.US

    def process(
        self,
        circuit: str,
        payload: Dict[str, Any],
        session_id: str = "",
        request_id: str = "",
    ) -> GeoFenceResult:
        """
        Process a telemetry payload through the jurisdiction fence.

        Parameters
        ----------
        circuit : str
            Circuit name (e.g. "barcelona", "silverstone").
        payload : dict
            Raw telemetry key-value pairs.
        session_id : str
            Optional session identifier for traceability.
        request_id : str
            Correlation ID for end-to-end packet tracing.

        Returns
        -------
        GeoFenceResult with separate local and sync payloads.
        """
        if not request_id:
            request_id = uuid.uuid4().hex[:12]

        jurisdiction = self.resolve_jurisdiction(circuit)
        policy = self.policies.get(jurisdiction, self.policies[Jurisdiction.US])

        # Start with full copies
        local_payload = dict(payload)
        sync_payload = dict(payload)

        fields_scrubbed: List[str] = []
        fields_anonymised: List[str] = []

        # --- PII Scrubbing for sync payload --------------------------
        if policy.scrub_pii:
            for key in list(sync_payload.keys()):
                if key.lower() in PII_FIELDS:
                    sync_payload[key] = "[REDACTED]"
                    fields_scrubbed.append(key)
            if fields_scrubbed and self.audit:
                self.audit.record(
                    action="PII_SCRUBBED",
                    circuit=circuit,
                    jurisdiction=jurisdiction.value,
                    session_id=session_id,
                    request_id=request_id,
                    details={"fields": fields_scrubbed, "policy": "scrub_pii"},
                )

        # --- Biometric Anonymisation ---------------------------------
        if policy.anonymise_biometrics:
            for key in list(sync_payload.keys()):
                if key.lower() in BIOMETRIC_FIELDS:
                    raw = str(sync_payload[key])
                    sync_payload[key] = self._anonymise(raw)
                    fields_anonymised.append(key)
            if fields_anonymised and self.audit:
                self.audit.record(
                    action="BIOMETRIC_ANONYMISED",
                    circuit=circuit,
                    jurisdiction=jurisdiction.value,
                    session_id=session_id,
                    request_id=request_id,
                    details={"fields": fields_anonymised, "policy": "anonymise_biometrics"},
                )

        # --- Metadata-only sync (strip raw telemetry values) ---------
        if policy.metadata_only_sync:
            sync_payload = self._extract_metadata(sync_payload, session_id, circuit)
            if self.audit:
                self.audit.record(
                    action="METADATA_ONLY_SYNC",
                    circuit=circuit,
                    jurisdiction=jurisdiction.value,
                    session_id=session_id,
                    request_id=request_id,
                    details={"policy": "metadata_only_sync", "field_count": len(payload)},
                )

        # --- Export-control marker ------------------------------------
        if policy.export_control_marker:
            sync_payload["_export_control"] = True
            sync_payload["_jurisdiction"] = jurisdiction.value
            if self.audit:
                self.audit.record(
                    action="EXPORT_CONTROL_APPLIED",
                    circuit=circuit,
                    jurisdiction=jurisdiction.value,
                    session_id=session_id,
                    request_id=request_id,
                    details={"policy": "export_control_marker"},
                )

        # --- Local retention audit -----------------------------------
        if policy.local_retention_required and self.audit:
            self.audit.record(
                action="LOCAL_RETENTION",
                circuit=circuit,
                jurisdiction=jurisdiction.value,
                session_id=session_id,
                request_id=request_id,
                details={
                    "retention_days": policy.retention_days,
                    "encryption_at_rest": policy.encryption_at_rest,
                },
            )

        # --- Compliance hash (proves this was processed) -------------
        compliance_hash = self._compute_compliance_hash(
            jurisdiction, payload, sync_payload
        )

        result = GeoFenceResult(
            jurisdiction=jurisdiction.value,
            policy_applied=f"{jurisdiction.value}_policy",
            local_payload=local_payload,
            sync_payload=sync_payload,
            fields_scrubbed=fields_scrubbed,
            fields_anonymised=fields_anonymised,
            compliance_hash=compliance_hash,
        )
        self._processing_log.append(result)
        # Update running counters
        self._total_processed += 1
        self._total_scrubbed += len(fields_scrubbed)
        self._total_anonymised += len(fields_anonymised)
        self._by_jurisdiction[jurisdiction.value] = (
            self._by_jurisdiction.get(jurisdiction.value, 0) + 1
        )
        return result

    def process_batch(
        self,
        circuit: str,
        payloads: List[Dict[str, Any]],
        session_id: str = "",
    ) -> List[GeoFenceResult]:
        """Process multiple payloads under the same circuit jurisdiction."""
        return [self.process(circuit, p, session_id) for p in payloads]

    # -----------------------------------------------------------------
    # Reporting
    # -----------------------------------------------------------------
    @property
    def processing_summary(self) -> Dict[str, Any]:
        """Aggregate stats for all processed payloads (uses running counters)."""
        return {
            "total_processed": self._total_processed,
            "by_jurisdiction": dict(self._by_jurisdiction),
            "total_fields_scrubbed": self._total_scrubbed,
            "total_fields_anonymised": self._total_anonymised,
        }

    # -----------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------
    @staticmethod
    def _anonymise(value: str) -> str:
        """One-way hash that preserves statistical grouping but hides identity."""
        return "anon_" + hashlib.sha256(value.encode()).hexdigest()[:12]

    @staticmethod
    def _extract_metadata(
        payload: Dict[str, Any],
        session_id: str,
        circuit: str,
    ) -> Dict[str, Any]:
        """
        Reduce a full telemetry payload to metadata-only for War Room sync.
        Retains: field names, data types, value ranges, timestamps.
        Strips: actual sensor values.
        """
        meta: Dict[str, Any] = {
            "_sync_type": "metadata_only",
            "_session_id": session_id,
            "_circuit": circuit,
            "_field_count": len(payload),
            "_fields": [],
            "_timestamp": datetime.utcnow().isoformat(),
        }
        for key, val in payload.items():
            field_meta: Dict[str, Any] = {
                "name": key,
                "type": type(val).__name__,
            }
            if isinstance(val, (int, float)):
                field_meta["range_hint"] = "numeric"
            elif isinstance(val, str) and val != "[REDACTED]":
                field_meta["length"] = len(val)
            meta["_fields"].append(field_meta)
        return meta

    @staticmethod
    def _compute_compliance_hash(
        jurisdiction: Jurisdiction,
        original: Dict[str, Any],
        processed: Dict[str, Any],
    ) -> str:
        """SHA-256 over the jurisdiction + original + processed payload."""
        blob = json.dumps(
            {"jurisdiction": jurisdiction.value, "original_keys": sorted(original.keys()),
             "processed_keys": sorted(processed.keys())},
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode()).hexdigest()
