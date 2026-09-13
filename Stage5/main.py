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
# ENVIRONMENT
# ============================================================

load_dotenv()

groq_api_key = os.getenv("GROQ_API_KEY")

if not groq_api_key:
    raise ValueError("GROQ_API_KEY not found in .env file")

client = Groq(api_key=groq_api_key)


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="AI Appointment Assistant",
    description="AI-powered clinic appointment booking API",
    version="5.0"
)


# ============================================================
# REQUEST MODEL
# ============================================================

class ChatRequest(BaseModel):
    message: str


# ============================================================
# APPOINTMENT STATE
# ============================================================

current_appointment = {
    "patient_name": None,
    "doctor": None,
    "date": None,
    "time": None
}


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
            parsed_date = datetime.strptime(cleaned, fmt).date()
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
            parsed_time = datetime.strptime(time_text, fmt)
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

    doctor_id = get_doctor_id(normalized_doctor)

    if doctor_id:

        return {
            "exists": True,
            "doctor": normalized_doctor
        }

    return {
        "exists": False,
        "doctor": normalized_doctor
    }


# ============================================================
# CHECK AVAILABILITY
# ============================================================

def check_availability(
    doctor_name,
    appointment_date,
    appointment_time
):

    doctor_id = get_doctor_id(doctor_name)

    if not doctor_id:

        return {
            "available": False,
            "message": "Doctor not found."
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

            return {
                "available": False,
                "message": "This appointment slot is already booked."
            }

        return {
            "available": True,
            "message": "This appointment slot is available."
        }

    finally:

        connection.close()


# ============================================================
# BOOK APPOINTMENT
# ============================================================

def book_appointment():

    patient_name = current_appointment["patient_name"]
    doctor = current_appointment["doctor"]
    appointment_date = current_appointment["date"]
    appointment_time = current_appointment["time"]

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

    doctor_id = get_doctor_id(doctor)

    if not doctor_id:

        return {
            "success": False,
            "message": "Doctor not found."
        }

    connection = get_db_connection()

    try:

        cursor = connection.cursor()

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

        return {
            "success": True,
            "message": "Appointment booked successfully."
        }

    except errors.UniqueViolation:

        connection.rollback()

        return {
            "success": False,
            "message": "This appointment slot is already booked."
        }

    finally:

        connection.close()


# ============================================================
# UPDATE APPOINTMENT STATE
# ============================================================

def update_appointment(
    patient_name=None,
    doctor=None,
    appointment_date=None,
    appointment_time=None
):

    if patient_name:
        current_appointment["patient_name"] = patient_name

    if doctor:

        normalized_doctor = normalize_doctor(doctor)

        current_appointment["doctor"] = normalized_doctor

    if appointment_date:

        normalized_date = normalize_date(appointment_date)

        if not normalized_date:

            return {
                "success": False,
                "message": "Invalid date format."
            }

        current_appointment["date"] = normalized_date

    if appointment_time:

        normalized_time = normalize_time(appointment_time)

        if not normalized_time:

            return {
                "success": False,
                "message": "Invalid time format."
            }

        if not valid_clinic_time(normalized_time):

            return {
                "success": False,
                "message": "Clinic accepts appointments between 08:00 AM and 08:00 PM."
            }

        current_appointment["time"] = normalized_time

    return {
        "success": True,
        "appointment": current_appointment
    }


# ============================================================
# RESET APPOINTMENT
# ============================================================

def reset_appointment():

    current_appointment["patient_name"] = None
    current_appointment["doctor"] = None
    current_appointment["date"] = None
    current_appointment["time"] = None

    return {
        "success": True,
        "message": "Appointment state has been reset."
    }


# ============================================================
# TOOL DEFINITIONS
# ============================================================

tools = [

    {
        "type": "function",
        "function": {
            "name": "update_appointment",
            "description": "Update one or more pieces of appointment information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {
                        "type": "string"
                    },
                    "doctor": {
                        "type": "string"
                    },
                    "appointment_date": {
                        "type": "string"
                    },
                    "appointment_time": {
                        "type": "string"
                    }
                }
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "check_doctor",
            "description": "Check whether a doctor exists in the clinic database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_name": {
                        "type": "string"
                    }
                },
                "required": [
                    "doctor_name"
                ]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Check whether a specific doctor, date and time are available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_name": {
                        "type": "string"
                    },
                    "appointment_date": {
                        "type": "string"
                    },
                    "appointment_time": {
                        "type": "string"
                    }
                },
                "required": [
                    "doctor_name",
                    "appointment_date",
                    "appointment_time"
                ]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book the currently prepared appointment after the user has confirmed it.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "reset_appointment",
            "description": "Reset the current appointment information.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


# ============================================================
# TOOL EXECUTION
# ============================================================

def execute_tool(tool_name, arguments):

    if tool_name == "update_appointment":

        return update_appointment(
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
            arguments.get("doctor_name"),
            arguments.get("appointment_date"),
            arguments.get("appointment_time")
        )

    if tool_name == "book_appointment":

        return book_appointment()

    if tool_name == "reset_appointment":

        return reset_appointment()

    return {
        "error": "Unknown tool."
    }


# ============================================================
# SYSTEM INSTRUCTION
# ============================================================

system_instruction = """
You are a clinic appointment assistant.

Your job is to help users book appointments.

You have access to tools for:
- updating appointment information
- checking doctors
- checking availability
- booking appointments
- resetting appointment state

IMPORTANT RULES:

1. Do not invent doctors.
2. Do not invent appointment information.
3. If information is missing, ask the user for it.
4. Use update_appointment when the user provides appointment information.
5. Use check_doctor when a doctor is provided.
6. Before booking, make sure patient name, doctor, date and time are available.
7. Check availability before telling the user that a slot is available.
8. Never book an appointment without explicit confirmation from the user.
9. Only call book_appointment after the user clearly says yes, confirm, or equivalent.
10. If the user cancels, use reset_appointment.
11. Be concise and polite.
12. The clinic operates between 08:00 AM and 08:00 PM.
"""


# ============================================================
# CHAT ENDPOINT
# ============================================================

@app.post("/chat")
def chat(request: ChatRequest):

    messages = [
        {
            "role": "system",
            "content": system_instruction
        },
        {
            "role": "user",
            "content": request.message
        }
    ]

    while True:

        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0,
            max_tokens=1000
        )

        assistant_message = response.choices[0].message

        tool_calls = assistant_message.tool_calls

        if not tool_calls:

            return {
                "response": assistant_message.content,
                "appointment": current_appointment
            }

        messages.append(assistant_message)

        for tool_call in tool_calls:

            tool_name = tool_call.function.name

            arguments = json.loads(
                tool_call.function.arguments
            )

            print(
                f"Groq selected tool: {tool_name}"
            )

            print(
                f"Arguments: {arguments}"
            )

            result = execute_tool(
                tool_name,
                arguments
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result)
                }
            )


# ============================================================
# ROOT ENDPOINT
# ============================================================

@app.get("/")
def home():

    return {
        "message": "AI Appointment Assistant API is running."
    }

