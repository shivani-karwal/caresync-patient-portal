# ============================================================
# FILE: discharge_ai.py   (NEW)
# PURPOSE: Builds the discharge summary.
#   - Facts block  : built in Python from MySQL values (never from the AI)
#   - Narrative    : written by Groq AI from those facts only
# The AI never touches the database. It only returns text.
# ============================================================

import os
import logging
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("hospital.discharge")

# Same model as triage_ai.py and bed_agent.py
GROQ_MODEL = "openai/gpt-oss-20b"

NOT_AVAILABLE = "Not available in the provided patient records."

SYSTEM_PROMPT = """You are a hospital documentation assistant. You write the narrative part of a discharge summary for a student/demo hospital system.

You will receive RECORD FACTS taken directly from the hospital database.

STRICT RULES:
1. Use ONLY the information in the RECORD FACTS.
2. NEVER invent diagnoses, medicines, procedures, test results, treatments, doses, or follow-up appointments.
3. Do NOT infer a diagnosis from symptoms. Report symptoms exactly as recorded.
4. If something is missing, write exactly: Not available in the provided patient records.
5. Follow-up / Instructions may only contain instructions that appear in the RECORD FACTS (for example the discharge reason). If there are none, write exactly: Not available in the provided patient records.
6. Be professional and concise: at most 120 words in total. Plain text only. No markdown, no bullet symbols.
7. Do not repeat the whole fact list. Do not add any other headings.

OUTPUT FORMAT (use exactly these two headings):
Summary
<2 to 3 sentences describing the hospital stay using only the facts>

Follow-up / Instructions
<only supported instructions, or the not-available sentence>"""


def _val(value, suffix=""):
    """Returns the value as text, or the standard 'not available' sentence."""
    if value is None or str(value).strip() == "":
        return NOT_AVAILABLE
    return f"{value}{suffix}"


def build_facts_block(patient, bed, assignment, discharged_at, reason):
    """
    Builds the factual part of the summary from real database values.
    patient: row from patients table (dict)
    bed: row from beds table (dict)
    assignment: latest bed_assignments row (dict) or None
    discharged_at: datetime object
    reason: string or None
    """
    systolic = patient.get("systolic_bp")
    diastolic = patient.get("diastolic_bp")
    if systolic is not None and diastolic is not None:
        blood_pressure = f"{systolic}/{diastolic} mmHg"
    else:
        blood_pressure = NOT_AVAILABLE

    admitted = assignment.get("assigned_at") if assignment else None
    nurse = assignment.get("nurse_assigned") if assignment else None

    return "\n".join([
        "DISCHARGE SUMMARY",
        "",
        "Patient Information",
        f"- Patient ID: {_val(patient.get('id'))}",
        f"- Name: {_val(patient.get('name'))}",
        f"- Age: {_val(patient.get('age'))}",
        f"- Gender: {_val(patient.get('gender'))}",
        "",
        "Admission Information",
        f"- Ward: {_val(bed.get('ward'))}",
        f"- Bed Number: {_val(bed.get('bed_number'))}",
        f"- Admission/Assignment Date: {_val(admitted)}",
        f"- Assigned Nurse: {_val(nurse)}",
        "",
        "Clinical Information (as recorded)",
        f"- Presenting Symptoms: {_val(patient.get('chief_complaint'))}",
        f"- Pain Level: {_val(patient.get('pain_level'), ' out of 10')}",
        f"- Temperature: {_val(patient.get('temperature'), ' C')}",
        f"- Blood Pressure: {blood_pressure}",
        f"- Heart Rate: {_val(patient.get('heart_rate'), ' bpm')}",
        "",
        "Discharge Information",
        f"- Discharge Date/Time: {discharged_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Discharge Reason: {_val(reason)}",
    ])


def generate_discharge_summary(patient, bed, assignment, discharged_at, reason):
    """
    Returns the full summary text:
      facts block (from database) + AI narrative (from Groq).
    Raises an exception if Groq fails. The caller must then NOT discharge.
    """
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("GROQ_API_KEY is not configured.")

    facts = build_facts_block(patient, bed, assignment, discharged_at, reason)
    logger.info("Summary generation started (patient %s)", patient.get("id"))

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "RECORD FACTS:\n" + facts},
        ],
        temperature=0.1,     # very low = predictable, no creativity
        max_tokens=1500,     # room for the model's internal reasoning + short answer
    )
    narrative = (response.choices[0].message.content or "").strip()
    if not narrative:
        raise RuntimeError("Groq returned an empty summary.")

    logger.info("Summary generation completed (patient %s)", patient.get("id"))

    return (
        facts
        + "\n\n--- AI-GENERATED NARRATIVE (based only on the record facts above) ---\n"
        + narrative
        + "\n\nNote: Generated summary based on available records. "
          "Not a substitute for clinician-written discharge documentation."
    )
