from google import genai
from pydantic import BaseModel
from dotenv import load_dotenv
from datetime import date, timedelta
import os


# ============================================================
# LOAD API KEY
# ============================================================

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("GEMINI_API_KEY was not found in .env")
    exit()

client = genai.Client(api_key=api_key)


# ============================================================
# PYDANTIC MODEL
# ============================================================

class Appointment(BaseModel):
    patient_name: str | None = None
    doctor: str | None = None
    date: str | None = None
    time: str | None = None


# ============================================================
# EXISTING APPOINTMENTS
# ============================================================

booked_appointments = [
    {
        "patient_name": "Existing Patient",
        "doctor": "Dr. Ahmed",
        "date": "2026-09-11",
        "time": "04:00 PM"
    },
    {
        "patient_name": "Existing Patient",
        "doctor": "Dr. Sara",
        "date": "2026-09-11",
        "time": "05:00 PM"
    }
]


# ============================================================
# NORMALIZE DOCTOR
# ============================================================

def normalize_doctor(doctor):

    doctor = doctor.strip().lower()

    if doctor in ["dr sara", "dr. sara"]:
        return "Dr. Sara"

    if doctor in ["dr ahmed", "dr. ahmed"]:
        return "Dr. Ahmed"

    return doctor.title()


# ============================================================
# NORMALIZE TIME
# ============================================================

def normalize_time(time):

    time = time.strip().lower()

    if time == "morning":
        return "09:00 AM"

    if time in ["9 am", "9:00 am", "09:00 am"]:
        return "09:00 AM"

    if time == "afternoon":
        return "01:00 PM"

    if time in ["1 pm", "1:00 pm", "01:00 pm"]:
        return "01:00 PM"

    if time == "evening":
        return "05:00 PM"

    if time in ["5 pm", "5:00 pm", "05:00 pm"]:
        return "05:00 PM"

    return time.upper()


# ============================================================
# CHECK AVAILABILITY
# ============================================================

def check_availability(doctor, appointment_date, appointment_time):

    doctor = normalize_doctor(doctor)
    appointment_time = normalize_time(appointment_time)

    for appointment in booked_appointments:

        booked_doctor = normalize_doctor(appointment["doctor"])
        booked_time = normalize_time(appointment["time"])

        if (
            booked_doctor == doctor
            and appointment["date"] == appointment_date
            and booked_time == appointment_time
        ):
            return False

    return True


# ============================================================
# BOOK APPOINTMENT
# ============================================================

def book_appointment(appointment):

    if not check_availability(
        appointment.doctor,
        appointment.date,
        appointment.time
    ):
        return False

    booked_appointments.append(
        {
            "patient_name": appointment.patient_name,
            "doctor": normalize_doctor(appointment.doctor),
            "date": appointment.date,
            "time": normalize_time(appointment.time)
        }
    )

    return True


# ============================================================
# STRUCTURED OUTPUT INSTRUCTIONS
# ============================================================

today = date.today()
tomorrow = today + timedelta(days=1)

extraction_instruction = f"""
You extract appointment information from the user's message.

Today's date is {today.isoformat()}.
Tomorrow's date is {tomorrow.isoformat()}.

Extract ONLY information that the user actually provides.

The appointment has these fields:

- patient_name
- doctor
- date
- time

Rules:

1. If the user does not provide a field, return null.

2. Never invent missing information.

3. Convert "today" to {today.isoformat()}.

4. Convert "tomorrow" to {tomorrow.isoformat()}.

5. Convert "dr sara" or "dr. sara" to "Dr. Sara".

6. Convert "dr ahmed" or "dr. ahmed" to "Dr. Ahmed".

7. Convert:
   morning -> 09:00 AM
   afternoon -> 01:00 PM
   evening -> 05:00 PM

8. If the user provides a specific time, extract that time.

Return only the appointment information.
"""


# ============================================================
# EXTRACT APPOINTMENT INFORMATION
# ============================================================

