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

class EnumEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        return super().default(obj)
    
def create_model_callback(payload: 'AttackExecution') -> Callable:
    """
    Creates an async callback function for Azure OpenAI endpoint.
    Returns an async callable `prompt -> response`.
    """
    if payload.target_endpoint_type == "CUSTOM_QA":
        provider = RAGProvider(payload)
    if payload.target_endpoint_type == "AZURE_OPENAI":
        provider = AzureProvider(payload)
    else:
        provider = OllamaProvider(payload)
        
    return provider.generate

# ---------------------------
# Core simulation routine
# ---------------------------

async def simulate_for_target_async(payload_id: UUID):
    """
    Async wrapper that runs the blocking red-team simulation in a thread,
    loads + updates the AttackExecution row in that thread, and commits results.
    """
    logger.info("Starting simulation for execution_id=%s", payload_id)
    start_all = time.perf_counter()

    def _run_blocking(execution_id: UUID):
        try:
            with Session(engine) as session:
                # load the DB row (fresh session)
                payload = session.get(AttackExecution, execution_id)
                
                if not payload:
                    logger.error("No AttackExecution row found for id=%s", execution_id)
                    return

                # ensure probe_metadata is a dict
                probe_meta = payload.probe_metadata or {}
                if not isinstance(probe_meta, dict):
                    probe_meta = {}

                # create model callback (may raise)
                try:
                    model_callback = create_model_callback(payload)
                except Exception as e:
                    logger.exception("Failed creating model callback for id=%s: %s", execution_id, e)
                    payload.status = "failed"
                    payload.error_message = f"callback_error: {e}"
                    payload.updated_at = datetime.utcnow()
                    session.add(payload); session.commit()
                    return

                # resolve attack & vulnerability classes
                try:
                    vulnerability = get_vulnerability_class(
                        getattr(payload, "vulnerability_type", None),
                        getattr(payload, "vulnerability_subtype", None),
                    )
                    # allow get_attack_class to accept optional count if supported
                    attack = None
                    try:
                        attack = get_attack_class(getattr(payload, "attack_method", None), getattr(payload, "number_of_attacks", 1))
                    except TypeError:
                        # fallback if get_attack_class expects single arg
                        attack = get_attack_class(getattr(payload, "attack_method", None))

                    if attack is None and vulnerability is None:
                        logger.warning("No attack or vulnerability resolved for id=%s", execution_id)
                        payload.status = "failed"
                        payload.error_message = "no_attack_or_vulnerability"
                        payload.updated_at = datetime.utcnow()
                        session.add(payload); session.commit()
                        return
                except Exception as e:
                    logger.exception("Error resolving attack/vuln for id=%s: %s", execution_id, e)
                    payload.status = "failed"
                    payload.error_message = f"resolve_error: {e}"
                    payload.updated_at = datetime.utcnow()
                    session.add(payload); session.commit()
                    return

                # Run red_team - may be sync or return an awaitable
                result_obj = None
                try:
                    rt = RedTeamer(
                        simulator_model=AttackSimulator(),
                        evaluation_model=AttackEvaluator(),
                        max_concurrent=1,
                    )

                    attacks = [attack] if attack is not None else []
                    vulns = [vulnerability] if vulnerability is not None else []
                    attacks_per_vuln = int(probe_meta.get("total_attacks", getattr(payload, "number_of_attacks", 1) or 1))

                    maybe = rt.red_team(
                        attacks=attacks,
                        vulnerabilities=vulns,
                        model_callback=model_callback,
                        attacks_per_vulnerability_type=attacks_per_vuln, ignore_errors = True,
                    )

                    # If awaitable, run it to completion inside this thread
                    if inspect.isawaitable(maybe):
                        result_obj = asyncio.run(maybe)
                    else:
                        result_obj = maybe

                except Exception as e:
                    logger.exception("red_team invocation failed for execution=%s: %s", execution_id, e)
                    payload.status = "error"
                    payload.error_message = f"red_team_error: {e}"
                    payload.updated_at = datetime.utcnow()
                    session.add(payload); session.commit()
                    return

                # normalize result -> plain python structures
                try:
                    result = result_obj.model_dump(by_alias=True)           
                except Exception as e:
                    logger.exception("Failed to normalize result for execution=%s: %s", execution_id, e)
                    result = {"error": f"normalize_failed: {e}"}

                # update payload with results and save
                try:
                    
                    payload.result_data = json.dumps(result, indent=2,cls=EnumEncoder)
                    payload.status = "completed"
                    payload.completed_at = datetime.utcnow()
                    payload.execution_duration_ms = int((time.perf_counter() - start_all) * 1000)
                    payload.updated_at = datetime.utcnow()

                    session.add(payload)
                    session.commit()
                    session.refresh(payload)
                    logger.info("✓ Completed execution %s (elapsed=%.3fs)", execution_id, time.perf_counter() - start_all)


                except Exception as e:
                    logger.exception("Failed to save results for execution=%s: %s", execution_id, e)
                    # best-effort mark as error
                    payload.status = "error"
                    payload.error_message = f"save_error: {e}"
                    payload.updated_at = datetime.utcnow()
                    session.add(payload); session.commit()

        except Exception as blocking_exc:
            # Best-effort to mark record failed (separate session)
            try:
                with Session(engine) as s2:
                    db_obj = s2.get(AttackExecution, execution_id)
                    if db_obj:
                        db_obj.status = "error"
                        db_obj.error_message = f"fatal_error: {blocking_exc}"
                        db_obj.updated_at = datetime.utcnow()
                        s2.add(db_obj); s2.commit()
            except Exception:
                logger.exception("Failed to mark execution %s as error after fatal exception", execution_id)
            logger.exception("Fatal error in blocking simulation for execution=%s: %s", execution_id, blocking_exc)

    # run the blocking helper in a separate thread to avoid blocking the event loop
    await asyncio.to_thread(_run_blocking, payload_id)

    total_elapsed = time.perf_counter() - start_all
    logger.info("Simulation wrapper finished for execution %s (total_elapsed=%.3fs)", payload_id, total_elapsed)


def simulate_for_target(payload: AttackExecution):
    """
    Synchronous wrapper for async simulation (for background tasks).
    """
    logger.info("simulate_for_target called (sync wrapper) target_id=%s", payload.target_id)
    asyncio.run(simulate_for_target_async(payload))


