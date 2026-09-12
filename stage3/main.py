import os
import json
from datetime import date

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
    raise ValueError("GROQ_API_KEY is missing from .env file")


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

def normalize_doctor(doctor):

    if not doctor:
        return None

    doctor = doctor.strip().lower()

    if doctor in ["sara", "dr sara", "dr. sara"]:
        return "Dr. Sara"

    if doctor in ["ahmed", "dr ahmed", "dr. ahmed"]:
        return "Dr. Ahmed"

    return doctor.title()


# ============================================================
# NORMALIZE TIME
# ============================================================

def normalize_time(time):

    if not time:
        return None

    time = time.strip().lower()

    if time in ["morning", "in the morning"]:
        return "Morning"

    if time in ["afternoon", "in the afternoon"]:
        return "Afternoon"

    if time in ["evening", "in the evening"]:
        return "Evening"

    return time


# ============================================================
# GET DOCTOR ID
# ============================================================

def get_doctor_id(doctor_name):

    doctor_name = normalize_doctor(doctor_name)

    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT id
        FROM doctors
        WHERE name = %s
        """,
        (doctor_name,)
    )

    result = cursor.fetchone()

    cursor.close()
    connection.close()

    if result:
        return result[0]

    return None


# ============================================================
# CHECK APPOINTMENT AVAILABILITY
# ============================================================

def check_availability(doctor, appointment_date, appointment_time):

    doctor = normalize_doctor(doctor)
    appointment_time = normalize_time(appointment_time)

    doctor_id = get_doctor_id(doctor)

    if doctor_id is None:
        return False

    connection = get_db_connection()
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
    connection.close()

    if result:
        return False

    return True


# ============================================================
# BOOK APPOINTMENT
# ============================================================

def book_appointment(appointment):

    doctor = normalize_doctor(appointment.doctor)
    appointment_time = normalize_time(appointment.time)

    doctor_id = get_doctor_id(doctor)

    if doctor_id is None:
        return False, "Doctor not found."

    connection = get_db_connection()
    cursor = connection.cursor()

    try:

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
                appointment_time
            )
        )

        connection.commit()

        cursor.close()
        connection.close()

        return True, "Appointment booked successfully."

    except errors.UniqueViolation:

        connection.rollback()

        cursor.close()
        connection.close()

        return False, "This appointment slot is already booked."

    except Exception as e:

        connection.rollback()

        cursor.close()
        connection.close()

        return False, f"Database error: {e}"


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

Put a value only when it is explicitly mentioned.
Otherwise use null.
Never invent values.
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

        # 500 gives the model enough room to finish valid JSON
        # while staying below the 1000-token limit we encountered.
        max_tokens=500
    )


    response_text = response.choices[0].message.content

    data = json.loads(response_text)

    appointment = Appointment.model_validate(data)

    return appointment


# ============================================================
# MERGE NEW INFORMATION WITH CURRENT APPOINTMENT
# ============================================================

def merge_appointment(current, new):

    if new.patient_name:
        current.patient_name = new.patient_name

    if new.doctor:
        current.doctor = normalize_doctor(new.doctor)

    if new.date:
        current.date = new.date

    if new.time:
        current.time = normalize_time(new.time)

    return current


# ============================================================
# GET MISSING INFORMATION
# ============================================================

def get_missing_information(appointment):

    missing = []

    if not appointment.patient_name:
        missing.append("patient name")

    if not appointment.doctor:
        missing.append("doctor")

    if not appointment.date:
        missing.append("date")

    if not appointment.time:
        missing.append("time")

    return missing


# ============================================================
# ASK FOR NEXT MISSING INFORMATION
# ============================================================

def ask_for_next_information(appointment):

    missing = get_missing_information(appointment)

    if not missing:
        return

    first_missing = missing[0]

    if first_missing == "patient name":

        print("\nAssistant: Sure! What is your name?")

    elif first_missing == "doctor":

        print("\nAssistant: Which doctor would you like to book with?")

    elif first_missing == "date":

        print("\nAssistant: What date would you like for the appointment?")

    elif first_missing == "time":

        print("\nAssistant: What time would you like for the appointment?")


# ============================================================
# MAIN PROGRAM
# ============================================================

print("==================================================")
print("        AI APPOINTMENT ASSISTANT - STAGE 3")
print("        Groq + PostgreSQL")
print("==================================================")

print("\nAssistant: Hello! I can help you book an appointment.")
print("Assistant: You can type 'exit' anytime to leave.\n")


# ============================================================
# SESSION STATE
# ============================================================

current_appointment = Appointment()

awaiting_confirmation = False


# ============================================================
# CHAT LOOP
# ============================================================

while True:

    user_input = input("You: ").strip()

    if not user_input:
        continue


    # ========================================================
    # EXIT
    # ========================================================

    if user_input.lower() in ["exit", "quit", "bye"]:

        print("\nAssistant: Goodbye!")

        break


    # ========================================================
    # HANDLE CONFIRMATION
    # ========================================================

    if awaiting_confirmation:

        if user_input.lower() in [
            "yes",
            "y",
            "confirm",
            "okay",
            "ok"
        ]:

            success, message = book_appointment(
                current_appointment
            )

            if success:

                print(
                    "\nAssistant: Your appointment has been "
                    "booked successfully!"
                )

                print(
                    f"Assistant: Patient: "
                    f"{current_appointment.patient_name}"
                )

                print(
                    f"Assistant: Doctor: "
                    f"{current_appointment.doctor}"
                )

                print(
                    f"Assistant: Date: "
                    f"{current_appointment.date}"
                )

                print(
                    f"Assistant: Time: "
                    f"{current_appointment.time}"
                )

                current_appointment = Appointment()

                awaiting_confirmation = False

            else:

                print(
                    f"\nAssistant: {message}"
                )

                current_appointment = Appointment()

                awaiting_confirmation = False

            continue


        elif user_input.lower() in [
            "no",
            "n",
            "cancel"
        ]:

            print(
                "\nAssistant: Okay, I cancelled "
                "the appointment request."
            )

            current_appointment = Appointment()

            awaiting_confirmation = False

            continue


        else:

            print(
                "\nAssistant: Please reply with yes or no."
            )

            continue


    # ========================================================
    # EXTRACT INFORMATION
    # ========================================================

    try:

        extracted = extract_appointment(user_input)

    except Exception as e:

        print(
            "\nAssistant: Sorry, I couldn't understand that."
        )

        print(
            f"Assistant: Error: {e}"
        )

        continue


    # ========================================================
    # MERGE INFORMATION INTO SESSION
    # ========================================================

    current_appointment = merge_appointment(
        current_appointment,
        extracted
    )


    # ========================================================
    # ASK FOR NEXT MISSING FIELD
    # ========================================================

    missing = get_missing_information(
        current_appointment
    )

    if missing:

        ask_for_next_information(
            current_appointment
        )

        continue


    # ========================================================
    # CHECK DOCTOR
    # ========================================================

    doctor_id = get_doctor_id(
        current_appointment.doctor
    )

    if doctor_id is None:

        print(
            f"\nAssistant: Sorry, I couldn't find "
            f"{current_appointment.doctor} in our clinic."
        )

        print(
            "Assistant: Please choose another doctor."
        )

        current_appointment.doctor = None

        continue


    # ========================================================
    # CHECK DATE FORMAT
    # ========================================================

    try:

        appointment_date = date.fromisoformat(
            current_appointment.date
        )

    except ValueError:

        print(
            "\nAssistant: Please provide the date "
            "in YYYY-MM-DD format."
        )

        current_appointment.date = None

        continue


    # ========================================================
    # CHECK PAST DATE
    # ========================================================

    if appointment_date < date.today():

        print(
            "\nAssistant: That date has already passed."
        )

        print(
            "Assistant: Please provide a future date."
        )

        current_appointment.date = None

        continue


    # ========================================================
    # CHECK AVAILABILITY
    # ========================================================

    available = check_availability(
        current_appointment.doctor,
        current_appointment.date,
        current_appointment.time
    )


    if not available:

        print(
            f"\nAssistant: Sorry, "
            f"{current_appointment.doctor} is already booked "
            f"on {current_appointment.date} "
            f"during {current_appointment.time}."
        )

        print(
            "Assistant: Please choose another date or time."
        )

        current_appointment.date = None
        current_appointment.time = None

        continue


    # ========================================================
    # SHOW APPOINTMENT DETAILS
    # ========================================================

    print(
        "\nAssistant: I found an available slot."
    )

    print(
        f"Assistant: Patient: "
        f"{current_appointment.patient_name}"
    )

    print(
        f"Assistant: Doctor: "
        f"{current_appointment.doctor}"
    )

    print(
        f"Assistant: Date: "
        f"{current_appointment.date}"
    )

    print(
        f"Assistant: Time: "
        f"{current_appointment.time}"
    )


    # ========================================================
    # ASK FOR CONFIRMATION
    # ========================================================

    print(
        "\nAssistant: Would you like me to "
        "book this appointment?"
    )

    awaiting_confirmation = True