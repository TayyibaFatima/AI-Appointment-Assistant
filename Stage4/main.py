import os
import json
from datetime import date, datetime, time as dt_time

import psycopg2
from psycopg2 import errors
from dotenv import load_dotenv
from groq import Groq
from pydantic import BaseModel


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()

groq_api_key = os.getenv("GROQ_API_KEY")

if not groq_api_key:
    raise ValueError("GROQ_API_KEY not found in .env file")


# ============================================================
# GROQ CLIENT
# ============================================================

client = Groq(api_key=groq_api_key)

MODEL = "openai/gpt-oss-20b"


# ============================================================
# PYDANTIC MODEL
# ============================================================

class Appointment(BaseModel):

    patient_name: str | None = None
    doctor: str | None = None
    date: str | None = None
    time: str | None = None


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
# NORMALIZE DOCTOR NAME
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

    if time_text in [
        "morning",
        "in the morning"
    ]:

        return "Morning"

    if time_text in [
        "afternoon",
        "in the afternoon"
    ]:

        return "Afternoon"

    if time_text in [
        "evening",
        "in the evening"
    ]:

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
# CHECK IF SPECIFIC TIME IS WITHIN CLINIC HOURS
# ============================================================

def valid_clinic_time(time_text):

    if time_text in [
        "Morning",
        "Afternoon",
        "Evening"
    ]:

        return True

    try:

        parsed_time = datetime.strptime(
            time_text,
            "%H:%M"
        ).time()

        opening_time = dt_time(8, 0)

        closing_time = dt_time(20, 0)

        return (
            opening_time
            <= parsed_time
            <= closing_time
        )

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
# TOOL 1: CHECK DOCTOR
# ============================================================
#
# In Stage 3:
#
# Python directly called doctor_exists().
#
# In Stage 4:
#
# Groq decides when this tool should be called.
# ============================================================

def check_doctor(doctor_name):

    doctor_name = normalize_doctor(doctor_name)

    doctor_id = get_doctor_id(doctor_name)

    if doctor_id:

        return {
            "exists": True,
            "doctor": doctor_name,
            "doctor_id": doctor_id
        }

    return {
        "exists": False,
        "doctor": doctor_name,
        "message": "Doctor not found in the clinic."
    }


# ============================================================
# TOOL 2: UPDATE APPOINTMENT
# ============================================================
#
# This stores information collected from the user.
#
# Groq decides when this tool should be used.
# ============================================================

current_appointment = Appointment()


def update_appointment(
    patient_name=None,
    doctor=None,
    appointment_date=None,
    appointment_time=None
):

    global current_appointment

    if patient_name:

        current_appointment.patient_name = (
            patient_name.strip()
        )

    if doctor:

        current_appointment.doctor = (
            normalize_doctor(doctor)
        )

    if appointment_date:

        normalized_date = normalize_date(
            appointment_date
        )

        if normalized_date:

            current_appointment.date = (
                normalized_date
            )

    if appointment_time:

        normalized_time = normalize_time(
            appointment_time
        )

        if normalized_time:

            current_appointment.time = (
                normalized_time
            )

    return {
        "success": True,
        "appointment": current_appointment.model_dump()
    }


# ============================================================
# TOOL 3: CHECK AVAILABILITY
# ============================================================
#
# THIS IS THE MOST IMPORTANT CHANGE FROM STAGE 3.
#
# We DO NOT directly call this function from the main loop.
#
# Groq decides whether this tool is needed.
# ============================================================

def check_availability(
    doctor_name,
    appointment_date,
    appointment_time
):

    doctor_name = normalize_doctor(
        doctor_name
    )

    appointment_date = normalize_date(
        appointment_date
    )

    appointment_time = normalize_time(
        appointment_time
    )

    # --------------------------------------------------------
    # Check doctor
    # --------------------------------------------------------

    doctor_id = get_doctor_id(
        doctor_name
    )

    if not doctor_id:

        return {
            "available": False,
            "reason": "doctor_not_found",
            "message": "Doctor not found."
        }

    # --------------------------------------------------------
    # Check time
    # --------------------------------------------------------

    if not appointment_time:

        return {
            "available": False,
            "reason": "invalid_time",
            "message": "Invalid appointment time."
        }

    if not valid_clinic_time(
        appointment_time
    ):

        return {
            "available": False,
            "reason": "outside_clinic_hours",
            "message": (
                "Please choose a time between "
                "08:00 AM and 08:00 PM."
            )
        }

    # --------------------------------------------------------
    # Check database
    # --------------------------------------------------------

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

        if result is None:

            return {
                "available": True,
                "doctor": doctor_name,
                "date": appointment_date,
                "time": appointment_time,
                "message": "The appointment slot is available."
            }

        return {
            "available": False,
            "doctor": doctor_name,
            "date": appointment_date,
            "time": appointment_time,
            "message": "This appointment slot is already booked."
        }

    finally:

        connection.close()


# ============================================================
# TOOL 4: BOOK APPOINTMENT
# ============================================================
#
# Groq should call this ONLY after the user confirms.
#
# Python does NOT directly call this from the main loop.
# ============================================================

