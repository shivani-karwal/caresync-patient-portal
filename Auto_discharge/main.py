# ============================================================
# FILE: main.py
# ROLE: Data Analyst (DA)
# PURPOSE: FastAPI server
# RUN: uvicorn main:app --reload
# ============================================================

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from database import (
    get_patient,
    get_all_patients,
    get_admitted_patients,
)

from triage_ai import run_triage

from mcp_tools import (
    tool_check_bed,
    tool_get_on_duty_nurse,
    tool_assign_bed,
    tool_discharge_patient,
)

from bed_agent import (
    run_agent,
    run_discharge_agent,
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

logger = logging.getLogger("hospital.discharge")


# ============================================================
# CREATE FASTAPI APP
# ============================================================

app = FastAPI(
    title="Hospital Triage and Bed Agent API"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# HOME PAGE
# ============================================================

@app.get("/")
def serve_homepage():

    # Always find index.html from the same folder as main.py
    index_file = Path(__file__).parent / "index.html"

    if not index_file.exists():
        raise HTTPException(
            status_code=404,
            detail="index.html not found"
        )

    return FileResponse(index_file)


# ============================================================
# PATIENT ROUTES
# ============================================================

@app.get("/patients")
def list_patients():
    """
    Returns ALL patients from database.
    Used by:
    - Triage dropdown
    - Bed assignment dropdown
    """

    try:
        patients = get_all_patients()
        return patients

    except Exception as e:

        logger.exception("Could not load patients")

        raise HTTPException(
            status_code=500,
            detail="Could not load patients."
        )


# ============================================================
# TRIAGE
# ============================================================

@app.post("/triage/{patient_id}")
def do_triage(patient_id: int):

    patient = get_patient(patient_id)

    if not patient:
        raise HTTPException(
            status_code=404,
            detail="Patient not found"
        )

    result = run_triage(patient)

    return {
        "result": result
    }


# ============================================================
# MCP TOOL REQUEST MODELS
# ============================================================

class BedRequest(BaseModel):

    ward: str


class NurseRequest(BaseModel):

    ward: str


class AssignRequest(BaseModel):

    patient_id: int
    bed_id: int
    nurse_name: str


# ============================================================
# CHECK BED
# ============================================================

@app.post("/tools/check_bed")
def api_check_bed(req: BedRequest):

    return tool_check_bed(req.ward)


# ============================================================
# GET ON DUTY NURSE
# ============================================================

@app.post("/tools/get_on_duty_nurse")
def api_get_nurse(req: NurseRequest):

    return tool_get_on_duty_nurse(req.ward)


# ============================================================
# ASSIGN BED
# ============================================================

@app.post("/tools/assign_bed")
def api_assign_bed(req: AssignRequest):

    return tool_assign_bed(
        req.patient_id,
        req.bed_id,
        req.nurse_name
    )


# ============================================================
# BED AGENT
# ============================================================

class AgentRequest(BaseModel):

    patient_id: int
    ward: str


@app.post("/agent/assign_bed")
def agent_assign_bed(req: AgentRequest):

    result = run_agent(
        req.patient_id,
        req.ward
    )

    return {
        "result": result
    }


# ============================================================
# DISCHARGE REQUEST MODELS
# ============================================================

class DischargeRequest(BaseModel):

    patient_id: int = Field(
        ...,
        gt=0
    )

    discharge_reason: Optional[str] = Field(
        None,
        max_length=255
    )

    discharged_by: Optional[str] = "web_ui"


class AgentDischargeRequest(BaseModel):

    patient_id: Optional[int] = Field(
        None,
        gt=0
    )

    message: Optional[str] = Field(
        None,
        max_length=500
    )


# ============================================================
# GET ADMITTED PATIENTS
# ============================================================

@app.get("/admitted_patients")
def list_admitted_patients():

    """
    Returns ONLY patients who currently have a bed.

    This is used by the Auto Discharge dropdown.
    """

    try:

        patients = get_admitted_patients()

        return patients

    except Exception:

        logger.exception(
            "Could not load admitted patients"
        )

        raise HTTPException(
            status_code=500,
            detail="Could not load admitted patients."
        )


# ============================================================
# DISCHARGE PATIENT
# ============================================================

@app.post("/tools/discharge_patient")
def api_discharge_patient(
    req: DischargeRequest
):

    """
    Discharge workflow:

    1. Find patient
    2. Find current bed
    3. Generate discharge summary
    4. Save discharge history
    5. Release bed
    """

    result = tool_discharge_patient(
        req.patient_id,
        req.discharge_reason,
        req.discharged_by or "web_ui"
    )

    status = result.get("status")


    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    if status == "discharged":

        code = 200


    # --------------------------------------------------------
    # PATIENT NOT ADMITTED
    # --------------------------------------------------------

    elif status in (
        "not_admitted",
        "in_progress"
    ):

        code = 409


    # --------------------------------------------------------
    # OTHER ERRORS
    # --------------------------------------------------------

    else:

        code = {
            "patient_not_found": 404,
            "invalid_input": 422
        }.get(
            result.get("error_code"),
            500
        )


    return JSONResponse(
        status_code=code,
        content=result
    )


# ============================================================
# AI DISCHARGE AGENT
# ============================================================

@app.post("/agent/discharge_patient")
def agent_discharge_patient(
    req: AgentDischargeRequest
):

    if (
        req.patient_id is None
        and not req.message
    ):

        raise HTTPException(
            status_code=422,
            detail="Send patient_id or message."
        )


    text = (
        req.message
        or f"Discharge patient {req.patient_id}."
    )


    output = run_discharge_agent(
        text,
        req.patient_id
    )


    return {
        "result": output["answer"],
        "discharge": output["discharge"]
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health_check():

    return {
        "status": "ok",
        "message": "Hospital AI System is running"
    }