from google import genai
from pydantic import BaseModel
import json
from dotenv import load_dotenv
import os


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================
# Loads the variables stored in the .env file.
#
# Our .env file contains:
#
# GEMINI_API_KEY=your_api_key
#
# This keeps the API key outside the Python code.
# ============================================================

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")


# ============================================================
# GEMINI CLIENT
# ============================================================
# Creates the Gemini API client using our API key.
# ============================================================

client = genai.Client(api_key=api_key)


# ============================================================
# PYDANTIC MODEL
# ============================================================
# This model defines the structure of appointment information.
#
# Pydantic allows us to define exactly what information
# an appointment should contain.
#
# We are learning structured data here.
# ============================================================

class Appointment(BaseModel):

    intent: str
    patient_name: str
    doctor: str
    date: str
    time: str


# ============================================================
# SYSTEM INSTRUCTION
# ============================================================
# This tells Gemini what role it has and how it should behave.
#
# Gemini is our AI assistant.
#
# Python functions are our tools.
#
# Gemini decides WHEN a tool is needed.
#
# Python actually EXECUTES the tool.
# ============================================================

system_instruction = """

You are an AI appointment assistant for a clinic.

Your job is to:

- Help users book appointments.
- Provide information about doctors.
- Ask for missing appointment information.
- Check appointment availability before booking.
- Ask the user for confirmation before booking an available appointment.
- Book the appointment only after the user confirms.
- Be polite and concise.
- Never make up doctor information.
- Never claim an appointment is booked unless the book_appointment
  tool confirms that it was booked.

For an appointment, collect:

- Patient name
- Doctor
- Date
- Time

When the user provides enough information to check availability,
use the check_availability tool.

If the requested slot is available, tell the user that the slot
is available and ask whether they want to book it.

Do NOT automatically book an available appointment.

Only use the book_appointment tool after the user clearly confirms
that they want to book the appointment.

If the slot is unavailable, tell the user that it is unavailable
and do not call book_appointment.

"""


# ============================================================
# BOOKED APPOINTMENTS
# ============================================================
# For Stage 1, we are keeping appointment data in a Python list.
#
# This is NOT permanent storage.
#
# It only exists while the program is running.
#
# Later we will replace this with a real database or other
# persistent storage.
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
# NORMALIZE DOCTOR NAME
# ============================================================
# Users can write a doctor's name in different ways.
#
# For example:
#
# Dr Sara
# Dr. Sara
# dr sara
#
# We convert them into one standard form.
# ============================================================

def normalize_doctor(doctor):

    doctor = doctor.strip()

    if doctor.lower() == "dr sara":
        return "Dr. Sara"

    if doctor.lower() == "dr. sara":
        return "Dr. Sara"

    if doctor.lower() == "dr ahmed":
        return "Dr. Ahmed"

    if doctor.lower() == "dr. ahmed":
        return "Dr. Ahmed"

    return doctor


# ============================================================
# NORMALIZE TIME
# ============================================================
# Users can describe the same time in different ways.
#
# Example:
#
# morning
# 9 AM
# 09:00 AM
# 9:00 am
#
# We convert common forms into one standard format.
# ============================================================

def normalize_time(time):

    time = time.strip().lower()

    if time == "morning":
        return "09:00 AM"

    if time == "9 am":
        return "09:00 AM"

    if time == "9:00 am":
        return "09:00 AM"

    if time == "09:00 am":
        return "09:00 AM"

    if time == "09:00 AM".lower():
        return "09:00 AM"

    if time == "afternoon":
        return "01:00 PM"

    if time == "1 pm":
        return "01:00 PM"

    if time == "1:00 pm":
        return "01:00 PM"

    if time == "evening":
        return "05:00 PM"

    if time == "5 pm":
        return "05:00 PM"

    if time == "5:00 pm":
        return "05:00 PM"

    return time.upper()


# ============================================================
# CHECK AVAILABILITY TOOL
# ============================================================
# This function checks whether a doctor already has an
# appointment at the requested date and time.
#
# IMPORTANT:
#
# This function DOES NOT book the appointment.
#
# It only checks availability.
#
# This separation is important because we want:
#
# CHECK
#   ↓
# CONFIRM
#   ↓
# BOOK
# ============================================================

