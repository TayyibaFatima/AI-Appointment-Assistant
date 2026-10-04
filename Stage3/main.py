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
# This only fixes formatting.
#
# Dr Sara  -> Dr. Sara
# dr sara  -> Dr. Sara
# Dr Sarah -> Dr. Sarah
#
# It does NOT change Sarah into Sara.
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

    # Try YYYY-MM-DD first
    try:

        parsed_date = date.fromisoformat(date_text)

        return parsed_date.isoformat()

    except ValueError:

        pass

    # Remove commas
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
# Examples:
#
# 9 am       -> 09:00
# 09:00 am   -> 09:00
# 11 am      -> 11:00
# morning    -> Morning
#
# Invalid values return None.
# ============================================================

def normalize_time(time_text):

    if not time_text:
        return None

    time_text = time_text.strip().lower()

    # General time periods
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
# Clinic hours:
#
# 08:00 AM to 08:00 PM
#
# Morning/Afternoon/Evening are allowed because they are
# general time periods rather than exact times.
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
# CHECK IF DOCTOR EXISTS
# ============================================================

def doctor_exists(doctor_name):

    doctor_id = get_doctor_id(
        doctor_name
    )

    return doctor_id is not None


# ============================================================
# CHECK APPOINTMENT AVAILABILITY
# ============================================================

def check_availability(
    doctor_name,
    appointment_date,
    appointment_time
):

    doctor_id = get_doctor_id(
        doctor_name
    )

    if not doctor_id:

        return False

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

        return result is None

    finally:

        connection.close()


# ============================================================
# BOOK APPOINTMENT
# ============================================================

def book_appointment(appointment):

    doctor_id = get_doctor_id(
        appointment.doctor
    )

    if not doctor_id:

        return False, "Doctor not found."

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
                appointment.patient_name,
                doctor_id,
                appointment.date,
                appointment.time
            )
        )

        connection.commit()

        cursor.close()

        return True, "Appointment booked successfully."

    except errors.UniqueViolation:

        connection.rollback()

        return False, (
            "This appointment slot is already booked."
        )

    finally:

        connection.close()


# ============================================================
# EXTRACT APPOINTMENT INFORMATION USING GROQ
# ============================================================

