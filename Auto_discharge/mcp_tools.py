# ============================================================
# FILE: mcp_tools.py
# ROLE: Data Analyst (DA)
# PURPOSE: Functions that work as MCP tools.
#          FastAPI will expose these as HTTP endpoints.
#          The AI agent calls these to do real database actions.
# ============================================================

import logging
import threading
from datetime import datetime

from database import (
    find_empty_bed, get_on_duty_nurse, assign_bed_to_patient,
    get_patient, get_patient_current_bed, get_latest_assignment,
    discharge_patient_transaction,
)
from discharge_ai import generate_discharge_summary

logger = logging.getLogger("hospital.discharge")


def tool_check_bed(ward: str) -> dict:
    """
    MCP Tool 1: Check if an empty bed exists in a ward.

    Input: ward name (example: "General")
    Output: dict with bed info, or message if no bed found.

    The AI agent calls this to find an empty bed.
    """
    bed = find_empty_bed(ward)

    if bed is None:
        # No empty bed in this ward
        return {
            "status": "no_bed",
            "message": f"No empty beds available in {ward} ward right now."
        }

    # Found a bed! Return its details.
    return {
        "status": "found",
        "bed_id": bed["bed_id"],
        "bed_number": bed["bed_number"],
        "bed_type": bed["bed_type"],
        "ward": ward
    }


def tool_get_on_duty_nurse(ward: str) -> dict:
    """
    MCP Tool 2: Get the nurse currently on duty in a ward.

    Input: ward name
    Output: dict with nurse name and shift times, or message if none.

    The AI agent calls this to know who will receive the patient.
    """
    nurse = get_on_duty_nurse(ward)

    if nurse is None:
        return {
            "status": "no_nurse",
            "message": f"No nurse currently on duty in {ward} ward."
        }

    return {
        "status": "found",
        "nurse_name": nurse["nurse_name"],
        "shift_start": str(nurse["shift_start"]),
        "shift_end": str(nurse["shift_end"]),
        "ward": ward
    }


def tool_assign_bed(patient_id: int, bed_id: int, nurse_name: str) -> dict:
    """
    MCP Tool 3: Assign a patient to a bed.

    Input: patient_id, bed_id, nurse_name
    Output: success or failure message.

    This writes to the database:
    - Marks the bed as occupied.
    - Records the assignment in bed_assignments table.
    - Sets assigned_by = "ai_agent" so we know AI did this.
    """
    success = assign_bed_to_patient(patient_id, bed_id, nurse_name)

    if success:
        return {
            "status": "assigned",
            "message": f"Patient {patient_id} assigned to bed {bed_id}.",
            "nurse_assigned": nurse_name,
            "assigned_by": "ai_agent"
        }
    else:
        return {
            "status": "error",
            "message": "Database error. Could not assign bed."
        }


# ============================================================
# NEW -- MCP Tool 4: discharge_patient
# ============================================================

NOT_ADMITTED_MSG = "Patient is already discharged or is not currently assigned to a bed."
ALLOWED_DISCHARGERS = {"web_ui", "ai_agent"}

# Patients whose discharge is running right now (stops two clicks from
# calling Groq twice). The database transaction is the real protection.
_in_progress = set()
_in_progress_lock = threading.Lock()


def tool_discharge_patient(patient_id, discharge_reason=None, discharged_by="web_ui") -> dict:
    """
    MCP Tool 4: Discharge an admitted patient.

    Steps:
      1. Validate input and check the patient exists (MySQL).
      2. Find the bed the patient currently occupies (MySQL).
      3. Generate the summary with Groq (text only, no DB access).
      4. One transaction: save discharge record + release bed.
      5. Return a structured result.

    If Groq fails, nothing is changed in the database.
    """
    # ---- Validate input ----
    if isinstance(patient_id, bool):
        return {"status": "error", "error_code": "invalid_input", "message": "Invalid patient ID."}
    try:
        patient_id = int(patient_id)
        if patient_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return {"status": "error", "error_code": "invalid_input", "message": "Invalid patient ID."}

    reason = (str(discharge_reason).strip()[:255] or None) if discharge_reason else None
    if discharged_by not in ALLOWED_DISCHARGERS:
        discharged_by = "web_ui"

    logger.info("Discharge requested for patient %s (by %s)", patient_id, discharged_by)

    # ---- Block a second request while the first one is running ----
    with _in_progress_lock:
        if patient_id in _in_progress:
            return {"status": "in_progress",
                    "message": "A discharge for this patient is already in progress."}
        _in_progress.add(patient_id)

    try:
        return _discharge_flow(patient_id, reason, discharged_by)
    finally:
        with _in_progress_lock:
            _in_progress.discard(patient_id)


def _discharge_flow(patient_id, reason, discharged_by):
    # ---- Steps 1 and 2: read real data from MySQL ----
    try:
        patient = get_patient(patient_id)
        if not patient:
            logger.info("Patient %s not found", patient_id)
            return {"status": "error", "error_code": "patient_not_found",
                    "message": "Patient not found."}
        logger.info("Patient %s found", patient_id)

        bed = get_patient_current_bed(patient_id)
        if bed is None:
            logger.info("Patient %s has no current bed", patient_id)
            return {"status": "not_admitted", "message": NOT_ADMITTED_MSG}
        logger.info("Current bed found: %s (%s)", bed["bed_number"], bed["ward"])

        assignment = get_latest_assignment(patient_id, bed["bed_id"])
    except Exception:
        logger.exception("Database error while reading patient or bed")
        return {"status": "error", "error_code": "db_error",
                "message": "Database error. No changes were made."}

    # ---- Step 3: Groq summary (before the transaction) ----
    discharged_at = datetime.now().replace(microsecond=0)
    try:
        summary = generate_discharge_summary(patient, bed, assignment, discharged_at, reason)
    except Exception:
        logger.exception("Groq summary generation failed")
        return {"status": "error", "error_code": "summary_failed",
                "message": "Could not generate the discharge summary. "
                           "The patient was NOT discharged. Try again."}

    # ---- Step 4: one safe database transaction ----
    admitted_at = assignment["assigned_at"] if assignment else None
    try:
        result = discharge_patient_transaction(
            patient_id, bed["bed_id"], summary, reason,
            discharged_by, admitted_at, discharged_at
        )
    except Exception:
        return {"status": "error", "error_code": "db_error",
                "message": "Discharge failed and was rolled back. No changes were made."}

    if result is None:
        # Another request discharged this patient first
        return {"status": "not_admitted", "message": NOT_ADMITTED_MSG}

    released = result["bed"]
    return {
        "status": "discharged",
        "patient_id": patient_id,
        "patient_name": patient.get("name"),
        "bed_id": released["bed_id"],
        "bed_number": released["bed_number"],
        "ward": released["ward"],
        "bed_status": "available",          # verified by reading the row after the update
        "discharged_at": discharged_at.strftime("%Y-%m-%d %H:%M:%S"),
        "discharged_by": discharged_by,
        "discharge_id": result["discharge_id"],
        "summary": summary,
        "message": "Patient discharged successfully and bed released."
    }