def check_availability(doctor, date, time):

    doctor = normalize_doctor(doctor)
    time = normalize_time(time)

    # Check every existing appointment.
    for appointment in booked_appointments:

        booked_doctor = normalize_doctor(
            appointment["doctor"]
        )

        booked_time = normalize_time(
            appointment["time"]
        )

        # Compare doctor + date + time.
        if (
            booked_doctor == doctor
            and appointment["date"] == date
            and booked_time == time
        ):

            return {
                "available": False,
                "message": "The requested appointment slot is NOT available."
            }

    # If no matching appointment was found,
    # the slot is available.
    return {
        "available": True,
        "message": "The requested appointment slot is available."
    }


# ============================================================
# BOOK APPOINTMENT TOOL
# ============================================================
# This function actually creates the appointment.
#
# IMPORTANT:
#
# This function should ONLY be called after the user confirms.
#
# It checks availability one more time before booking.
#
# Why?
#
# Because we should never blindly add an appointment.
# ============================================================

def book_appointment(patient_name, doctor, date, time):

    doctor = normalize_doctor(doctor)
    time = normalize_time(time)

    # Check whether the slot is still available.
    availability = check_availability(
        doctor,
        date,
        time
    )

    # If someone already booked it,
    # do not create another appointment.
    if not availability["available"]:

        return {
            "booked": False,
            "message": "The appointment could not be booked because the slot is no longer available."
        }

    # Create the new appointment.
    new_appointment = {
        "patient_name": patient_name,
        "doctor": doctor,
        "date": date,
        "time": time
    }

    # Add it to our appointment list.
    booked_appointments.append(
        new_appointment
    )

    # Return a successful result.
    return {
        "booked": True,
        "message": "The appointment has been successfully booked.",
        "appointment": new_appointment
    }


# ============================================================
# AVAILABILITY TOOL DEFINITION
# ============================================================
# This describes check_availability to Gemini.
#
# Gemini sees this description and can decide when it needs
# to call this tool.
#
# Gemini does NOT execute this function.
#
# Gemini only requests the function.
#
# Python executes the actual function.
# ============================================================

availability_tool = {

    "type": "function",

    "name": "check_availability",

    "description":
        "Check whether a doctor's appointment slot is available.",

    "parameters": {

        "type": "object",

        "properties": {

            "doctor": {
                "type": "string",
                "description": "Doctor's name"
            },

            "date": {
                "type": "string",
                "description":
                    "Appointment date in YYYY-MM-DD format"
            },

            "time": {
                "type": "string",
                "description":
                    "Appointment time"
            }
        },

        "required": [
            "doctor",
            "date",
            "time"
        ]
    }
}


# ============================================================
# BOOKING TOOL DEFINITION
# ============================================================
# This describes book_appointment to Gemini.
#
# Gemini can call this tool ONLY after the user confirms.
#
# The actual Python function will then create the appointment.
# ============================================================

booking_tool = {

    "type": "function",

    "name": "book_appointment",

    "description":
        "Book an appointment after the patient has confirmed that they want to book the available slot.",

    "parameters": {

        "type": "object",

        "properties": {

            "patient_name": {
                "type": "string",
                "description":
                    "Full name of the patient"
            },

            "doctor": {
                "type": "string",
                "description":
                    "Doctor's name"
            },

            "date": {
                "type": "string",
                "description":
                    "Appointment date in YYYY-MM-DD format"
            },

            "time": {
                "type": "string",
                "description":
                    "Appointment time"
            }
        },

        "required": [
            "patient_name",
            "doctor",
            "date",
            "time"
        ]
    }
}


# ============================================================
# ALL TOOLS
# ============================================================
# Gemini receives both tools.
#
# It can choose:
#
# check_availability
#
# OR
#
# book_appointment
# ============================================================

tools = [
    availability_tool,
    booking_tool
]


