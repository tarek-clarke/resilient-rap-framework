#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Reporting module for Resilient RAP Framework.
Provides PDF report generation and other reporting utilities.
"""

from .pdf_report import (
    generate_pdf_report,
    ReportGenerationError,
    RunReport,
    SchemaDriftEvent,
    FailureEvent,
    ResilienceAction,
    AuditSummary
)

__all__ = [
    'generate_pdf_report',
    'ReportGenerationError',
    'RunReport',
    'SchemaDriftEvent',
    'FailureEvent',
    'ResilienceAction',
    'AuditSummary'
]
