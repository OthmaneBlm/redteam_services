# app/services/simulate_attacks.py
from typing import Optional, List, Callable, Any, Dict
from enum import Enum
from uuid import UUID
from datetime import datetime
from sqlmodel import Session, select
import asyncio
import os
import time
import logging
import inspect
import json

from services.models import AttackExecution, engine, create_db_and_tables
from core.simulator_core import run_simulation
# DeepTeam imports
from deepteam.red_teamer import RedTeamer
from deepteam.vulnerabilities import Bias
from deepteam.attacks.single_turn import ROT13, Leetspeak, Base64
from services.custom_evaluator import AttackEvaluator, AttackSimulator
# SQLAlchemy helpers
from sqlalchemy import func
from utils.utils import *
from services.providers import AzureProvider, RAGProvider, OllamaProvider
from utils.logger import setup_logging



# create module-level logger (default INFO, no file)
logger = setup_logging()  # call setup_logging(logging.DEBUG) from scripts to increase verbosity

# ---------------------------
# Core simulation routine - Expanded with writing to db
# ---------------------------

async def simulate_for_target_async(payload_id: UUID):
    def _blocking_job():
        with Session(engine) as session:
            payload = session.get(AttackExecution, payload_id)
            if not payload:
                logger.error(f"No AttackExecution found for id={payload_id}")
                return

            try:
                updated_payload = run_simulation(payload)

                # Optionally persist updates
                session.add(updated_payload)
                session.commit()
                session.refresh(updated_payload)
                logger.info(f"✓ Completed and saved execution {payload_id}")

            except Exception as e:
                logger.exception(f"Error running simulation for {payload_id}: {e}")
                payload.status = "error"
                payload.error_message = str(e)
                payload.updated_at = datetime.utcnow()
                session.add(payload)
                session.commit()

    await asyncio.to_thread(_blocking_job)

def simulate_for_target(payload: AttackExecution):
    """
    Synchronous wrapper for async simulation (for background tasks).
    """
    logger.info("simulate_for_target called (sync wrapper) target_id=%s", payload.target_id)
    asyncio.run(simulate_for_target_async(payload))


