# AI Appointment Assistant

An AI-powered clinic appointment assistant that combines **LLM tool calling, structured data, PostgreSQL, session-based state management, and FastAPI** to handle multi-turn appointment booking.

The project was developed progressively through seven stages, moving from a basic LLM application to a **tool-using AI agent connected to a persistent database and backend API**.

---

## Overview

The assistant can:

* Collect patient information
* Identify and verify doctors
* Check appointment availability
* Maintain appointment information across multiple messages
* Ask for booking confirmation
* Book appointments through a database-backed tool
* Store confirmed appointments in PostgreSQL
* Maintain separate appointment state for different sessions
* Expose the AI assistant through a FastAPI REST API

The project focuses on understanding how an AI application moves beyond:

```text
User → LLM → Response
```

into a system where the LLM can make decisions, request tools, receive tool results, and interact with real application state and databases:

```text
User
 ↓
FastAPI
 ↓
Session State
 ↓
LLM
 ↓
Tool Selection
 ↓
Python Tool Execution
 ↓
PostgreSQL / Application State
 ↓
Tool Result
 ↓
LLM
 ↓
Final Response
```

---

# Key Features

### AI-Powered Appointment Booking

The assistant handles a multi-turn conversation to collect the information required for an appointment.

Example:

```text
User: I want to book an appointment.

Assistant: Sure. What is your name?

User: Tayyiba.

Assistant: Which doctor would you like to see?

User: Dr. Sara.

Assistant: What date and time would you prefer?
```

The assistant maintains the information collected throughout the conversation.

### LLM Tool Calling

The LLM can decide when an application tool is required.

Available tools include:

```text
update_appointment
check_doctor
check_availability
book_appointment
reset_appointment
```

The LLM does not directly execute Python or database operations.

Instead:

```text
LLM
 ↓
Tool Call
 ↓
Python Tool Executor
 ↓
Database / Application Logic
 ↓
Tool Result
 ↓
LLM
```

This separates **LLM decision-making** from **actual application execution**.

### PostgreSQL Integration

Appointment data is stored in PostgreSQL rather than a temporary Python list.

The database is used for:

* Doctor lookup
* Appointment availability
* Appointment booking
* Persistent appointment records

Example database operations include:

```sql
SELECT id
FROM doctors
WHERE LOWER(name) = LOWER(%s);
```

and:

```sql
SELECT id
FROM appointments
WHERE doctor_id = %s
AND appointment_date = %s
AND appointment_time = %s
AND status = 'booked';
```

Confirmed appointments are persisted using SQL `INSERT` operations.

### Session-Based State

The API uses a `session_id` to maintain appointment state across multiple HTTP requests.

Example:

```json
{
    "session_id": "test-user-1",
    "message": "My name is Tayyiba"
}
```

This allows different conversations to maintain separate appointment states.

Conceptually:

```text
Session 1
 └── Appointment State

Session 2
 └── Appointment State

Session 3
 └── Appointment State
```

### Reliable Application State

A key design principle of the final stage is:

> The application's state is the source of truth, not the LLM's generated response.

The system maintains structured state such as:

```text
appointment
availability_checked
awaiting_confirmation
booking_completed
messages
```

Example:

```json
{
    "patient_name": "Tayyiba",
    "doctor": "Dr. Sara",
    "date": "2026-09-20",
    "time": "09:00"
}
```

This prevents the application from relying solely on what the model says it remembers.

### FastAPI Backend

The final system is exposed through a REST API.

Main endpoints include:

```text
GET  /
GET  /health
POST /chat
```

Interactive API documentation is available through Swagger UI:

```text
http://127.0.0.1:8000/docs
```

---

# Architecture

The final architecture combines the main components developed throughout the project:

```text
                         USER / CLIENT
                              │
                              ▼
                         FASTAPI API
                              │
                              ▼
                       SESSION STATE
                              │
                              ▼
                          GROQ LLM
                              │
                     ┌────────┴────────┐
                     │                 │
                  Tool Call       Final Response
                     │
                     ▼
                PYTHON TOOLS
                     │
          ┌──────────┼───────────┐
          │          │           │
          ▼          ▼           ▼
     Check Doctor  Availability  Booking
          │          │           │
          └──────────┼───────────┘
                     ▼
                 PostgreSQL
```

---

# Appointment Booking Flow

A typical appointment follows this workflow:

```text
1. User starts a booking
          ↓
2. Assistant collects missing information
          ↓
3. Patient information is stored in session state
          ↓
4. Doctor is identified and verified
          ↓
5. Date and time are collected
          ↓
6. Availability is checked
          ↓
7. Assistant reports the available/unavailable slot
          ↓
8. User confirms the appointment
          ↓
9. Booking tool executes
          ↓
10. PostgreSQL stores the appointment
          ↓
11. Assistant returns the booking confirmation
```

