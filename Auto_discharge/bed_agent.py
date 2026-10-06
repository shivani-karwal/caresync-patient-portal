# ============================================================
# FILE: bed_agent.py
# ROLE: Data Analyst (DA)
# PURPOSE: AI Agent that assigns hospital beds automatically
#          and (new) discharges patients.
#
# HOW TO RUN: python bed_agent.py
#
# WHAT IT DOES:
#   1. Asks you: assign a bed, or discharge a patient?
#   2. Sends request to Groq AI with available tools.
#   3. AI decides which tool to call.
#   4. Python calls the tool on FastAPI.
#   5. AI sees result, decides next tool.
#   6. Loop until AI says task is done.
# ============================================================

import json
import requests      # For calling FastAPI tool endpoints
from groq import Groq
from dotenv import load_dotenv
import os

load_dotenv()

# ============================================================
# STEP 1: Define the tools for Groq AI
# This is how we tell Groq AI what tools are available.
# Groq uses this list to decide which tool to call.
# ============================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_bed",
            "description": "Check if there is an empty bed in a hospital ward.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ward": {
                        "type": "string",
                        "description": "Ward name. Options: General, Emergency, ICU, Pediatric, Maternity"
                    }
                },
                "required": ["ward"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_on_duty_nurse",
            "description": "Get the name of the nurse currently on duty in a ward.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ward": {
                        "type": "string",
                        "description": "Ward name"
                    }
                },
                "required": ["ward"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "assign_bed",
            "description": "Assign a patient to a hospital bed with a nurse.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "integer",
                        "description": "The patient ID number"
                    },
                    "bed_id": {
                        "type": "integer",
                        "description": "The bed ID number"
                    },
                    "nurse_name": {
                        "type": "string",
                        "description": "The name of the nurse who will handle this patient"
                    }
                },
                "required": ["patient_id", "bed_id", "nurse_name"]
            }
        }
    },
    # ---------------- NEW TOOL ----------------
    {
        "type": "function",
        "function": {
            "name": "discharge_patient",
            "description": (
                "Discharge an admitted patient. The system verifies the patient, "
                "generates the discharge summary, saves the discharge history and "
                "releases the patient's bed. Call it once per discharge request."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_id": {
                        "type": "integer",
                        "description": "The patient ID number to discharge"
                    },
                    "discharge_reason": {
                        "type": "string",
                        "description": "Reason for discharge. Only include it if the user stated one."
                    }
                },
                "required": ["patient_id"]
            }
        }
    }
]


# ============================================================
# STEP 2: Function to call a tool on FastAPI
# When AI says "call check_bed", this function does it.
# ============================================================

FASTAPI_URL = "http://localhost:8000"   # FastAPI runs here


def call_tool(tool_name: str, tool_args: dict) -> str:
    """
    Calls one of our FastAPI MCP tool endpoints.
    Returns the result as a JSON string.
    """
    url = f"{FASTAPI_URL}/tools/{tool_name}"

    try:
        # POST request sends the arguments to FastAPI
        response = requests.post(url, json=tool_args)
        result = response.json()
        print(f"  [TOOL CALLED] {tool_name}({tool_args})")
        print(f"  [TOOL RESULT] {result}")
        return json.dumps(result)   # Convert dict to string for AI

    except Exception as e:
        error_msg = f"Tool call failed: {str(e)}"
        print(f"  [TOOL ERROR] {error_msg}")
        return json.dumps({"error": error_msg})


# ============================================================
# STEP 3: The Agent Loop  (bed assignment - unchanged)
# This is the main logic. It loops until the AI is done.
# ============================================================

