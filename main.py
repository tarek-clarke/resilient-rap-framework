#!/usr/bin/env python3
"""
Production entry point for Resilient RAP Framework.

This script demonstrates the core ingestion and schema reconciliation workflow
for reproducible analytical pipelines with autonomous schema drift resolution.

Usage:
    python main.py --adapter openf1 --session 9158 --driver 1
    python main.py --adapter nhl --game 2024020001
    python main.py --adapter clinical --vendor GE --batch-size 25
"""

import argparse
import sys
import json
from pathlib import Path
import logging

# Configure logging for production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point for RAP framework."""
    parser = argparse.ArgumentParser(
        description='Resilient RAP Framework - Production Pipeline Runner'
    )
    
    parser.add_argument(
        '--adapter',
        choices=['openf1', 'nhl', 'clinical'],
        default='openf1',
        help='Data adapter to use'
    )
    
    parser.add_argument(
        '--session',
        type=int,
        help='Session ID (for F1 adapter)'
    )
    
    parser.add_argument(
        '--driver',
        type=int,
        help='Driver ID (for F1 adapter)'
    )
    
    parser.add_argument(
        '--game',
        help='Game ID (for NHL adapter)'
    )
    
    parser.add_argument(
        '--vendor',
        choices=['GE', 'Philips', 'Drager'],
        default='GE',
        help='Medical device vendor (for clinical adapter)'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=25,
        help='Stream batch size (for clinical adapter)'
    )
    
    parser.add_argument(
        '--export-audit',
        action='store_true',
        help='Export audit trail after execution'
    )
    
    parser.add_argument(
        '--audit-path',
        default='data/audit.json',
        help='Path to save audit log'
    )
    
    args = parser.parse_args()
    
    try:
        if args.adapter == 'openf1':
            from adapters.sports.ingestion_sports import SportsIngestor
            
            if not args.session or not args.driver:
                parser.error('--session and --driver required for F1 adapter')
            
            logger.info(f'Starting F1 ingestion: session={args.session}, driver={args.driver}')
            ingestor = SportsIngestor(
                source_name='OpenF1',
                session_id=args.session,
                driver_id=args.driver
            )
            
        elif args.adapter == 'nhl':
            from adapters.sports.ingestion_sports import NHLIngestor
            
            if not args.game:
                parser.error('--game required for NHL adapter')
            
            logger.info(f'Starting NHL ingestion: game={args.game}')
            ingestor = NHLIngestor(game_id=args.game)
            
        elif args.adapter == 'clinical':
            from adapters.clinical.ingestion_clinical import ClinicalIngestor
            
            logger.info(f'Starting clinical ingestion: vendor={args.vendor}, batch={args.batch_size}')
            ingestor = ClinicalIngestor(
                use_stream_generator=True,
                stream_vendor=args.vendor,
                stream_batch_size=args.batch_size
            )
        
        # Execute pipeline
        logger.info('Connecting to data source...')
        ingestor.connect()
        
        logger.info('Running ingestion pipeline...')
        df = ingestor.run()
        
        logger.info(f'Pipeline completed. Output shape: {df.shape}')
        logger.info(f'Sample output:\n{df.head()}')
        
        # Export audit trail if requested
        if args.export_audit:
            logger.info(f'Exporting audit log to {args.audit_path}')
            ingestor.export_audit_log(args.audit_path)
            logger.info('Audit log exported successfully')
        
        return 0
        
    except ImportError as e:
        logger.error(f'Import error: {e}')
        logger.error('Ensure all adapters are installed and configured')
        return 1
    except Exception as e:
        logger.error(f'Pipeline execution failed: {e}', exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())