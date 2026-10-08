from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import json
from datetime import date, datetime, time as dt_time

import psycopg2
from psycopg2 import errors
from dotenv import load_dotenv
from groq import Groq


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://ai-appointment-assistant-sooty.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
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

    doctor_changed = False
    date_changed = False
    time_changed = False

    # Patient name does NOT invalidate availability.
    if patient_name:

        new_patient_name = patient_name.strip()

        if new_patient_name:
            appointment["patient_name"] = new_patient_name

    # Doctor changes invalidate previous availability.
    if doctor:

        normalized_doctor = normalize_doctor(doctor)

        if normalized_doctor:

            if appointment["doctor"] != normalized_doctor:
                doctor_changed = True

            appointment["doctor"] = normalized_doctor

    # Date changes invalidate previous availability.
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

            if appointment["date"] != normalized_date:
                date_changed = True

            appointment["date"] = normalized_date

        else:

            return {
                "success": False,
                "message": "The date format could not be understood."
            }

    # Time changes invalidate previous availability.
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
                "message": (
                    "The appointment time must be between "
                    "8:00 AM and 8:00 PM."
                )
            }

        if appointment["time"] != normalized_time:
            time_changed = True

        appointment["time"] = normalized_time

    # Only doctor/date/time changes invalidate availability.
    if doctor_changed or date_changed or time_changed:

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

        # Check the slot again immediately before booking.
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
                "message": (
                    "This appointment slot has just been "
                    "booked by someone else."
                )
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
                "Save appointment information explicitly provided "
                "by the user. Patient name is information only and "
                "is never booking confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {

                    "patient_name": {
                        "type": "string",
                        "description": (
                            "Patient name if explicitly provided. "
                            "Saving a patient name never means the "
                            "user confirmed booking."
                        )
                    },

                    "doctor": {
                        "type": "string",
                        "description": (
                            "Doctor name if explicitly provided."
                        )
                    },

                    "appointment_date": {
                        "type": "string",
                        "description": (
                            "Appointment date if explicitly provided."
                        )
                    },

                    "appointment_time": {
                        "type": "string",
                        "description": (
                            "Appointment time if explicitly provided."
                        )
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
                "doctor, date and time are available."
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
                "Book the stored appointment ONLY after the "
                "availability has been checked AND the user has "
                "explicitly confirmed booking in a separate turn."
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

Your job is to help users check doctors, find available
appointment slots, collect patient information, and book
appointments.

STRICT BOOKING FLOW:

STEP 1:
Collect the doctor, appointment date, and appointment time.

STEP 2:
Use check_doctor to verify the doctor.

STEP 3:
Use check_availability after doctor, date, and time are available.

STEP 4:
If the slot is available, ask for the patient's name if it
has not already been provided.

STEP 5:
After the patient provides their name, DO NOT book the
appointment yet.

You MUST ask for explicit booking confirmation.

For example:

Assistant:
"Thanks, Tayyiba. Would you like me to book this appointment?"

STEP 6:
Only when the user gives a clear booking confirmation such as:

"yes"
"yes, book it"
"confirm"
"please book it"
"book the appointment"

may you call book_appointment.

CRITICAL RULE:

A patient name is NEVER booking confirmation.

These are name information only:

"I'm Tayyiba"
"My name is Tayyiba"
"Tayyiba"
"Yes, I'm Tayyiba"
"Sure, my name is Tayyiba"

Even if the user says:

"yes I'm Tayyiba"

the word "yes" does NOT mean booking confirmation.

Save the name and then ask for explicit booking confirmation.

Example:

User:
"yes I'm Tayyiba"

Correct behavior:
Save patient name = Tayyiba.
Do NOT call book_appointment.
Ask:
"Thanks, Tayyiba. Would you like me to book this appointment?"

IMPORTANT:

The booking confirmation must be a separate user turn after
the assistant has asked for confirmation.

Never interpret a message that provides a newly supplied
patient name as confirmation.

OTHER RULES:

- Never invent patient information.
- Never invent a doctor.
- Never invent a date.
- Never invent a time.
- Only save information explicitly provided by the user.
- Use update_appointment for information explicitly provided.
- Use check_doctor to verify doctors.
- Use check_availability only when doctor, date and time exist.
- Use book_appointment only after explicit confirmation.
- If the doctor, date, or time changes, availability must be checked again.
- Providing or changing the patient name does NOT invalidate availability.
- Do not display raw tool results.
- Respond politely and concisely.
- After successful booking, simply tell the user that the appointment
  has been booked successfully.
- Do NOT promise SMS, email, phone calls, notifications, or
  "confirmation shortly" because no notification system exists.

CURRENT APPOINTMENT STATE supplied by Python is authoritative.
Do not invent or replace state values.

If booking is successful, clearly state that the appointment
has been booked and include the patient name, doctor, date,
and time when appropriate.
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

    # Remember whether the patient name existed BEFORE
    # the current user message.
    patient_name_before_message = (
        session["appointment"]["patient_name"]
    )

    # Tracks whether the patient name was updated during
    # this specific user turn.
    patient_name_updated_this_turn = False

    appointment_state = json.dumps(
        session["appointment"]
    )

    state_message = {
        "role": "system",
        "content": (
            "CURRENT APPOINTMENT STATE FROM PYTHON:\n"
            + appointment_state
            + "\n\n"
            "CURRENT FLAGS:\n"
            + json.dumps(
                {
                    "availability_checked":
                        session["availability_checked"],
                    "awaiting_confirmation":
                        session["awaiting_confirmation"],
                    "booking_completed":
                        session["booking_completed"]
                }
            )
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

    messages.extend(
        session["messages"]
    )

    messages.append(
        {
            "role": "user",
            "content": request.message
        }
    )

    # ========================================================
    # FIRST GROQ REQUEST
    # ========================================================

    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=messages,
        tools=tools,
        tool_choice="auto",
        temperature=0,
        max_tokens=700
    )

    assistant_message = response.choices[0].message

    # ========================================================
    # TOOL-CALL LOOP
    # ========================================================

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

            # ------------------------------------------------
            # Track patient-name updates during this turn.
            # ------------------------------------------------

            if (
                tool_name == "update_appointment"
                and arguments.get("patient_name")
            ):

                patient_name_updated_this_turn = True

            # ------------------------------------------------
            # HARD SAFETY GUARD
            #
            # If the patient name was newly supplied during
            # this turn, booking is NOT allowed in the same
            # turn.
            # ------------------------------------------------

            if (
                tool_name == "book_appointment"
                and patient_name_updated_this_turn
            ):

                tool_result = {
                    "success": False,
                    "message": (
                        "The patient name was provided in this "
                        "same user turn. Do NOT book yet. "
                        "The assistant must ask the user for "
                        "explicit booking confirmation in a "
                        "separate turn first."
                    )
                }

            else:

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

        # ====================================================
        # ASK GROQ WHAT TO DO AFTER TOOL RESULTS
        # ====================================================

        updated_state_message = {
            "role": "system",
            "content": (
                "UPDATED CURRENT APPOINTMENT STATE FROM PYTHON:\n"
                + json.dumps(session["appointment"])
                + "\n\n"
                "UPDATED FLAGS:\n"
                + json.dumps(
                    {
                        "availability_checked":
                            session["availability_checked"],
                        "awaiting_confirmation":
                            session["awaiting_confirmation"],
                        "booking_completed":
                            session["booking_completed"]
                    }
                )
                + "\n\n"
                "The Python state is authoritative."
            )
        }

        messages.append(
            updated_state_message
        )

        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0,
            max_tokens=700
        )

        assistant_message = response.choices[0].message

    # ========================================================
    # FINAL ASSISTANT RESPONSE
    # ========================================================

    final_message = assistant_message.content or ""

    # Extra protection against an accidental booking response
    # when the name was supplied for the first time this turn.
    if (
        patient_name_updated_this_turn
        and session["booking_completed"]
        and patient_name_before_message is None
    ):

        # This should normally never be reached because the
        # hard tool guard above blocks the booking.
        # It exists as an additional safety layer.
        session["booking_completed"] = False

    messages.append(
        serialize_assistant_message(
            assistant_message
        )
    )

    # ========================================================
    # SAVE CONVERSATION HISTORY
    # ========================================================

    conversation_messages = []

    for message in messages:

        if message["role"] != "system":

            conversation_messages.append(
                message
            )

    session["messages"] = conversation_messages

    # ========================================================
    # RETURN CURRENT PYTHON STATE
    # ========================================================

    return {
        "session_id": request.session_id,
        "response": final_message,
        "appointment": session["appointment"],
        "availability_checked":
            session["availability_checked"],
        "awaiting_confirmation":
            session["awaiting_confirmation"],
        "booking_completed":
            session["booking_completed"]
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
        "availability_checked":
            session["availability_checked"],
        "awaiting_confirmation":
            session["awaiting_confirmation"],
        "booking_completed":
            session["booking_completed"]
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