def extract_appointment(user_message):

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=user_message,
        config={
            "system_instruction": extraction_instruction,
            "response_mime_type": "application/json",
            "response_schema": Appointment,
            "automatic_function_calling": {
                "disable": True
            }
        }
    )

    return Appointment.model_validate_json(response.text)


# ============================================================
# FIND MISSING INFORMATION
# ============================================================

def get_missing_field(appointment):

    if appointment.patient_name is None:
        return "patient_name"

    if appointment.doctor is None:
        return "doctor"

    if appointment.date is None:
        return "date"

    if appointment.time is None:
        return "time"

    return None


# ============================================================
# ASK FOR MISSING INFORMATION
# ============================================================

def ask_for_missing_field(field):

    if field == "patient_name":
        return "Sure! May I have your name?"

    if field == "doctor":
        return "Which doctor would you like to book with?"

    if field == "date":
        return "What date would you like for the appointment?"

    if field == "time":
        return "What time would you like?"


# ============================================================
# CURRENT APPOINTMENT
# ============================================================

current_appointment = Appointment()

awaiting_confirmation = False


# ============================================================
# MAIN PROGRAM
# ============================================================

print("AI Appointment Assistant")
print("Type 'exit' to stop.\n")


while True:

    user_input = input("You: ").strip()

    if user_input.lower() == "exit":
        print("Goodbye!")
        break


    # ========================================================
    # CONFIRMATION
    # ========================================================

    if awaiting_confirmation:

        if user_input.lower() in ["yes", "y", "confirm", "book it"]:

            success = book_appointment(current_appointment)

            if success:

                print("\nGemini: Your appointment has been successfully booked!")

                print("\nAppointment details:")
                print(
                    "Name:",
                    current_appointment.patient_name
                )
                print(
                    "Doctor:",
                    normalize_doctor(current_appointment.doctor)
                )
                print(
                    "Date:",
                    current_appointment.date
                )
                print(
                    "Time:",
                    normalize_time(current_appointment.time)
                )

            else:

                print(
                    "\nGemini: Sorry, that appointment slot is no longer available."
                )

            current_appointment = Appointment()
            awaiting_confirmation = False

        elif user_input.lower() in ["no", "n", "cancel"]:

            print(
                "\nGemini: Okay, I won't book the appointment."
            )

            current_appointment = Appointment()
            awaiting_confirmation = False

        else:

            print(
                "\nGemini: Please confirm with yes or no."
            )

        print()
        continue


    # ========================================================
    # EXTRACT INFORMATION FROM CURRENT USER MESSAGE
    # ========================================================

    extracted = extract_appointment(user_input)


    # ========================================================
    # UPDATE CURRENT APPOINTMENT
    # ========================================================

    if extracted.patient_name is not None:
        current_appointment.patient_name = extracted.patient_name

    if extracted.doctor is not None:
        current_appointment.doctor = extracted.doctor

    if extracted.date is not None:
        current_appointment.date = extracted.date

    if extracted.time is not None:
        current_appointment.time = extracted.time


    # ========================================================
    # CHECK FOR MISSING INFORMATION
    # ========================================================

    missing_field = get_missing_field(current_appointment)


    # ========================================================
    # ASK FOR NEXT MISSING FIELD
    # ========================================================

    if missing_field is not None:

        print(
            "\nGemini:",
            ask_for_missing_field(missing_field)
        )

        print()
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
            "\nGemini: Sorry, that appointment slot is not available."
        )

        print("Gemini: Please choose another time.")

        print()
        continue


    # ========================================================
    # ASK FOR CONFIRMATION
    # ========================================================

    print(
        "\nGemini: The appointment slot is available."
    )

    print("\nAppointment details:")

    print(
        "Name:",
        current_appointment.patient_name
    )

    print(
        "Doctor:",
        normalize_doctor(current_appointment.doctor)
    )

    print(
        "Date:",
        current_appointment.date
    )

    print(
        "Time:",
        normalize_time(current_appointment.time)
    )

    print(
        "\nGemini: Would you like me to book this appointment? (yes/no)"
    )

    awaiting_confirmation = True

    print()