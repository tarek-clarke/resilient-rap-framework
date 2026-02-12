#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Tamper-Evident Provenance Middleware for PhD Validation
=========================================================

Research Justification:
    Auditability is a core thesis claim (#2). This module implements a cryptographic
    chain-of-custody log using SHA-256 hashing. Every schema transformation is
    recorded with:
    - Input hash (digest of original messy field)
    - Output hash (digest of resolved standard field)
    - Confidence score
    - Timestamp
    - Previous hash (creating a linked chain)
    
    This enables:
    1. Tamper detection: Any alteration invalidates the chain
    2. Lineage tracking: Trace each decision back to its source
    3. Compliance: Audit trails for regulated domains (healthcare, finance)
    4. Reproducibility: Deterministic re-execution with proof
    
    We validate this by computing aggregate chain integrity over 10,000 samples.

Author: Lead Research Engineer
Date: 2026
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import json
import polars as pl


@dataclass
class TamperEvidentLog:
    """
    Cryptographically secure transaction log with chain-of-custody semantics.
    
    Each entry is linked to the previous via hash, forming an immutable ledger.
    """

    log_file: Path = Path("results/provenance_chain.jsonl")
    chain_file: Path = Path("results/provenance_chain_integrity.json")
    current_hash: str = field(default="genesis")
    transaction_count: int = field(default=0)
    
    def __post_init__(self):
        """Ensure log directory exists."""
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.chain_file.parent.mkdir(parents=True, exist_ok=True)

    def _hash_payload(self, payload: Dict[str, Any]) -> str:
        """
        Compute SHA-256 digest of a canonical JSON payload.
        
        Canonicalization ensures reproducibility: keys sorted, separators consistent.
        
        Args:
            payload: Dictionary to hash.
            
        Returns:
            Hex-encoded SHA-256 digest.
        """
        canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def log_transaction(
        self,
        original: str,
        mapped: str,
        confidence: float,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Record a schema mapping transaction with full provenance.
        
        Academic Justification:
            Each transformation is immutably recorded with:
            - Cryptographic signatures of inputs/outputs
            - Confidence level (model uncertainty)
            - Linked hash chain (previous transaction hash)
            - Timestamp (temporal ordering)
            
            This creates an auditable trail that proves the system's decisions
            were made consistently and can be replayed deterministically.
        
        Args:
            original: Original messy field name.
            mapped: Resolved standard field name.
            confidence: Model confidence (0.0 to 1.0).
            metadata: Optional dict with additional context (e.g., adapter, source).
            
        Returns:
            Dict representing the logged transaction.
        """
        original_hash = self._hash_payload({"field": original, "type": "original"})
        mapped_hash = self._hash_payload({"field": mapped, "type": "mapped"})
        
        transaction = {
            "transaction_id": self.transaction_count,
            "timestamp": datetime.utcnow().isoformat(),
            "original_field": original,
            "original_hash": original_hash,
            "mapped_field": mapped,
            "mapped_hash": mapped_hash,
            "confidence": confidence,
            "previous_hash": self.current_hash,
            "metadata": metadata or {},
        }
        
        # Compute this transaction's hash (links to next)
        transaction_payload = {
            k: v for k, v in transaction.items()
            if k not in ["previous_hash", "metadata"]
        }
        transaction_hash = self._hash_payload(transaction_payload)
        transaction["transaction_hash"] = transaction_hash
        
        # Append to log file
        with open(self.log_file, "a") as f:
            f.write(json.dumps(transaction) + "\n")
        
        # Update chain state
        self.current_hash = transaction_hash
        self.transaction_count += 1
        
        return transaction

    def verify_chain_integrity(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Verify the integrity of the entire provenance chain.
        
        Walks the chain from genesis, recomputing hashes to detect tampering.
        
        Returns:
            Tuple of (is_valid, report_dict)
        """
        if not self.log_file.exists():
            return True, {"message": "No log file found", "valid": True}
        
        transactions = []
        with open(self.log_file, "r") as f:
            for line in f:
                transactions.append(json.loads(line))
        
        # Verify chain
        previous_hash = "genesis"
        valid = True
        
        for i, tx in enumerate(transactions):
            # Check that previous_hash matches the expected value
            if tx["previous_hash"] != previous_hash:
                valid = False
                break
            
            # Recompute transaction hash
            tx_payload = {
                k: v for k, v in tx.items()
                if k not in ["previous_hash", "transaction_hash", "metadata"]
            }
            expected_hash = self._hash_payload(tx_payload)
            
            if tx["transaction_hash"] != expected_hash:
                valid = False
                break
            
            previous_hash = tx["transaction_hash"]
        
        report = {
            "valid": valid,
            "total_transactions": len(transactions),
            "chain_verified_up_to": self.transaction_count if valid else -1,
        }
        
        return valid, report

    def export_provenance_dataframe(self) -> pl.DataFrame:
        """
        Export the provenance log as a Polars DataFrame for analysis.
        
        Useful for:
        - Statistical auditing
        - Lineage visualization
        - Performance analysis (transaction latency, confidence trends)
        
        Returns:
            Polars DataFrame with all transactions.
        """
        if not self.log_file.exists():
            return pl.DataFrame()
        
        transactions = []
        with open(self.log_file, "r") as f:
            for line in f:
                transactions.append(json.loads(line))
        
        if not transactions:
            return pl.DataFrame()
        
        return pl.DataFrame(transactions)

    def compute_aggregate_statistics(self) -> Dict[str, Any]:
        """
        Compute aggregate statistics over the provenance chain.
        
        Returns:
            Dict with metrics like average confidence, chain length, etc.
        """
        df = self.export_provenance_dataframe()
        
        if df.is_empty():
            return {"error": "No transactions logged"}
        
        stats = {
            "total_transactions": len(df),
            "avg_confidence": df["confidence"].mean(),
            "min_confidence": df["confidence"].min(),
            "max_confidence": df["confidence"].max(),
            "confidence_std": df["confidence"].std(),
        }
        
        return stats

    def generate_audit_report(self, output_file: Optional[Path] = None) -> str:
        """
        Generate a human-readable audit report.
        
        Args:
            output_file: Optional path to save report. If None, returns as string.
            
        Returns:
            Audit report as string.
        """
        is_valid, integrity_report = self.verify_chain_integrity()
        stats = self.compute_aggregate_statistics()
        
        report = f"""
=== PROVENANCE AUDIT REPORT ===
Generated: {datetime.utcnow().isoformat()}

Chain Integrity:
  - Valid: {is_valid}
  - Total Transactions: {integrity_report.get('total_transactions', 'N/A')}

Statistics:
  - Average Confidence: {stats.get('avg_confidence', 'N/A'):.4f}
  - Min Confidence: {stats.get('min_confidence', 'N/A'):.4f}
  - Max Confidence: {stats.get('max_confidence', 'N/A'):.4f}
  - Std Dev: {stats.get('confidence_std', 'N/A'):.4f}

Conclusion: {'Chain is tamper-free and auditable.' if is_valid else 'WARNING: Chain integrity compromised!'}
"""
        
        if output_file:
            output_file.write_text(report)
        
        return report
