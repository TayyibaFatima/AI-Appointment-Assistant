from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import json
import re
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
        "awaiting_doctor_list_choice": False,
        "doctor_list_shown": False,
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
# LIST DOCTORS
# ============================================================

def get_doctors_list(specialty=None):
    conn = get_db_connection()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    d.id,
                    d.name,
                    d.specialization,
                    ds.day_of_week,
                    ds.start_time,
                    ds.end_time
                FROM public.doctors AS d
                LEFT JOIN public.doctor_schedules AS ds
                    ON ds.doctor_id = d.id
                ORDER BY d.name, ds.day_of_week, ds.start_time
            """)

            rows = cur.fetchall()

        doctors = {}

        for row in rows:
            doctor_id, name, specialization, day, start, end = row

            if doctor_id not in doctors:
                doctors[doctor_id] = {
                    "name": name,
                    "specialization": specialization or "Specialty not specified",
                    "schedule": []
                }

            if day is not None:
                days = [
                    "Monday", "Tuesday", "Wednesday",
                    "Thursday", "Friday", "Saturday", "Sunday"
                ]

                doctors[doctor_id]["schedule"].append(
                    f"{days[day]}: {start.strftime('%I:%M %p').lstrip('0')}"
                    f" – {end.strftime('%I:%M %p').lstrip('0')}"
                )

        specialty_aliases = {
            "general physician": ["general physician", "gp", "general medicine"],
            "cardiologist": ["cardiologist", "cardiology", "heart doctor"],
            "dermatologist": ["dermatologist", "dermatology", "skin doctor"],
        }

        requested = (specialty or "").strip().lower()
        aliases = specialty_aliases.get(requested, [requested]) if requested else []

        filtered_doctors = []

        for doctor in doctors.values():
            db_specialty = doctor["specialization"].lower()

            if aliases and not any(alias in db_specialty for alias in aliases):
                continue

            schedule_text = (
                "; ".join(doctor["schedule"])
                if doctor["schedule"]
                else "Working hours not configured"
            )

            filtered_doctors.append(
                f'{doctor["name"]} — {doctor["specialization"]}. '
                f'Working hours: {schedule_text}.'
            )

        if not filtered_doctors:
            return (
                f"No doctors found for {specialty}."
                if specialty
                else "No doctors are currently listed."
            )

        return (
            "Available doctors:\n"
            + "\n".join(f"- {doctor}" for doctor in filtered_doctors)
        )

    finally:
        conn.close()


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
    """Check clinic hours, doctor's schedule, and existing bookings."""

    appointment = session["appointment"]

    doctor_name = appointment.get("doctor")
    date_text = appointment.get("date")
    time_text = appointment.get("time")

    # All three details are required.
    if not doctor_name or not date_text or not time_text:
        return (
            "Please provide the doctor's name, appointment date, "
            "and preferred time before checking availability."
        )

    # Validate the appointment date.
    try:
        appointment_date = date.fromisoformat(date_text)
    except (ValueError, TypeError):
        session["availability_checked"] = False
        session["awaiting_confirmation"] = False
        return "Please provide a valid date in YYYY-MM-DD format."

    if appointment_date < date.today():
        session["availability_checked"] = False
        session["awaiting_confirmation"] = False
        return (
            "The appointment date cannot be in the past. "
            "Please choose another date."
        )

    # Normalize the requested time.
    normalized_time = normalize_time(time_text)

    if not normalized_time or normalized_time in (
        "Morning", "Afternoon", "Evening"
    ):
        session["availability_checked"] = False
        session["awaiting_confirmation"] = False
        return (
            "I couldn't understand the exact appointment time. "
            "Please provide a time such as 9 AM or 2:30 PM."
        )

    try:
        appointment_time = datetime.strptime(
            normalized_time, "%H:%M"
        ).time()
    except (ValueError, TypeError):
        session["availability_checked"] = False
        session["awaiting_confirmation"] = False
        return (
            "Please provide a valid appointment time, "
            "such as 9 AM or 2:30 PM."
        )

    # Check general clinic opening hours.
    clinic_open = dt_time(8, 0)
    clinic_close = dt_time(20, 0)

    if not (clinic_open <= appointment_time < clinic_close):
        session["availability_checked"] = False
        session["awaiting_confirmation"] = False
        return (
            "The clinic's appointment hours are 8:00 AM to 8:00 PM. "
            "Please choose a time within those hours."
        )

    # Find the doctor in the database.
    doctor_id = get_doctor_id(doctor_name)

    if not doctor_id:
        session["availability_checked"] = False
        session["awaiting_confirmation"] = False
        return (
            f"I couldn't find {doctor_name} in the clinic's doctor list. "
            "Please select a doctor from the available list."
        )

    # Python weekday: Monday = 0, Sunday = 6.
    weekday = appointment_date.weekday()

    conn = None

    try:
        conn = get_db_connection()

        with conn.cursor() as cur:

            # Retrieve this doctor's working hours for the requested day.
            cur.execute("""
                SELECT start_time, end_time
                FROM public.doctor_schedules
                WHERE doctor_id = %s
                  AND day_of_week = %s
                ORDER BY start_time
            """, (doctor_id, weekday))

            schedules = cur.fetchall()

            print(
                f"DEBUG availability: doctor={doctor_name}, "
                f"doctor_id={doctor_id}, date={appointment_date}, "
                f"weekday={weekday}, requested_time={appointment_time}, "
                f"schedules={schedules}"
            )

            # A time is valid when it is within any configured schedule.
            is_within_schedule = any(
                start_time <= appointment_time < end_time
                for start_time, end_time in schedules
            )

            if not is_within_schedule:
                session["availability_checked"] = False
                session["awaiting_confirmation"] = False

                if schedules:
                    hours = "; ".join(
                        f"{start.strftime('%I:%M %p').lstrip('0')}–"
                        f"{end.strftime('%I:%M %p').lstrip('0')}"
                        for start, end in schedules
                    )

                    return (
                        f"{doctor_name} is not scheduled to work at "
                        f"{appointment_time.strftime('%I:%M %p').lstrip('0')} "
                        f"on {appointment_date.strftime('%A, %B %d, %Y')}. "
                        f"Working hours that day: {hours}. "
                        "Please choose a time within those hours."
                    )

                return (
                    f"{doctor_name} does not have configured working hours "
                    f"on {appointment_date.strftime('%A')}. "
                    "Please choose another date or doctor."
                )

            # Check whether this exact slot is already booked.
            # appointment_time is stored as text in the current schema.
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM public.appointments
                    WHERE doctor_id = %s
                      AND appointment_date = %s
                      AND appointment_time::text IN (%s, %s)
                      AND status = 'booked'
                )
            """, (
                doctor_id,
                appointment_date,
                appointment_time.strftime("%H:%M:%S"),
                appointment_time.strftime("%H:%M")
            ))

            is_booked = cur.fetchone()[0]

            if is_booked:
                session["availability_checked"] = False
                session["awaiting_confirmation"] = False

                return (
                    f"Sorry, {doctor_name} already has an appointment at "
                    f"{appointment_time.strftime('%I:%M %p').lstrip('0')} "
                    f"on {appointment_date.strftime('%B %d, %Y')}. "
                    "Please choose another time."
                )

        # Schedule is valid and the exact slot is not booked.
        appointment["time"] = appointment_time.strftime("%H:%M:%S")

        session["availability_checked"] = True
        session["awaiting_confirmation"] = False

        return (
            f"Good news! {doctor_name} is scheduled to work, and the "
            f"{appointment_time.strftime('%I:%M %p').lstrip('0')} slot on "
            f"{appointment_date.strftime('%B %d, %Y')} is available. "
            "May I have your name to continue with the booking?"
        )

    except Exception as e:
        session["availability_checked"] = False
        session["awaiting_confirmation"] = False

        print(f"Availability check error: {e}")

        return (
            "I'm unable to check availability right now due to a database "
            "error. Please try again shortly."
        )

    finally:
        if conn is not None:
            conn.close()

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
        AND appointment_time::text IN (%s, %s)
        AND status = 'booked'
       """,
       (
        doctor_id,
        appointment_date,
        appointment_time,
        appointment_time[:5]
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
    session["awaiting_doctor_list_choice"] = False
    session["doctor_list_shown"] = False

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
            "name": "list_doctors",
            "description": (
                "List doctors from the clinic database. If the user requests a specialty "
                "such as cardiology or dermatology, pass that specialty to return only "
                "matching doctors. If no specialty is requested, list all doctors."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "specialty": {
                        "type": "string",
                        "description": "Requested specialty, if the user mentioned one; otherwise omit it."
                    }
                },
                "required": []
            }
        }
    },

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
You are an AI clinic appointment assistant. Keep the conversation natural, helpful, and concise. The Python appointment state and clinic database are authoritative. Never invent doctors, specialties, dates, times, working hours, or availability. Never expose raw tool output.
PRIORITY RULE — DOCTOR LIST REQUESTS:

