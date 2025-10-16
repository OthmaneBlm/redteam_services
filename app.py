# app.py
from typing import List, Optional
from uuid import UUID, uuid4
from datetime import datetime
import time

from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlmodel import Session

from services.simulate_attack import *
from services.models import AttackExecution, engine, create_db_and_tables

# create tables at startup
app = FastAPI(title="RedTeam")

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

# -----------------------
# Routes: Simulate 
# -----------------------
@app.get("/ping")
def ping():
    return {"status": "ok"}

@app.post("/atomic_attack", response_model=AttackExecution)
async def simulate_target_and_wait(payload: AttackExecution, timeout: Optional[float] = None):
    """
    Save payload (status -> running) then run the simulation and WAIT for it to finish.
    Returns the final DB row (including result_data) after worker completes.

    timeout: optional seconds to wait before cancelling and returning an error.
    """
    # prepare persistable payload
    payload.status = "running"
    payload.started_at = datetime.utcnow()
    payload.updated_at = datetime.utcnow()

    # persist initial row and get ID
    try:
        with Session(engine) as session:
            # optionally prevent duplicate IDs
            if payload.id and session.get(AttackExecution, payload.id):
                raise HTTPException(status_code=409, detail=f"AttackExecution with id {payload.id} already exists")

            session.add(payload)
            session.commit()
            session.refresh(payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error while creating execution: {e}")

    execution_id: UUID = payload.id

    # await the async worker (it will do DB writes itself)
    try:
        if timeout:
            # optional timeout to avoid infinite wait
            await asyncio.wait_for(simulate_for_target_async(execution_id), timeout=timeout)
        else:
            await simulate_for_target_async(execution_id)
    except asyncio.TimeoutError:
        # mark the row as timed out (best-effort)
        try:
            with Session(engine) as session:
                row = session.get(AttackExecution, execution_id)
                if row:
                    row.status = "timed_out"
                    row.updated_at = datetime.utcnow()
                    session.add(row); session.commit(); session.refresh(row)
        except Exception:
            app.logger.exception("Failed to mark execution timed_out for id=%s", execution_id)
        raise HTTPException(status_code=504, detail="Simulation timed out")
    except Exception as e:
        # worker signalled an error (or crashed)
        # try to return latest DB row (which worker may have marked failed)
        with Session(engine) as session:
            row = session.get(AttackExecution, execution_id)
            if row:
                return row
        raise HTTPException(status_code=500, detail=f"Simulation failed: {e}")

    # reload final row and return it (should include result_data)
    with Session(engine) as session:
        final = session.get(AttackExecution, execution_id)
        if not final:
            raise HTTPException(status_code=404, detail="Execution not found after simulation")
        session.refresh(final)
        return final

@app.get("/results/{execution_id}", response_model=AttackExecution)
def get_result(execution_id: UUID):
    with Session(engine) as session:
        item = session.get(AttackExecution, execution_id)
        if not item: raise HTTPException(404)
        return item