def book_appointment(
    patient_name,
    doctor_name,
    appointment_date,
    appointment_time
):

    doctor_name = normalize_doctor(
        doctor_name
    )

    appointment_date = normalize_date(
        appointment_date
    )

    appointment_time = normalize_time(
        appointment_time
    )

    doctor_id = get_doctor_id(
        doctor_name
    )

    if not doctor_id:

        return {
            "success": False,
            "message": "Doctor not found."
        }

    if not valid_clinic_time(
        appointment_time
    ):

        return {
            "success": False,
            "message": (
                "The requested time is outside "
                "clinic hours."
            )
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
            "message": "Appointment booked successfully.",
            "appointment": {
                "patient_name": patient_name,
                "doctor": doctor_name,
                "date": appointment_date,
                "time": appointment_time
            }
        }

    except errors.UniqueViolation:

        connection.rollback()

        return {
            "success": False,
            "message": (
                "This appointment slot is already booked."
            )
        }

    finally:

        connection.close()


# ============================================================
# TOOL 5: RESET APPOINTMENT
# ============================================================

def reset_appointment():

    global current_appointment

    current_appointment = Appointment()

    return {
        "success": True,
        "message": "Appointment information has been reset."
    }


# ============================================================
# TOOL DEFINITIONS
# ============================================================
#
# These are NOT the actual Python functions.
#
# These are descriptions of the functions that Groq can see.
#
# Groq uses these descriptions to decide which function
# should be called.
# ============================================================