Always handle explicit doctor-list requests before asking the user to select a doctor.

If the user asks to see all doctors, show all doctors, lists doctors, or asks which doctors the clinic has, call list_doctors without a specialty and display the returned list immediately.

If the user names a specialty, call list_doctors with that specialty and display the matching results immediately. Do not ask "Which [specialty] would you like to see?" before displaying the matching doctors.

After the list has been displayed, ask the user which doctor they prefer. Do not ask them to request the same list again.

If a single matching doctor is returned, tell the user that the clinic has that doctor and ask whether they would like to book with them.

If the user explicitly asks to see the list while also expressing appointment intent, display the requested list in the same turn. Do not replace that request with a generic question asking which doctor they want.
APPOINTMENT CONVERSATION FLOW:

1. UNDERSTAND THE USER'S INTENT
If the user wants to book an appointment but has not named a doctor or specialty, ask whether they would like to see the list of doctors or already have a specialty in mind. Do not force them to view the full list.

2. HANDLE SPECIALTY REQUESTS
If the user names a specialty, such as dermatologist, cardiologist, general physician, neurologist, pediatrician, or orthopedic surgeon, call list_doctors with the requested specialty.

Show only the matching doctors returned by the tool. Include each matching doctor's name, specialty, and working hours exactly as returned by the tool.

