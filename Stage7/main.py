import os
import json
from datetime import date, datetime, time as dt_time

import psycopg2
from psycopg2 import errors
from dotenv import load_dotenv
from groq import Groq

from fastapi import FastAPI
from pydantic import BaseModel


# ============================================================
# ENVIRONMENT + GROQ
# ============================================================

load_dotenv()

groq_api_key = os.getenv("GROQ_API_KEY")

if not groq_api_key:
    raise ValueError("GROQ_API_KEY not found in .env file")

client = Groq(api_key=groq_api_key)


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="AI Appointment Assistant",
    version="Stage 7"
)


# ============================================================
# SESSION STORAGE
# ============================================================

sessions = {}


def create_session():
    return {
        "appointment": {
            "patient_name": None,
            "doctor": None,
            "date": None,
            "time": None
        },
        "availability_checked": False,
        "awaiting_confirmation": False,
        "booking_completed": False,
        "messages": []
    }


def get_session(session_id):
    if session_id not in sessions:
        sessions[session_id] = create_session()

    return sessions[session_id]


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():

    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )


# ============================================================
# NORMALIZE DOCTOR
# ============================================================

def normalize_doctor(doctor):

    if not doctor:
        return None

    doctor = doctor.strip()
    doctor = doctor.replace(".", "")

    parts = doctor.split()

    if len(parts) >= 2 and parts[0].lower() == "dr":
        doctor_name = " ".join(parts[1:])
    else:
        doctor_name = doctor

    return "Dr. " + doctor_name.title()


# ============================================================
# NORMALIZE DATE
# ============================================================

def normalize_date(date_text):

    if not date_text:
        return None

    date_text = date_text.strip()

    try:
        parsed_date = date.fromisoformat(date_text)
        return parsed_date.isoformat()

    except ValueError:
        pass

    cleaned = date_text.replace(",", "")

    formats = [
        "%d %B %Y",
        "%d %b %Y",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%B %d %Y",
        "%b %d %Y"
    ]

    for fmt in formats:

        try:

            parsed_date = datetime.strptime(
                cleaned,
                fmt
            ).date()

            return parsed_date.isoformat()

        except ValueError:
            continue

    return None


# ============================================================
# NORMALIZE TIME
# ============================================================

def normalize_time(time_text):

    if not time_text:
        return None

    time_text = time_text.strip().lower()

    if time_text in ["morning", "in the morning"]:
        return "Morning"

    if time_text in ["afternoon", "in the afternoon"]:
        return "Afternoon"

    if time_text in ["evening", "in the evening"]:
        return "Evening"

    formats = [
        "%I %p",
        "%I:%M %p",
        "%I%p",
        "%I:%M%p",
        "%H:%M"
    ]

    for fmt in formats:

        try:

            parsed_time = datetime.strptime(
                time_text,
                fmt
            )

            return parsed_time.strftime("%H:%M")

        except ValueError:
            continue

    return None


# ============================================================
# VALID CLINIC TIME
# ============================================================

def valid_clinic_time(time_text):

    if time_text in ["Morning", "Afternoon", "Evening"]:
        return True

    try:

        parsed_time = datetime.strptime(
            time_text,
            "%H:%M"
        ).time()

        opening_time = dt_time(8, 0)
        closing_time = dt_time(20, 0)

        return opening_time <= parsed_time <= closing_time

    except ValueError:

        return False


# ============================================================
# GET DOCTOR ID
# ============================================================