def run_agent(patient_id: int, ward: str):
    """
    Main agent function.
    Gives Groq AI a task and lets it use tools to complete it.

    patient_id: The patient we want to assign
    ward: Which ward they need (General, ICU, etc.)
    """

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    # This is the initial task we give the AI
    task_message = f"""
You are a hospital bed assignment agent. Your job:
1. Check if there is an empty bed in the {ward} ward.
2. Find which nurse is on duty in that ward.
3. Assign patient {patient_id} to the empty bed with that nurse.
4. Report what you did.

Use the tools available to you. Do not guess. Use real data.
"""

    # Start conversation with AI
    messages = [
        {"role": "user", "content": task_message}
    ]

    print(f"\n=== AI Agent Starting ===")
    print(f"Task: Assign patient {patient_id} to {ward} ward")
    print(f"=========================\n")

    # Agent loop: keep going until AI says it is done
    while True:
        # Send current messages + tools to Groq AI
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=messages,
            tools=TOOLS,              # Tell AI what tools are available
            tool_choice="auto",       # AI decides when to use a tool
            max_tokens=1000,
        )

        ai_message = response.choices[0].message

        # Add AI response to conversation history
        messages.append({
            "role": "assistant",
            "content": ai_message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in (ai_message.tool_calls or [])
            ] or None
        })

        # Check if AI wants to call a tool
        if ai_message.tool_calls:
            # AI wants to call one or more tools
            for tool_call in ai_message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                # Call the actual tool on FastAPI
                tool_result = call_tool(tool_name, tool_args)

                # Add tool result to conversation so AI can see it
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result
                })

        else:
            # AI did not call any tool. It is done.
            # Print the final message from AI.
            final_answer = ai_message.content
            print(f"\n=== AI Agent Done ===")
            print(f"Result: {final_answer}")
            print(f"=====================\n")
            return final_answer


# ============================================================
# NEW -- Discharge agent
# The AI decides to call discharge_patient. The tool itself
# talks to MySQL. The AI never writes to the database.
# ============================================================

MAX_DISCHARGE_STEPS = 6   # safety limit so the loop can never run forever


def run_discharge_agent(user_request: str, patient_id: int = None):
    """
    Handles a discharge request such as "Discharge patient 5."

    user_request: the nurse's sentence
    patient_id: if given, this ID is ENFORCED on the tool call, so the AI
                cannot discharge a different patient by mistake.

    Returns: {"answer": text from the AI, "discharge": structured tool result or None}
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    task_message = f"""
You are a hospital discharge agent.

Rules:
1. Call the discharge_patient tool exactly once with the patient ID from the request.
2. Never guess a patient ID. Never write medical information yourself.
3. After the tool returns, report the status, patient, bed number and ward in 2 or 3 sentences.
4. Do not rewrite or repeat the discharge summary. The system already saved it.
5. If the tool says the patient is not admitted or not found, explain that clearly.

Request: {user_request}
"""
    messages = [{"role": "user", "content": task_message}]
    discharge_result = None

    print(f"\n=== Discharge Agent Starting ===")
    print(f"Request: {user_request}")
    print(f"================================\n")

    for _ in range(MAX_DISCHARGE_STEPS):
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=1000,
        )
        ai_message = response.choices[0].message

        messages.append({
            "role": "assistant",
            "content": ai_message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in (ai_message.tool_calls or [])
            ] or None
        })

        if not ai_message.tool_calls:
            final_answer = ai_message.content
            print(f"\n=== Discharge Agent Done ===")
            print(f"Result: {final_answer}")
            print(f"============================\n")
            return {"answer": final_answer, "discharge": discharge_result}

        for tool_call in ai_message.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            if tool_name == "discharge_patient":
                # Code decides who is discharged and who did it, not the AI
                if patient_id is not None:
                    tool_args["patient_id"] = patient_id
                tool_args["discharged_by"] = "ai_agent"
                tool_result = call_tool(tool_name, tool_args)
                try:
                    discharge_result = json.loads(tool_result)
                except json.JSONDecodeError:
                    discharge_result = None
            else:
                # This agent only discharges. Other tools are refused here.
                tool_result = json.dumps({"error": "Tool not allowed in the discharge agent."})

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result
            })

    return {"answer": "The agent stopped because it used too many steps.",
            "discharge": discharge_result}


# ============================================================
# STEP 4: Run the agent from command line
# ============================================================

if __name__ == "__main__":
    print("\n--- Hospital Bed Availability Agent ---")
    print("Make sure FastAPI is running first: uvicorn main:app --reload")
    print("")

    choice = input("Type 1 to assign a bed, or 2 to discharge a patient: ").strip()

    if choice == "2":
        request_text = input('Type your request (example: Discharge patient 5): ').strip()
        out = run_discharge_agent(request_text)
        print("\nAgent finished. Check the discharges table in MySQL.")
    else:
        # Ask user for input
        patient_id = int(input("Enter patient ID: "))
        ward = input("Enter ward (General / Emergency / ICU / Pediatric / Maternity): ").strip()

        # Run the agent
        result = run_agent(patient_id, ward)

        print("\nAgent finished. Check MySQL to see the bed_assignments table.")