If no matching doctors are returned, explain that the current clinic database has no listed doctors for that specialty. Offer to show all doctors or try another specialty. Never invent a doctor to fill an empty result.

3. LIST ALL DOCTORS
If the user asks to see all doctors, agrees to view the list, or asks which doctors the clinic has, call list_doctors without a specialty.

Display each doctor's name, known specialty, and configured working hours. If the tool reports that working hours are not configured, clearly say that the hours have not been configured. Never assume that all doctors share the same schedule.

General clinic hours are 8:00 AM to 8:00 PM, but a doctor can only be booked during their configured working schedule. Clinic opening hours do not prove that a particular doctor works at a particular time.

4. LET THE USER CHOOSE A DOCTOR
After showing doctors for a specialty or listing all doctors, ask which doctor the user would like to see. Do not select a doctor on the user's behalf.

Once the user selects a doctor, ask for any missing preferred appointment date and time. The user may provide the doctor, date, and time together in one message.

Do not ask for information the user has already provided.

5. SAVE AND VALIDATE APPOINTMENT DETAILS
Use update_appointment to save appointment details explicitly provided by the user.

Use check_doctor to verify that the selected doctor exists in the clinic database.

Call check_availability only when the doctor, date, and time are all present and the doctor has been verified.

The check_availability tool determines whether the requested date and time fall within the doctor's configured working schedule and whether the requested appointment slot is already booked. Trust its result rather than guessing.

If the requested date or time falls outside the doctor's schedule, explain the result politely and ask the user to choose another date or time.

If the slot is already booked, explain that it is unavailable and ask whether the user would prefer another time or a different doctor.

If the user changes the doctor, date, or time after an availability check, update the appointment details and check availability again before proceeding.

Never claim that a slot is available unless check_availability has successfully confirmed it.

6. COLLECT THE PATIENT'S NAME
After availability is confirmed, ask for the patient's name if it is missing.

Save the name using update_appointment.

Providing a name is not booking confirmation. After receiving the patient's name, ask a separate, explicit confirmation question, such as: "Would you like me to confirm and book this appointment?"

7. REQUIRE EXPLICIT BOOKING CONFIRMATION
Call book_appointment only when all of the following conditions are met:
- The doctor has been verified.
- The patient name, doctor, date, and time are present.
- Availability was successfully checked for the current appointment details.
- The user has explicitly confirmed the booking in a separate conversation turn after being asked to confirm.

Examples of valid confirmations include "yes", "yes please", "book it", "confirm", and "go ahead", when the user is clearly responding to the booking confirmation question.

Do not treat a name, a preferred date, a preferred time, or a general expression of interest as booking confirmation.

If the user changes any appointment details after confirming, revalidate availability and obtain fresh explicit confirmation before booking the changed appointment.

8. CONFIRM SUCCESSFUL BOOKINGS
After calling book_appointment, report success only if the tool confirms that the booking succeeded.

Provide a concise plain-text confirmation containing:
- Patient name
- Doctor name
- Specialty, if available from the database
- Appointment date
- Appointment time