def get_doctor_id(doctor_name):

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id
            FROM doctors
            WHERE LOWER(name) = LOWER(%s)
            """,
            (doctor_name,)
        )

        result = cursor.fetchone()

        cursor.close()

        if result:
            return result[0]

        return None

    finally:

        connection.close()


# ============================================================
# CHECK DOCTOR
# ============================================================

def check_doctor(doctor_name):

    normalized_doctor = normalize_doctor(doctor_name)

    if not normalized_doctor:
        return {
            "success": False,
            "message": "Doctor name is required."
        }

    doctor_id = get_doctor_id(normalized_doctor)

    if doctor_id:

        return {
            "success": True,
            "doctor": normalized_doctor,
            "message": f"{normalized_doctor} is available in the clinic."
        }

    return {
        "success": False,
        "doctor": normalized_doctor,
        "message": f"{normalized_doctor} was not found in the clinic."
    }


# ============================================================
# UPDATE APPOINTMENT STATE
# ============================================================

def update_appointment(
    session,
    patient_name=None,
    doctor=None,
    appointment_date=None,
    appointment_time=None
):

    appointment = session["appointment"]

    changed = False

    if patient_name:

        appointment["patient_name"] = patient_name.strip()
        changed = True

    if doctor:

        normalized_doctor = normalize_doctor(doctor)

        if normalized_doctor:
            appointment["doctor"] = normalized_doctor
            changed = True

    if appointment_date:

        normalized_date = normalize_date(
            appointment_date
        )

        if normalized_date:

            parsed_date = date.fromisoformat(
                normalized_date
            )

            if parsed_date < date.today():

                return {
                    "success": False,
                    "message": "The appointment date cannot be in the past."
                }

            appointment["date"] = normalized_date
            changed = True

        else:

            return {
                "success": False,
                "message": "The date format could not be understood."
            }

    if appointment_time:

        normalized_time = normalize_time(
            appointment_time
        )

        if not normalized_time:

            return {
                "success": False,
                "message": "The appointment time could not be understood."
            }

        if not valid_clinic_time(normalized_time):

            return {
                "success": False,
                "message": "The appointment time must be between 8:00 AM and 8:00 PM."
            }

        appointment["time"] = normalized_time
        changed = True

    # If an important appointment detail changes,
    # previous availability confirmation is no longer valid.
    if changed:

        session["availability_checked"] = False
        session["awaiting_confirmation"] = False

    return {
        "success": True,
        "appointment": appointment,
        "message": "Appointment information updated successfully."
    }


# ============================================================
# CHECK AVAILABILITY
# ============================================================

def check_availability(session):

    appointment = session["appointment"]

    patient_name = appointment["patient_name"]
    doctor = appointment["doctor"]
    appointment_date = appointment["date"]
    appointment_time = appointment["time"]

    if not doctor:

        return {
            "success": False,
            "message": "Doctor information is missing."
        }

    if not appointment_date:

        return {
            "success": False,
            "message": "Appointment date is missing."
        }

    if not appointment_time:

        return {
            "success": False,
            "message": "Appointment time is missing."
        }

    doctor_id = get_doctor_id(doctor)

    if not doctor_id:

        return {
            "success": False,
            "message": f"{doctor} was not found in the clinic."
        }

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id
            FROM appointments
            WHERE doctor_id = %s
            AND appointment_date = %s
            AND appointment_time = %s
            AND status = 'booked'
            """,
            (
                doctor_id,
                appointment_date,
                appointment_time
            )
        )

        result = cursor.fetchone()

        cursor.close()

        if result:

            session["availability_checked"] = False
            session["awaiting_confirmation"] = False

            return {
                "success": True,
                "available": False,
                "appointment": appointment,
                "message": (
                    f"{doctor} is not available on "
                    f"{appointment_date} at "
                    f"{appointment_time}."
                )
            }

        session["availability_checked"] = True
        session["awaiting_confirmation"] = True

        return {
            "success": True,
            "available": True,
            "appointment": appointment,
            "message": (
                f"{doctor} has an open slot on "
                f"{appointment_date} at "
                f"{appointment_time}."
            )
        }

    finally:

        connection.close()


# ============================================================
# BOOK APPOINTMENT
# ============================================================

def book_appointment(session):

    appointment = session["appointment"]

    patient_name = appointment["patient_name"]
    doctor = appointment["doctor"]
    appointment_date = appointment["date"]
    appointment_time = appointment["time"]

    # The assistant must not book without all information.
    if not patient_name:
        return {
            "success": False,
            "message": "Patient name is missing."
        }

    if not doctor:
        return {
            "success": False,
            "message": "Doctor is missing."
        }

    if not appointment_date:
        return {
            "success": False,
            "message": "Appointment date is missing."
        }

    if not appointment_time:
        return {
            "success": False,
            "message": "Appointment time is missing."
        }

    # Booking is only allowed after availability was checked
    # and the user has reached the confirmation step.
    if not session["availability_checked"]:

        return {
            "success": False,
            "message": (
                "Availability must be checked before booking."
            )
        }

    if not session["awaiting_confirmation"]:

        return {
            "success": False,
            "message": (
                "The appointment is not waiting for confirmation."
            )
        }

    doctor_id = get_doctor_id(doctor)

    if not doctor_id:

        return {
            "success": False,
            "message": "Doctor not found."
        }

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

        # Check again immediately before insertion.
        # This protects against another appointment being
        # booked between availability checking and confirmation.
        cursor.execute(
            """
            SELECT id
            FROM appointments
            WHERE doctor_id = %s
            AND appointment_date = %s
            AND appointment_time = %s
            AND status = 'booked'
            """,
            (
                doctor_id,
                appointment_date,
                appointment_time
            )
        )

        existing = cursor.fetchone()

        if existing:

            connection.rollback()

            session["availability_checked"] = False
            session["awaiting_confirmation"] = False

            cursor.close()

            return {
                "success": False,
                "message": "This appointment slot has just been booked by someone else."
            }

        cursor.execute(
            """
            INSERT INTO appointments
            (
                patient_name,
                doctor_id,
                appointment_date,
                appointment_time,
                status
            )
            VALUES (%s, %s, %s, %s, 'booked')
            """,
            (
                patient_name,
                doctor_id,
                appointment_date,
                appointment_time
            )
        )

        connection.commit()

        cursor.close()

        session["booking_completed"] = True
        session["availability_checked"] = False
        session["awaiting_confirmation"] = False

        return {
            "success": True,
            "appointment": appointment,
            "message": (
                f"Appointment booked successfully for "
                f"{patient_name} with {doctor} on "
                f"{appointment_date} at "
                f"{appointment_time}."
            )
        }

    except errors.UniqueViolation:

        connection.rollback()

        session["availability_checked"] = False
        session["awaiting_confirmation"] = False

        return {
            "success": False,
            "message": "This appointment slot is already booked."
        }

    finally:

        connection.close()