# ============================================================
# CONVERSATION HISTORY
# ============================================================
# Stores the previous interaction ID.
#
# This allows Gemini to remember the conversation while the
# program is running.
#
# For example:
#
# User gives name
#       ↓
# User gives doctor
#       ↓
# User gives date
#       ↓
# User confirms
#
# Gemini can understand that these messages belong to the
# same appointment conversation.
# ============================================================

previous_interaction_id = None


# ============================================================
# MAIN CHAT LOOP
# ============================================================
# This continuously asks the user for messages.
# ============================================================

while True:

    user_input = input("You: ")

    # ========================================================
    # EXIT
    # ========================================================
    # Stop the program if the user types exit.
    # ========================================================

    if user_input.lower() == "exit":
        break


    # ========================================================
    # FIRST GEMINI INTERACTION
    # ========================================================
    # If there is no previous interaction,
    # create a new conversation.
    # ========================================================

    if previous_interaction_id is None:

        interaction = client.interactions.create(

            model="gemini-3.6-flash",

            input=user_input,

            system_instruction=system_instruction,

            tools=tools
        )


    # ========================================================
    # FOLLOW-UP GEMINI INTERACTION
    # ========================================================
    # If a previous interaction exists,
    # continue the same conversation.
    # ========================================================

    else:

        interaction = client.interactions.create(

            model="gemini-3.6-flash",

            input=user_input,

            previous_interaction_id=previous_interaction_id,

            system_instruction=system_instruction,

            tools=tools
        )


    # ========================================================
    # CHECK WHETHER GEMINI CALLED A TOOL
    # ========================================================

    tool_called = False


    # Gemini can return multiple steps.
    #
    # We inspect each step to see if one of them is a
    # function call.

    for step in interaction.steps:

        if step.type == "function_call":

            tool_called = True


            # =================================================
            # DISPLAY TOOL INFORMATION
            # =================================================

            print(
                "\nTool called:",
                step.name
            )

            print(
                "Arguments:",
                step.arguments
            )


            # =================================================
            # CHECK AVAILABILITY
            # =================================================

            if step.name == "check_availability":

                result = check_availability(

                    step.arguments["doctor"],

                    step.arguments["date"],

                    step.arguments["time"]
                )


            # =================================================
            # BOOK APPOINTMENT
            # =================================================

            elif step.name == "book_appointment":

                result = book_appointment(

                    step.arguments["patient_name"],

                    step.arguments["doctor"],

                    step.arguments["date"],

                    step.arguments["time"]
                )


            # =================================================
            # DISPLAY TOOL RESULT
            # =================================================

            print(
                "Tool result:",
                result
            )


            # =================================================
            # SEND TOOL RESULT BACK TO GEMINI
            # =================================================
            # Gemini needs to see the result of the Python
            # function before it can produce its final answer.
            # =================================================

            final_interaction = client.interactions.create(

                model="gemini-3.6-flash",

                previous_interaction_id=interaction.id,

                input=[

                    {

                        "type": "function_result",

                        "name": step.name,

                        "call_id": step.id,

                        "result": [

                            {

                                "type": "text",

                                "text": json.dumps(result)
                            }
                        ]
                    }
                ],

                tools=tools
            )


            # =================================================
            # DISPLAY GEMINI'S FINAL RESPONSE
            # =================================================

            print(
                "\nGemini:",
                final_interaction.output_text
            )


            # =================================================
            # SAVE INTERACTION ID
            # =================================================
            # The next user message will continue from here.
            # =================================================

            previous_interaction_id = final_interaction.id


            # Stop checking steps after handling the tool.
            break


    # ========================================================
    # NO TOOL WAS CALLED
    # ========================================================
    # If Gemini did not need a tool, simply display its
    # response.
    #
    # Example:
    #
    # User: What doctors do you have?
    #
    # Or:
    #
    # User: I want to book an appointment.
    #
    # Gemini may need to ask for missing information first.
    # ========================================================

    if not tool_called:

        print(
            "\nGemini:",
            interaction.output_text
        )

        previous_interaction_id = interaction.id


    print()