---

# Technology Stack

| Technology        | Purpose                                  |
| ----------------- | ---------------------------------------- |
| **Python**        | Main programming language                |
| **Groq API**      | LLM inference and tool calling           |
| **GPT-OSS-20B**   | Model used for the tool-calling workflow |
| **Gemini API**    | Used during early experimentation        |
| **Pydantic**      | Structured data and request validation   |
| **PostgreSQL**    | Persistent appointment storage           |
| **psycopg2**      | PostgreSQL connectivity                  |
| **FastAPI**       | REST API backend                         |
| **Uvicorn**       | FastAPI development server               |
| **python-dotenv** | Environment variable management          |

---

# Development Stages

The project was intentionally developed in stages so that each major AI engineering concept could be implemented and tested independently.

## Stage 1 — Gemini API + Basic Tool Calling

The initial version introduced:

* LLM API integration
* System instructions
* Conversation history
* Tool definitions
* Function calling
* Python tool execution

The appointment data was initially stored in a simple Python list.

The basic flow was:

```text
User
 ↓
Gemini
 ↓
Tool Request
 ↓
Python Function
 ↓
Tool Result
 ↓
Gemini
 ↓
Response
```

The purpose of this stage was to understand the separation between **LLM reasoning/decision-making and application-side tool execution**.

---

## Stage 2 — Structured Output

The next stage introduced structured appointment information using Pydantic.

```python
class Appointment(BaseModel):
    patient_name: str | None = None
    doctor: str | None = None
    date: str | None = None
    time: str | None = None
```

This allowed the application to work with predictable fields instead of relying entirely on free-form text.

The workflow became:

```text
User Message
      ↓
Structured Extraction
      ↓
Pydantic Appointment
      ↓
Update State
      ↓
Check Missing Information
      ↓
Check Availability
      ↓
Confirmation
      ↓
Booking
```

---

## Stage 3 — PostgreSQL Integration

The temporary Python appointment list was replaced with PostgreSQL.

The application introduced database-backed:

* Doctor lookup
* Availability checking
* Appointment booking
* Persistent storage

This stage established a clear separation:

```text
LLM
 ↓
Information Extraction
 ↓
Python Application Logic
 ↓
PostgreSQL
```

---

## Stage 4 — Groq Function / Tool Calling

The project later moved from Gemini to Groq because of free-tier limitations encountered during development.

The model used for the tool-calling workflow is:

```text
openai/gpt-oss-20b
```

This stage introduced an LLM-controlled tool loop.

Instead of Python explicitly deciding which operation should happen next, the model could request an appropriate tool.

The agent loop became:

```text
User Message
     ↓
Groq
     ↓
Tool Required?
     ↓
   Yes
     ↓
Python Executes Tool
     ↓
Tool Result
     ↓
Groq
     ↓
Another Tool OR Final Response
```

Tools introduced during this stage included:

```text
update_appointment
check_doctor
check_availability
book_appointment
reset_appointment
```

---

## Stage 5 — FastAPI Backend

The command-line application was converted into a backend service using FastAPI.

Example request:

```json
{
    "message": "I want to book an appointment"
}
```

The backend sends the message to the AI agent and returns the generated response.

Main endpoints:

```text
GET  /
GET  /health
POST /chat
```

This transformed the project from a local CLI application into an HTTP-accessible AI backend.

---

## Stage 6 — Session-Based Integration

The initial FastAPI implementation used a shared appointment state.

That created a potential multi-user state problem:

```text
User A
   ↓
Shared Appointment State
   ↑
User B
```

Stage 6 introduced `session_id` so each conversation could maintain separate state.

Example:

```json
{
    "session_id": "test-user-1",
    "message": "My name is Tayyiba"
}
```

The same session ID is used across requests belonging to the same conversation.

Conceptually:

```text
Session 1 → Appointment State
Session 2 → Appointment State
Session 3 → Appointment State
```

---

## Stage 7 — Reliable Session State + Tool Flow

The final development stage focused on reliability and state consistency.

During testing, an important issue was identified: the LLM could generate a response containing appointment information while the application's actual state remained incomplete.

For example, the model response could mention:

```text
Dr. Sara
September 20, 2026
09:00 AM
```

while the application state still contained:

```json
{
    "patient_name": null,
    "doctor": null,
    "date": null,
    "time": null
}
```

This demonstrated an important AI engineering principle:

> Generated text should not be treated as the application's source of truth.

Stage 7 therefore focused on making application-managed state authoritative.

The session tracks information such as:

```text
appointment
availability_checked
awaiting_confirmation
booking_completed
messages
```