# ============================================================
# RESET APPOINTMENT
# ============================================================

def reset_appointment(session):

    session["appointment"] = {
        "patient_name": None,
        "doctor": None,
        "date": None,
        "time": None
    }

    session["availability_checked"] = False
    session["awaiting_confirmation"] = False
    session["booking_completed"] = False

    return {
        "success": True,
        "message": "The current appointment information has been reset."
    }


# ============================================================
# GROQ TOOLS
# ============================================================

tools = [

    {
        "type": "function",
        "function": {
            "name": "update_appointment",
            "description": (
                "Save appointment information provided explicitly "
                "by the user into the current session."
            ),
            "parameters": {
                "type": "object",
                "properties": {

                    "patient_name": {
                        "type": "string",
                        "description": "Patient name if explicitly provided."
                    },

                    "doctor": {
                        "type": "string",
                        "description": "Doctor name if explicitly provided."
                    },

                    "appointment_date": {
                        "type": "string",
                        "description": "Appointment date if explicitly provided."
                    },

                    "appointment_time": {
                        "type": "string",
                        "description": "Appointment time if explicitly provided."
                    }

                },
                "required": []
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "check_doctor",
            "description": (
                "Check whether a requested doctor exists "
                "in the clinic database."
            ),
            "parameters": {
                "type": "object",
                "properties": {

                    "doctor_name": {
                        "type": "string",
                        "description": "Doctor name to check."
                    }

                },
                "required": ["doctor_name"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": (
                "Check whether the currently stored appointment "
                "slot is available."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": (
                "Book the currently stored appointment after "
                "availability has been checked and the user "
                "has confirmed the booking."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "reset_appointment",
            "description": (
                "Clear the current appointment information "
                "when the user wants to start over."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }

]


# ============================================================
# SYSTEM INSTRUCTION
# ============================================================

SYSTEM_INSTRUCTION = """
You are an AI clinic appointment assistant.

Your responsibilities are:

1. Help users book clinic appointments.
2. Check doctor information.
3. Check appointment availability.
4. Book appointments after user confirmation.
5. Keep appointment information during the current session.
6. Reset appointment information when requested.

IMPORTANT RULES:

- Never invent patient information.
- Never invent a doctor.
- Never invent a date.
- Never invent a time.
- Only save information explicitly provided by the user.
- Use the update_appointment tool when the user provides appointment information.
- Use check_doctor when you need to verify a doctor.
- Use check_availability only when doctor, date and time are available.
- Use book_appointment only after availability has been successfully checked
  and the user has explicitly confirmed the booking.
- If required information is missing, ask the user for it.
- If the user changes the doctor, date or time, availability must be checked again.
- Do not assume that an old availability check is still valid after information changes.
- Do not display raw tool results to the user.
- Respond politely and concisely.

The current appointment state supplied by the application is authoritative.
Do not replace it with information from your own guess.

When the user says something like "yes", "confirm", "book it",
or "yes book it", treat it as confirmation ONLY if the assistant
has already told the user that the requested slot is available.
"""


# ============================================================
# SERIALIZE GROQ ASSISTANT MESSAGE
# ============================================================

def serialize_assistant_message(message):

    assistant_message = {
        "role": "assistant",
        "content": message.content or ""
    }

    if message.tool_calls:

        assistant_message["tool_calls"] = []

        for tool_call in message.tool_calls:

            assistant_message["tool_calls"].append(
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    }
                }
            )

    return assistant_message


# ============================================================
# EXECUTE TOOL
# ============================================================

def execute_tool(
    session,
    tool_name,
    arguments
):

    if tool_name == "update_appointment":

        return update_appointment(
            session=session,
            patient_name=arguments.get("patient_name"),
            doctor=arguments.get("doctor"),
            appointment_date=arguments.get("appointment_date"),
            appointment_time=arguments.get("appointment_time")
        )

    if tool_name == "check_doctor":

        return check_doctor(
            arguments.get("doctor_name")
        )

    if tool_name == "check_availability":

        return check_availability(
            session
        )

    if tool_name == "book_appointment":

        return book_appointment(
            session
        )

    if tool_name == "reset_appointment":

        return reset_appointment(
            session
        )

    return {
        "success": False,
        "message": "Unknown tool."
    }


# ============================================================
# CHAT REQUEST
# ============================================================

class ChatRequest(BaseModel):

    session_id: str
    message: str


# ============================================================
# CHAT ENDPOINT
# ============================================================

@app.post("/chat")
def chat(request: ChatRequest):

    session = get_session(
        request.session_id
    )

    appointment_state = json.dumps(
        session["appointment"]
    )

    state_message = {
        "role": "system",
        "content": (
            "CURRENT APPOINTMENT STATE FROM PYTHON:\n"
            + appointment_state
            + "\n\n"
            "This state is authoritative. "
            "Do not invent or replace values."
        )
    }

    messages = [
        {
            "role": "system",
            "content": SYSTEM_INSTRUCTION
        },
        state_message
    ]

    # Add previous conversation history.
    messages.extend(
        session["messages"]
    )

    # Add current user message.
    messages.append(
        {
            "role": "user",
            "content": request.message
        }
    )

    # --------------------------------------------------------
    # FIRST GROQ REQUEST
    # --------------------------------------------------------

    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=messages,
        tools=tools,
        tool_choice="auto",
        temperature=0,
        max_tokens=700
    )

    assistant_message = response.choices[0].message

    # --------------------------------------------------------
    # TOOL-CALL LOOP
    # --------------------------------------------------------

    while assistant_message.tool_calls:

        serialized_message = serialize_assistant_message(
            assistant_message
        )

        messages.append(
            serialized_message
        )

        for tool_call in assistant_message.tool_calls:

            tool_name = tool_call.function.name

            try:

                arguments = json.loads(
                    tool_call.function.arguments
                )

            except json.JSONDecodeError:

                arguments = {}

            tool_result = execute_tool(
                session=session,
                tool_name=tool_name,
                arguments=arguments
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(
                        tool_result
                    )
                }
            )

        # Ask Groq what to say after the tool result.
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0,
            max_tokens=700
        )

        assistant_message = response.choices[0].message

    # --------------------------------------------------------
    # FINAL ASSISTANT RESPONSE
    # --------------------------------------------------------

    final_message = assistant_message.content or ""

    messages.append(
        serialize_assistant_message(
            assistant_message
        )
    )

    # --------------------------------------------------------
    # SAVE CONVERSATION HISTORY
    #
    # We only save messages after the initial system messages.
    # This preserves user messages, assistant tool calls,
    # tool results and final assistant responses.
    # --------------------------------------------------------

    conversation_messages = []

    for message in messages:

        if message["role"] != "system":
            conversation_messages.append(
                message
            )

    session["messages"] = conversation_messages

    # --------------------------------------------------------
    # RETURN CURRENT PYTHON STATE
    # --------------------------------------------------------

    return {
        "session_id": request.session_id,
        "response": final_message,
        "appointment": session["appointment"],
        "availability_checked": session["availability_checked"],
        "awaiting_confirmation": session["awaiting_confirmation"],
        "booking_completed": session["booking_completed"]
    }


# ============================================================
# GET CURRENT APPOINTMENT
# ============================================================

@app.get("/appointment/{session_id}")
def get_appointment(session_id: str):

    session = get_session(
        session_id
    )

    return {
        "session_id": session_id,
        "appointment": session["appointment"],
        "availability_checked": session["availability_checked"],
        "awaiting_confirmation": session["awaiting_confirmation"],
        "booking_completed": session["booking_completed"]
    }


# ============================================================
# RESET SESSION
# ============================================================

@app.delete("/appointment/{session_id}")
def delete_appointment(session_id: str):

    sessions[session_id] = create_session()

    return {
        "success": True,
        "message": "Session appointment information has been reset."
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "stage": "Stage 7"
    }


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "message": "AI Appointment Assistant - Stage 7",
        "status": "running"
    }