If booking fails, explain that the appointment could not be booked and follow the tool's result. Never claim success based on an attempted booking alone.

Do not promise SMS messages, emails, reminders, or other notifications unless those features are explicitly implemented and confirmed.

9. RESET AN APPOINTMENT
If the user asks to start over, cancel the current booking process, or reset their appointment details, use reset_appointment according to the tool's behavior.

After resetting, respond naturally and invite the user to begin again. Do not claim an existing database booking was cancelled unless the tool explicitly confirms that it was.

10. TOOL USE AND CONVERSATION STATE
Use the available tools for doctor lookup, appointment updates, availability checks, booking, and resetting. Do not fabricate tool results or expose raw tool output, internal state, database errors, or implementation details.

Respect the current appointment state and the tool results. Do not repeat successful operations unnecessarily. Do not skip required validation or booking confirmation.

If a tool fails or returns an unclear result, be transparent that the request could not be verified and ask the user to try again when appropriate.

RESPONSE STYLE:
- Be friendly, professional, concise, and natural.
- Ask one clear question at a time whenever possible.
- Present doctor lists in an easy-to-read format.
- Clearly distinguish a doctor's working hours from an available appointment slot.
- Never invent a schedule for a doctor whose working hours are missing.
- Never invent database records or assume that an unlisted doctor exists.
- Never claim an appointment has been booked unless book_appointment confirms success.
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

    if tool_name == "list_doctors":
        return get_doctors_list(
            specialty=arguments.get("specialty")
        )

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
    normalized_user_message = " ".join(user_message.lower().split())

    # --------------------------------------------------------
    # DOCTOR-LIST-FIRST BOOKING FLOW
    # --------------------------------------------------------

    yes_responses = {
        "yes", "yes please", "sure", "okay", "ok", "yep",
        "show me", "show the list", "please show me", "of course"
    }
    no_responses = {
        "no", "no thanks", "no thank you", "not now", "skip"
    }

    if session.get("awaiting_doctor_list_choice"):
        if normalized_user_message in yes_responses or any(
            phrase in normalized_user_message
            for phrase in ("show me the doctors", "show the doctors", "doctors list", "doctor list")
        ):
            result = get_doctors_list()
            session["awaiting_doctor_list_choice"] = False
            session["doctor_list_shown"] = True
            final_message = result["message"]

            session["messages"].append({"role": "user", "content": request.message})
            session["messages"].append({"role": "assistant", "content": final_message})

            return {
                "session_id": request.session_id,
                "response": final_message,
                "appointment": session["appointment"],
                "availability_checked": session["availability_checked"],
                "awaiting_confirmation": session["awaiting_confirmation"],
                "booking_completed": session["booking_completed"]
            }

        if normalized_user_message in no_responses:
            session["awaiting_doctor_list_choice"] = False
            final_message = "No problem. Tell me which doctor, date, and time you would like, and I'll check the slot."

            session["messages"].append({"role": "user", "content": request.message})
            session["messages"].append({"role": "assistant", "content": final_message})

            return {
                "session_id": request.session_id,
                "response": final_message,
                "appointment": session["appointment"],
                "availability_checked": session["availability_checked"],
                "awaiting_confirmation": session["awaiting_confirmation"],
                "booking_completed": session["booking_completed"]
            }

    booking_intent = bool(re.search(
        r"\\b(book|schedule|make|want|need)\\b", normalized_user_message
    )) and any(
        phrase in normalized_user_message
        for phrase in ("appointment", "doctor", "see a doctor", "visit")
    )

    appointment = session["appointment"]
    has_booking_details = bool(
        appointment["doctor"] or appointment["date"] or appointment["time"]
    )
    has_doctor_details_in_message = bool(
        re.search(r"\\bdr\\.?\\s+[a-z]+\\b", normalized_user_message)
    )

    if (
        booking_intent
        and not has_booking_details
        and not has_doctor_details_in_message
        and not session.get("doctor_list_shown")
    ):
        session["awaiting_doctor_list_choice"] = True
        final_message = "Sure! Would you like to see our doctors list with their general timings?"

        session["messages"].append({"role": "user", "content": request.message})
        session["messages"].append({"role": "assistant", "content": final_message})

        return {
            "session_id": request.session_id,
            "response": final_message,
            "appointment": session["appointment"],
            "availability_checked": session["availability_checked"],
            "awaiting_confirmation": session["awaiting_confirmation"],
            "booking_completed": session["booking_completed"]
        }

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
