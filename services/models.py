from typing import Optional, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime

from sqlmodel import SQLModel, Field, create_engine
from sqlalchemy import Column, JSON


class AttackExecution(SQLModel, table=True):
    __tablename__ = "attack_execution"

    # --- Identifiers ---
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    project_id: UUID = Field(default=None, index=True)
    target_id: UUID = Field(default=None, index=True)
    vulnerability_catalog_id: Optional[UUID] = Field(default=None, index=True)

    # --- Vulnerability Info ---
    vulnerability_type: Optional[str] = None
    vulnerability_subtype: Optional[str] = None
    attack_method: Optional[str] = None

    # --- Probe Metadata (JSON) ---
    probe_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, sa_column=Column(JSON))

    # --- Status and Timing ---
    status: Optional[str] = Field(default="pending", index=True)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_duration_ms: Optional[int] = None

    # --- Results ---
    result_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    severity_score: Optional[float] = None
    success_indicator: Optional[bool] = None
    confidence_score: Optional[float] = None
    error_message: Optional[str] = None

    # --- Target Info (denormalized snapshot) ---
    target_name: Optional[str] = None
    target_description: Optional[str] = None
    target_endpoint_url: Optional[str] = None
    target_auth_method: Optional[str] = None
    target_endpoint_type: Optional[str] = None
    target_input_field: Optional[str] = None
    target_output_field: Optional[str] = None
    target_endpoint_config: Optional[Dict[str, Any]] = Field(default_factory=dict, sa_column=Column(JSON))
    target_additional_params: Optional[Dict[str, Any]] = Field(default_factory=dict, sa_column=Column(JSON))
    target_labels: Optional[Dict[str, Any]] = Field(default_factory=dict, sa_column=Column(JSON))

    # --- Audit fields ---
    created_at: str = Field(default_factory=datetime.utcnow)
    updated_at: str = Field(default_factory=datetime.utcnow)

# ---------- DB Setup ----------
DATABASE_URL = "sqlite:///./redteam_simple.db"
engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})

def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    
create_db_and_tables()