tools = [

    {
        "type": "function",

        "function": {

            "name": "update_appointment",

            "description": (
                "Save appointment information explicitly "
                "provided by the user."
            ),

            "parameters": {

                "type": "object",

                "properties": {

                    "patient_name": {
                        "type": "string",
                        "description": "Patient's name"
                    },

                    "doctor": {
                        "type": "string",
                        "description": "Doctor name"
                    },

                    "appointment_date": {
                        "type": "string",
                        "description": "Appointment date"
                    },

                    "appointment_time": {
                        "type": "string",
                        "description": "Appointment time"
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
                "Check whether the requested doctor exists "
                "in the clinic database."
            ),

            "parameters": {

                "type": "object",

                "properties": {

                    "doctor_name": {
                        "type": "string",
                        "description": "Doctor name"
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

            "description": (
                "Check whether a specific doctor, date, "
                "and time slot is available."
            ),

            "parameters": {

                "type": "object",

                "properties": {

                    "doctor_name": {
                        "type": "string",
                        "description": "Doctor name"
                    },

                    "appointment_date": {
                        "type": "string",
                        "description": "Appointment date"
                    },

                    "appointment_time": {
                        "type": "string",
                        "description": "Appointment time"
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

            "description": (
                "Book the appointment in the database. "
                "ONLY use this after the user explicitly "
                "confirms that they want to book the appointment."
            ),

            "parameters": {

                "type": "object",

                "properties": {

                    "patient_name": {
                        "type": "string",
                        "description": "Patient's name"
                    },

                    "doctor_name": {
                        "type": "string",
                        "description": "Doctor name"
                    },

                    "appointment_date": {
                        "type": "string",
                        "description": "Appointment date"
                    },

                    "appointment_time": {
                        "type": "string",
                        "description": "Appointment time"
                    }

                },

                "required": [
                    "patient_name",
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

            "name": "reset_appointment",

            "description": (
                "Reset the current appointment when "
                "the user wants to book another appointment."
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
# FUNCTION MAP
# ============================================================
#
# Groq returns a function name.
#
# This dictionary connects that name to the actual Python
# function.
# ============================================================

available_functions = {

    "update_appointment": update_appointment,

    "check_doctor": check_doctor,

    "check_availability": check_availability,

    "book_appointment": book_appointment,

    "reset_appointment": reset_appointment
}


# ============================================================
# SYSTEM PROMPT
# ============================================================

system_message = """

You are an AI clinic appointment assistant.

Your job is to help users book appointments.

You have access to tools that can:

1. Store appointment information.
2. Check whether a doctor exists.
3. Check appointment availability.
4. Book an appointment.
5. Reset the current appointment.

IMPORTANT RULES:

- Never invent a doctor.
- Never invent availability.
- Never invent appointment details.
- If the user provides appointment information, use
  update_appointment to store it.
- If the user provides a doctor, use check_doctor to verify
  that doctor exists.
- If the doctor does not exist, tell the user and ask for
  another doctor.
- Once patient name, doctor, date, and time are available,
  use check_availability.
- Do not book automatically when a slot is available.
- After availability is confirmed, tell the user the slot
  is available and ask for confirmation.
- Only call book_appointment after the user clearly confirms.
- A confirmation can be "yes", "confirm", "book it",
  "yes please", or similar.
- If the user says no or cancel, do not book.
- If the slot is unavailable, tell the user and ask for
  another date or time.
- If the user wants another appointment after completing
  one, use reset_appointment.
- Be concise and polite.

Most importantly:

YOU decide when a tool is needed.

Do not pretend to have database information without using
the appropriate tool.
"""


# ============================================================
# EXECUTE TOOL CALL
# ============================================================
#
# This function is the bridge between:
#
#               GROQ
#                 ↓
#             TOOL CALL
#                 ↓
#              PYTHON
#                 ↓
#             DATABASE
#
# ============================================================

def execute_tool_call(tool_call):

    function_name = tool_call.function.name

    function_arguments = json.loads(
        tool_call.function.arguments
    )

    function_to_call = available_functions.get(
        function_name
    )

    if not function_to_call:

        return {
            "success": False,
            "message": (
                f"Unknown tool: {function_name}"
            )
        }

    try:

        result = function_to_call(
            **function_arguments
        )

        return result

    except Exception as e:

        return {
            "success": False,
            "message": str(e)
        }


# ============================================================
# RUN AGENT
# ============================================================
#
# THIS IS THE CORE OF STAGE 4.
#
# We keep asking Groq what to do next.
#
# If Groq wants a tool:
#
#     execute tool
#          ↓
#     send result to Groq
#
# If Groq does not want a tool:
#
#     return normal response
#
# ============================================================

def run_agent(messages):

    max_iterations = 10

    for _ in range(max_iterations):

        response = client.chat.completions.create(

            model=MODEL,

            messages=messages,

            tools=tools,

            tool_choice="auto",

            temperature=0
        )

        assistant_message = (
            response.choices[0].message
        )

        # ----------------------------------------------------
        # Add Groq's response to conversation history.
        # ----------------------------------------------------

        messages.append(
            assistant_message
        )

        # ----------------------------------------------------
        # Groq does not want a tool.
        #
        # Therefore this is the final response.
        # ----------------------------------------------------

        if not assistant_message.tool_calls:

            return assistant_message.content

        # ----------------------------------------------------
        # Groq requested one or more tools.
        # ----------------------------------------------------

        for tool_call in assistant_message.tool_calls:

            function_name = (
                tool_call.function.name
            )

            print(
                f"[Groq selected tool: {function_name}]"
            )

            # ------------------------------------------------
            # Python executes the requested function.
            # ------------------------------------------------

            tool_result = execute_tool_call(
                tool_call
            )

            # ------------------------------------------------
            # Send result back to Groq.
            # ------------------------------------------------

            messages.append(
                {
                    "role": "tool",

                    "tool_call_id": tool_call.id,

                    "name": function_name,

                    "content": json.dumps(
                        tool_result
                    )
                }
            )

        # ----------------------------------------------------
        # Loop again.
        #
        # Groq now sees the tool result and decides what
        # should happen next.
        # ----------------------------------------------------

    return (
        "Sorry, I could not complete the request."
    )


# ============================================================
# MAIN PROGRAM
# ============================================================

print(
    "Assistant: Hello! I can help you book a clinic appointment."
)

print(
    "Assistant: What would you like to do?"
)


# ============================================================
# CONVERSATION HISTORY
# ============================================================
#
# Unlike Stage 3, we now maintain the conversation history
# because Groq needs to remember:
#
# - what the user said
# - which tool it called
# - what the tool returned
# - what happened next
#
# ============================================================

messages = [

    {
        "role": "system",

        "content": system_message
    }

]


# ============================================================
# SESSION VARIABLES
# ============================================================

awaiting_confirmation = False

booking_completed = False


# ============================================================
# MAIN LOOP
# ============================================================

while True:

    user_input = input("You: ").strip()

    if not user_input:

        continue


    # ========================================================
    # EXIT
    # ========================================================

    if user_input.lower() in [
        "exit",
        "quit",
        "bye"
    ]:

        print(
            "Assistant: Goodbye!"
        )

        break


    # ========================================================
    # AFTER BOOKING
    # ========================================================

    if booking_completed:

        if user_input.lower() in [
            "ok",
            "okay",
            "thanks",
            "thank you",
            "great",
            "alright",
            "fine"
        ]:

            print(
                "Assistant: You're welcome! "
                "Let me know if you need anything else."
            )

            continue


        if user_input.lower() in [
            "book appointment",
            "book another appointment",
            "new appointment",
            "make another appointment",
            "another appointment"
        ]:

            booking_completed = False

            current_appointment = Appointment()

            messages.append(
                {
                    "role": "user",
                    "content": user_input
                }
            )

            response = run_agent(
                messages
            )

            print(
                "Assistant:",
                response
            )

            continue


        print(
            "Assistant: No problem! "
            "How can I help you?"
        )

        continue


    # ========================================================
    # ADD USER MESSAGE TO CONVERSATION
    # ========================================================

    messages.append(
        {
            "role": "user",
            "content": user_input
        }
    )


    # ========================================================
    # RUN GROQ AGENT
    # ========================================================

    try:

        assistant_response = run_agent(
            messages
        )

        print(
            "Assistant:",
            assistant_response
        )

    except Exception as e:

        print(
            "Assistant: Sorry, something went wrong."
        )

        print(
            f"Error: {e}"
        )