def extract_appointment(user_message):

    extraction_instruction = """
Extract appointment information from the user's message.

Return ONLY this JSON object:

{
    "patient_name": null,
    "doctor": null,
    "date": null,
    "time": null
}

Rules:

- Put a value only when it is explicitly mentioned.
- Otherwise use null.
- Never invent values.
- Do not change names.
- If the user says Dr Sarah, return Dr Sarah.
- If the user says Dr Sara, return Dr Sara.
- If the user says 11 am, return 11 am.
- If the user says 11 qam, return 11 qam.
"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "system",
                "content": extraction_instruction
            },
            {
                "role": "user",
                "content": user_message
            }
        ],
        response_format={
            "type": "json_object"
        },
        temperature=0,
        max_tokens=500
    )

    content = response.choices[0].message.content

    data = json.loads(content)

    return Appointment(
        patient_name=data.get("patient_name"),
        doctor=data.get("doctor"),
        date=data.get("date"),
        time=data.get("time")
    )


# ============================================================
# GET MISSING INFORMATION
# ============================================================

def get_missing_information(appointment):

    if not appointment.patient_name:

        return "patient_name"

    if not appointment.doctor:

        return "doctor"

    if not appointment.date:

        return "date"

    if not appointment.time:

        return "time"

    return None


# ============================================================
# ASK FOR NEXT INFORMATION
# ============================================================

def ask_for_next_information(missing):

    if missing == "patient_name":

        return (
            "Sure! What is your name?"
        )

    if missing == "doctor":

        return (
            "Which doctor would you like to book with?"
        )

    if missing == "date":

        return (
            "What date would you like for the appointment?\n"
            "Please use YYYY-MM-DD format "
            "(for example, 2026-09-15)."
        )

    if missing == "time":

        return (
            "What time would you like for the appointment?\n"
            "For example, 09:00 AM."
        )

    return None


# ============================================================
# MAIN PROGRAM
# ============================================================

print(
    "Assistant: Hello! I can help you book a clinic appointment."
)


# ============================================================
# SESSION VARIABLES
# ============================================================

current_appointment = Appointment()

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
    # Once a booking has been completed, normal messages such
    # as "ok", "thanks", etc. should NOT start a new booking.
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
                "Assistant: You're welcome! Let me know if you have any other queries."
            )

            continue


        # ----------------------------------------------------
        # USER WANTS ANOTHER APPOINTMENT
        # ----------------------------------------------------

        if user_input.lower() in [
            "book appointment",
            "book another appointment",
            "new appointment",
            "make another appointment",
            "another appointment"
        ]:

            booking_completed = False

            current_appointment = Appointment()

            print(
                "Assistant: Sure! What is your name?"
            )

            continue


        # ----------------------------------------------------
        # OTHER MESSAGE AFTER BOOKING
        # ----------------------------------------------------

        print(
            "Assistant: No problem! "
            "How can I help you?"
        )

        continue


    # ========================================================
    # CONFIRMATION
    # ========================================================

    if awaiting_confirmation:

        answer = user_input.lower()


        # ----------------------------------------------------
        # USER CONFIRMS
        # ----------------------------------------------------

        if answer in [
            "yes",
            "y",
            "confirm"
        ]:

            success, message = book_appointment(
                current_appointment
            )

            if success:

                print(
                    "Assistant: Your appointment has been "
                    "booked successfully!\n"
                    f"Patient: {current_appointment.patient_name}\n"
                    f"Doctor: {current_appointment.doctor}\n"
                    f"Date: {current_appointment.date}\n"
                    f"Time: {current_appointment.time}"
                )

            

                current_appointment = Appointment()

                awaiting_confirmation = False

                booking_completed = True
                continue

            else:

                print(
                    f"Assistant: {message}"
                )

                if "already booked" in message.lower():

                    current_appointment.date = None

                    current_appointment.time = None

                    awaiting_confirmation = False

            continue


        # ----------------------------------------------------
        # USER CANCELS
        # ----------------------------------------------------

        elif answer in [
            "no",
            "n",
            "cancel"
        ]:

            print(
                "Assistant: Okay, I cancelled the booking."
            )

            current_appointment = Appointment()

            awaiting_confirmation = False

            continue


        # ----------------------------------------------------
        # INVALID CONFIRMATION
        # ----------------------------------------------------

        else:

            print(
                "Assistant: Please answer yes or no."
            )

            continue


    # ========================================================
    # EXTRACT INFORMATION
    # ========================================================

    try:

        extracted = extract_appointment(
            user_input
        )

    except Exception as e:

        print(
            "Assistant: Sorry, I couldn't understand that."
        )

        print(
            f"Error: {e}"
        )

        continue


    # ========================================================
    # DOCTOR CHECK
    # ========================================================
    # IMPORTANT:
    # Doctor is checked immediately after the user enters it.
    #
    # We do NOT wait for date or time.
    # ========================================================

    if extracted.doctor:

        normalized_doctor = normalize_doctor(
            extracted.doctor
        )


        # ----------------------------------------------------
        # CHECK DATABASE IMMEDIATELY
        # ----------------------------------------------------

        if not doctor_exists(
            normalized_doctor
        ):

            print(
                f"Assistant: Sorry, I couldn't find "
                f"{normalized_doctor} in our clinic.\n"
                "Please choose another doctor."
            )

            # Keep patient name.
            # Do not save invalid doctor.
            current_appointment.doctor = None

            continue


        # ----------------------------------------------------
        # DOCTOR EXISTS
        # ----------------------------------------------------

        current_appointment.doctor = (
            normalized_doctor
        )


    # ========================================================
    # SAVE PATIENT NAME
    # ========================================================

    if extracted.patient_name:

        current_appointment.patient_name = (
            extracted.patient_name
        )


    # ========================================================
    # DATE
    # ========================================================

    if extracted.date:

        normalized_date = normalize_date(
            extracted.date
        )


        if not normalized_date:

            print(
                "Assistant: Please enter the date in "
                "YYYY-MM-DD format "
                "(for example, 2026-09-15)."
            )

            current_appointment.date = None

            continue


        current_appointment.date = (
            normalized_date
        )


    # ========================================================
    # CHECK DATE IS NOT IN THE PAST
    # ========================================================

    if current_appointment.date:

        try:

            appointment_date = date.fromisoformat(
                current_appointment.date
            )

            if appointment_date < date.today():

                print(
                    "Assistant: The appointment date "
                    "cannot be in the past."
                )

                current_appointment.date = None

                continue

        except ValueError:

            print(
                "Assistant: Please enter the date in "
                "YYYY-MM-DD format "
                "(for example, 2026-09-15)."
            )

            current_appointment.date = None

            continue


    # ========================================================
    # TIME
    # ========================================================

    if extracted.time:

        normalized_time = normalize_time(
            extracted.time
        )


        if not normalized_time:

            print(
                "Assistant: Please enter a valid time.\n"
                "For example, 09:00 AM."
            )

            current_appointment.time = None

            continue


        # ----------------------------------------------------
        # CHECK CLINIC HOURS
        # ----------------------------------------------------

        if not valid_clinic_time(
            normalized_time
        ):

            print(
                "Assistant: Please choose a time between "
                "08:00 AM and 08:00 PM."
            )

            current_appointment.time = None

            continue


        current_appointment.time = (
            normalized_time
        )


    # ========================================================
    # ASK FOR MISSING INFORMATION
    # ========================================================

    missing = get_missing_information(
        current_appointment
    )


    if missing:

        question = ask_for_next_information(
            missing
        )

        print(
            f"Assistant: {question}"
        )

        continue


    # ========================================================
    # CHECK AVAILABILITY
    # ========================================================

    available = check_availability(
        current_appointment.doctor,
        current_appointment.date,
        current_appointment.time
    )


    # ========================================================
    # SLOT NOT AVAILABLE
    # ========================================================

    if not available:

        print(
            f"Assistant: Sorry, "
            f"{current_appointment.doctor} is already booked "
            f"on {current_appointment.date} during "
            f"{current_appointment.time}.\n"
            "Please choose another date or time."
        )

        current_appointment.date = None

        current_appointment.time = None

        continue


    # ========================================================
    # SHOW APPOINTMENT DETAILS
    # ========================================================

    print(
        "Assistant: I found an available slot.\n"
        f"Patient: {current_appointment.patient_name}\n"
        f"Doctor: {current_appointment.doctor}\n"
        f"Date: {current_appointment.date}\n"
        f"Time: {current_appointment.time}\n"
        "Would you like me to book this appointment?"
    )


    # ========================================================
    # WAIT FOR CONFIRMATION
    # ========================================================

    awaiting_confirmation = True