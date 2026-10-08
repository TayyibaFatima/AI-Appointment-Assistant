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

    appointment_details_changed = False

    # Patient name does NOT invalidate availability.
    if patient_name:

        appointment["patient_name"] = patient_name.strip()

    # Doctor/date/time changes invalidate previous availability.
    if doctor:

        normalized_doctor = normalize_doctor(doctor)

        if normalized_doctor:

            if appointment["doctor"] != normalized_doctor:
                appointment_details_changed = True

            appointment["doctor"] = normalized_doctor

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
                appointment_details_changed = True

            appointment["date"] = normalized_date

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
                "message": (
                    "The appointment time must be between "
                    "8:00 AM and 8:00 PM."
                )
            }

        if appointment["time"] != normalized_time:
            appointment_details_changed = True

        appointment["time"] = normalized_time

    # Only doctor/date/time changes reset availability.
    if appointment_details_changed:

        session["availability_checked"] = False
        session["awaiting_confirmation"] = False
        session["booking_completed"] = False

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
                f"Yes, {doctor} is available on "
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
            "message": "Availability must be checked before booking."
        }

    if not session["awaiting_confirmation"]:

        return {
            "success": False,
            "message": "The appointment is not waiting for confirmation."
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

        # Recheck immediately before booking.
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
            "message": "Appointment booked successfully."
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
                "by the user."
            ),
            "parameters": {
                "type": "object",
                "properties": {

                    "patient_name": {
                        "type": "string",
                        "description": (
                            "Patient name if explicitly provided."
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
                "Check whether the currently stored "
                "appointment slot is available."
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
                "Book the currently stored appointment only "
                "after availability has been checked and "
                "the user has explicitly confirmed."
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

Your job is to have a natural, concise conversation while
helping users check doctors, find available slots, collect
their name, and book appointments.

IMPORTANT BOOKING FLOW:

1. Ask for doctor, date and time.

2. Save the information using update_appointment.

3. Verify the doctor using check_doctor.

4. Check availability using check_availability.

5. If the requested slot is unavailable, clearly tell the user
   that the doctor is not available at that time and ask whether
   they would like another time or doctor.

6. If the requested slot is available, respond naturally.

For example:

"Yes, Dr. Sara is available on 2026-10-15 at 09:00.
What name should I put the appointment under?"

Do NOT say "Great!" every time a slot is available.

7. After the user gives their name, ask for explicit confirmation.

For example:

"Thanks, Tayyiba. Would you like me to book this appointment?"

8. A patient's name is NEVER booking confirmation.

For example:

"yes I'm Tayyiba"

is a name/message containing a name, NOT confirmation.

9. Only book after a separate explicit confirmation such as:

"yes"
"yes please"
"yes, book it"
"book it"
"confirm"
"confirmed"
"please book it"
"go ahead"
"book the appointment"

10. Never promise SMS, email, notifications, reminders,
or a confirmation being sent because this system does not
have a notification service.

11. After successful booking, give a short plain-text
confirmation with the appointment details.

Use this style:

Your appointment has been booked successfully!

Patient: Tayyiba
Doctor: Dr. Sara
Date: 2026-10-15
Time: 09:00

Do NOT use Markdown bold formatting.
Do NOT put ** around the fields.

12. If the user changes the doctor, date or time,
availability must be checked again.

13. If the user only provides their name, availability
must NOT be reset.

14. Never invent patient information, doctor information,
dates, times, or availability.

15. The Python appointment state is authoritative.

16. Respond naturally and concisely.
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
# CONFIRMATION DETECTION
# ============================================================

def is_booking_confirmation(message):

    text = " ".join(
        message.strip().lower().split()
    )

    # Exact standalone confirmations.
    exact_confirmations = {
        "yes",
        "yes please",
        "sure",
        "okay",
        "ok",
        "confirm",
        "confirmed",
        "go ahead",
        "book it",
        "book the appointment",
        "please book it"
    }

    if text in exact_confirmations:
        return True

    # Explicit booking language.
    confirmation_starts = (
        "yes ",
        "sure ",
        "please ",
        "go ahead ",
        "confirm ",
        "book "
    )

    booking_words = (
        "book",
        "appointment",
        "confirm"
    )

    if text.startswith(confirmation_starts):

        if any(
            word in text
            for word in booking_words
        ):
            return True

    return False


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

    appointment = session["appointment"]

    user_message = request.message.strip()

    # --------------------------------------------------------
    # DIRECT CONFIRMATION HANDLING
    #
    # This prevents Groq from asking for confirmation twice.
    # --------------------------------------------------------

    if (
        session["availability_checked"]
        and session["awaiting_confirmation"]
        and appointment["patient_name"]
        and appointment["doctor"]
        and appointment["date"]
        and appointment["time"]
        and is_booking_confirmation(user_message)
    ):

        booking_result = book_appointment(
            session
        )

        if booking_result["success"]:

            final_message = (
                "Your appointment has been booked successfully!\n\n"
                f"Patient: {appointment['patient_name']}\n"
                f"Doctor: {appointment['doctor']}\n"
                f"Date: {appointment['date']}\n"
                f"Time: {appointment['time']}"
            )

        else:

            final_message = booking_result["message"]

        session["messages"].append(
            {
                "role": "user",
                "content": request.message
            }
        )

        session["messages"].append(
            {
                "role": "assistant",
                "content": final_message
            }
        )

        return {
            "session_id": request.session_id,
            "response": final_message,
            "appointment": session["appointment"],
            "availability_checked": session["availability_checked"],
            "awaiting_confirmation": session["awaiting_confirmation"],
            "booking_completed": session["booking_completed"]
        }

    # --------------------------------------------------------
    # CURRENT APPOINTMENT STATE
    # --------------------------------------------------------

    appointment_state = json.dumps(
        session["appointment"]
    )

    state_message = {
        "role": "system",
        "content": (
            "CURRENT APPOINTMENT STATE FROM PYTHON:\n"
            + appointment_state
            + "\n\n"
            "AVAILABILITY CHECKED: "
            + str(session["availability_checked"])
            + "\n"
            "AWAITING CONFIRMATION: "
            + str(session["awaiting_confirmation"])
            + "\n"
            "BOOKING COMPLETED: "
            + str(session["booking_completed"])
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

    # --------------------------------------------------------
    # PREVIOUS CONVERSATION
    # --------------------------------------------------------

    messages.extend(
        session["messages"]
    )

    # --------------------------------------------------------
    # CURRENT USER MESSAGE
    # --------------------------------------------------------

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

        # Detect whether the user supplied a name in this turn.
        #
        # If update_appointment contains patient_name,
        # booking must NOT happen in that same turn.
        patient_name_updated_this_turn = False

        for tool_call in assistant_message.tool_calls:

            tool_name = tool_call.function.name

            try:

                arguments = json.loads(
                    tool_call.function.arguments
                )

            except json.JSONDecodeError:

                arguments = {}

            if (
                tool_name == "update_appointment"
                and arguments.get("patient_name")
            ):

                patient_name_updated_this_turn = True

            if (
                tool_name == "book_appointment"
                and patient_name_updated_this_turn
            ):

                tool_result = {
                    "success": False,
                    "message": (
                        "The patient name was provided in this "
                        "same user turn. Do not book yet. "
                        "Ask for explicit booking confirmation "
                        "in a separate user turn."
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

        # ----------------------------------------------------
        # ASK GROQ FOR FINAL RESPONSE
        # ----------------------------------------------------

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

    # Remove accidental Markdown bold from booking details.
    final_message = final_message.replace("**", "")

    messages.append(
        {
            "role": "assistant",
            "content": final_message
        }
    )

    # --------------------------------------------------------
    # SAVE CONVERSATION HISTORY
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