The resulting flow is:

```text
User
 ↓
FastAPI
 ↓
Session State
 ↓
Groq
 ↓
Tool Selection
 ↓
Python Tool Execution
 ↓
Session State Update
 ↓
Tool Result
 ↓
Groq
 ↓
Final Response
```

Additional reliability improvements include:

* Persistent conversation messages
* Current appointment state supplied to the model
* Availability state tracking
* Confirmation state tracking
* Booking state tracking
* Re-checking availability before booking
* Better protection against stale appointment information

---

# AI Engineering Concepts Demonstrated

### LLM API Integration

* API authentication
* System instructions
* Conversation history
* Model responses
* Environment variables

### Structured Data

* Pydantic models
* Structured extraction
* Validation
* Missing-field handling

### Tool Calling

* Tool schemas
* Function mapping
* Tool execution
* Tool results
* LLM-controlled tool selection

### Agent Loop

The project implements the basic tool-using agent pattern:

```text
LLM Decision
     ↓
Tool Call
     ↓
Tool Execution
     ↓
Tool Result
     ↓
LLM Decision
     ↓
Final Response
```

### Database Integration

* PostgreSQL
* SQL queries
* Persistent storage
* Database-backed availability
* Database-backed booking

### State Management

The project progressed from:

```text
Python List
     ↓
Application State
     ↓
Session-Based State
     ↓
Reliable Session + Tool State
```

### Backend Engineering

* FastAPI
* REST API
* Request validation
* JSON responses
* Swagger/OpenAPI documentation
* Session-aware API requests

---

# Security

Sensitive configuration is stored in environment variables.

Example:

```text
GROQ_API_KEY=your_api_key

POSTGRES_HOST=...
POSTGRES_PORT=...
POSTGRES_DB=...
POSTGRES_USER=...
POSTGRES_PASSWORD=...
```

The `.env` file should not be committed to GitHub.

A `.gitignore` file is used to exclude sensitive configuration and local project files.

---

# Running the Project

## 1. Clone the repository

```powershell
git clone <your-repository-url>
cd AI_Appointment_Assistant
```

## 2. Create a virtual environment

```powershell
python -m venv venv
```

## 3. Activate the environment

```powershell
.\venv\Scripts\Activate.ps1
```

## 4. Install dependencies

```powershell
pip install groq python-dotenv pydantic psycopg2-binary fastapi uvicorn
```

## 5. Configure environment variables

Create a `.env` file:

```text
GROQ_API_KEY=your_api_key

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=your_database
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
```

## 6. Configure PostgreSQL

Create the required database and tables before starting the application.

The application expects the database to contain the required doctor and appointment data.

## 7. Start the FastAPI server

```powershell
uvicorn Stage7.main:app --reload
```

The API will be available at:

```text
http://127.0.0.1:8000
```

Swagger documentation:

```text
http://127.0.0.1:8000/docs
```

---

# Git Development History

The project is divided into Git stages to preserve the development progression:

```text
stage-1
    Gemini API + basic tool calling

stage-2
    Structured output + appointment extraction

stage-3
    PostgreSQL + Python-controlled workflow

stage-4
    Groq function/tool calling + agent loop

stage-5
    FastAPI backend

stage-6
    Session-based integration

stage-7
    Reliable session state + improved tool flow
```

This progression demonstrates how the system evolved from a basic LLM experiment into an integrated AI backend.

---

# Project Evolution

```text
LLM API
   ↓
Structured Output
   ↓
Tool Calling
   ↓
PostgreSQL
   ↓
AI Agent Loop
   ↓
FastAPI
   ↓
Session State
   ↓
Reliable AI Backend
```

The main architectural progression was from:

```text
User → LLM → Answer
```

to:

```text
User
 ↓
LLM
 ↓
Decision
 ↓
Tool
 ↓
Python
 ↓
Database / Application State
 ↓
Tool Result
 ↓
LLM
 ↓
User
```

This project demonstrates how LLMs can be integrated with deterministic application logic, persistent data, tools, and backend APIs to build a more reliable AI application.

---

# Future Improvements

Potential future improvements include:

* Authentication and authorization
* Production database deployment
* Persistent session storage using Redis or a database
* Appointment cancellation and rescheduling
* Doctor-specific schedules
* Calendar integration
* Production frontend
* Deployment using Docker
* Automated testing
* Observability and logging
* Evaluation of tool-calling accuracy and booking reliability

---

## Project Status

**Core AI appointment assistant:** Completed

**Current implementation:** FastAPI + Groq + PostgreSQL + session-based state + tool calling

The project is primarily intended as an AI engineering project demonstrating the integration of **LLMs, tools, structured data, databases, state management, and backend APIs**.
