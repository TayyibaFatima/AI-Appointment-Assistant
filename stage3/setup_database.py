import os
import psycopg2
from dotenv import load_dotenv


# ============================================================
# LOAD DATABASE SETTINGS
# ============================================================

load_dotenv()

connection = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST"),
    port=os.getenv("POSTGRES_PORT"),
    database=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD")
)

cursor = connection.cursor()


# ============================================================
# CREATE DOCTORS TABLE
# ============================================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS doctors (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL UNIQUE,
        specialization VARCHAR(100)
    )
""")


# ============================================================
# CREATE APPOINTMENTS TABLE
# ============================================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id SERIAL PRIMARY KEY,
        patient_name VARCHAR(100) NOT NULL,
        doctor_id INTEGER NOT NULL REFERENCES doctors(id),
        appointment_date DATE NOT NULL,
        appointment_time VARCHAR(20) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'booked',

        UNIQUE (
            doctor_id,
            appointment_date,
            appointment_time
        )
    )
""")


# ============================================================
# ADD DOCTORS
# ============================================================

cursor.execute("""
    INSERT INTO doctors (name, specialization)
    VALUES
        ('Dr. Sara', 'General Physician'),
        ('Dr. Ahmed', 'Cardiologist')
    ON CONFLICT (name) DO NOTHING
""")


# ============================================================
# SAVE CHANGES
# ============================================================

connection.commit()

cursor.close()
connection.close()

print("Database setup successful!")
print("Doctors table created.")
print("Appointments table created.")
print("Doctors added.")