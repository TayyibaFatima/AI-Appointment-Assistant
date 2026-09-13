# AI Appointment Assistant

An AI-powered clinic appointment assistant built progressively to learn **LLM APIs, structured outputs, tool/function calling, databases, agentic workflows, session state, and backend APIs**.

This project was developed in multiple stages. Each stage introduced a new AI engineering concept and built on the previous one.

---

# Project Goal

The goal of this project was not only to build an appointment booking system, but to understand how an AI assistant evolves from a simple LLM application into a **tool-using agent connected to a real database and backend API**.

The assistant can:

* Collect patient information
* Identify doctors
* Check doctor availability
* Check appointment availability
* Ask for booking confirmation
* Book appointments
* Store confirmed appointments in PostgreSQL
* Maintain appointment state during a session
* Expose the assistant through a FastAPI backend

---

# Learning Journey

```text
Stage 1
Gemini API
   ↓
Stage 2
Structured Output
   ↓
Stage 3
PostgreSQL + Python-controlled workflow
   ↓
Stage 4
Groq Function / Tool Calling
   ↓
Stage 5
FastAPI Backend
   ↓
Stage 6
Session-based Final Integration
   ↓
Stage 7
Reliable Session State + Tool Flow
```

Each stage represents a different step in understanding AI application development.

---

# Stage 1 — Gemini API + Basic Tool Calling

### Main concepts learned

* Connecting an application to an LLM API
* Environment variables
* Gemini API client
* System instructions
* Conversation history
* Function/tool definitions
* Function calling
* Sending tool results back to the model
* Separating AI decision-making from Python execution

### What was built

The first version used the Gemini API.

The assistant could:

1. Receive a user's message.
2. Understand the appointment request.
3. Decide whether a tool was required.
4. Request `check_availability`.
5. Python executed the actual availability function.
6. The result was sent back to Gemini.
7. Gemini generated the final response.
8. If the user confirmed, Gemini could request `book_appointment`.

The appointment data at this stage was stored in a simple Python list.

```python
booked_appointments = [
    {
        "patient_name": "Existing Patient",
        "doctor": "Dr. Ahmed",
        "date": "2026-09-11",
        "time": "04:00 PM"
    }
]
```

This was intentionally simple because the main goal of Stage 1 was understanding **LLM + tool interaction**.

### Important concept

The LLM does not directly execute Python functions.

The flow was:

```text
User
 ↓
Gemini
 ↓
Gemini decides a tool is needed
 ↓
Python executes the tool
 ↓
Tool result
 ↓
Gemini
 ↓
Final response
```

---

# Stage 2 — Structured Output

### Main concepts learned

* Structured output
* JSON
* Pydantic
* Information extraction
* State management
* Validation
* Handling missing information
* Multi-turn appointment collection

Gemini was now used to extract appointment information into a predictable structure.

```python
class Appointment(BaseModel):
    patient_name: str | None = None
    doctor: str | None = None
    date: str | None = None
    time: str | None = None
```

Instead of receiving arbitrary text, the application could work with predictable fields:

```text
patient_name
doctor
date
time
```

### Example

User:

```text
My name is Tayyiba and I want Dr Sara tomorrow at 9 AM.
```

The model extracts information into structured data.

The Python application then checks which fields are missing.

```text
Patient name → available
Doctor       → available
Date         → available
Time         → available
```

If something is missing, the application asks for it.

```text
Assistant: What time would you like for the appointment?
```

### Stage 2 workflow

```text
User message
      ↓
Gemini structured extraction
      ↓
Pydantic Appointment
      ↓
Update current appointment
      ↓
Check missing information
      ↓
Ask for missing information
      ↓
Check availability
      ↓
Ask confirmation
      ↓
Book appointment
```

At this stage, the **Python program controlled the workflow**.

---

# Stage 3 — PostgreSQL + Database Integration

### Main concepts learned

* PostgreSQL
* SQL queries
* `psycopg2`
* Database connections
* Database-backed availability
* Database-backed booking
* Data normalization
* Persistent storage
* Separation between AI and database logic

The Python list from Stage 1 was replaced with a real PostgreSQL database.

The assistant could now work with tables such as:

```text
doctors
appointments
```

The application could query the database to find a doctor:

```sql
SELECT id
FROM doctors
WHERE LOWER(name) = LOWER(%s)
```

It could also check whether a slot was already booked:

```sql
SELECT id
FROM appointments
WHERE doctor_id = %s
AND appointment_date = %s
AND appointment_time = %s
AND status = 'booked'
```

### Booking

A confirmed appointment was inserted into PostgreSQL:

```sql
INSERT INTO appointments
(
    patient_name,
    doctor_id,
    appointment_date,
    appointment_time,
    status
)
VALUES (%s, %s, %s, %s, 'booked')
```

### Important learning

Stage 3 introduced a major separation:

```text
LLM
 ↓
Extract information
 ↓
Python controls workflow
 ↓
Python calls database functions
 ↓
PostgreSQL
```

At this stage, **Python was deciding when to call the tools/database functions**.

---

# Stage 4 — Groq Function / Tool Calling

Gemini's free-tier limits became restrictive during development, so the project moved to **Groq**.

The model used in the project was:

```text
openai/gpt-oss-20b
```

### Main concepts learned

* Function calling
* Tool calling
* Agent loops
* Tool schemas
* Function maps
* Tool execution
* Sending tool results back to the LLM
* LLM-controlled workflows

This stage introduced the biggest conceptual change.

## Stage 3

Python decided:

```text
if information is complete:
    check availability

if user confirms:
    book appointment
```

## Stage 4

Groq decides:

```text
Which tool should I use?
```

Python only executes the tool requested by Groq.

The architecture became:

```text
                    ┌───────────────┐
                    │     Groq      │
                    │     LLM       │
                    └───────┬───────┘
                            │
                       Tool call
                            ↓
                    ┌───────────────┐
                    │    Python     │
                    │ Tool Executor │
                    └───────┬───────┘
                            │
                ┌───────────┼───────────┐
                ↓           ↓           ↓
           PostgreSQL   Appointment   Reset
                         State
```

### Tools introduced

```text
update_appointment
check_doctor
check_availability
book_appointment
reset_appointment
```

The model receives descriptions of these tools.

It can then decide which one is appropriate.

### Agent loop

The core Stage 4 idea was:

```text
User message
     ↓
Groq
     ↓
Does Groq need a tool?
     ↓
   Yes
     ↓
Python executes tool
     ↓
Tool result sent to Groq
     ↓
Groq decides what to do next
     ↓
Another tool OR final response
```

This was the first stage where the project behaved like a basic **tool-using AI agent**.

---

# Stage 5 — FastAPI Backend

After understanding tool calling, the next step was to turn the CLI application into a backend API.

### Main concepts learned

* FastAPI
* REST API
* API endpoints
* Request models
* JSON responses
* Backend integration
* Swagger documentation
* Connecting an AI agent to an HTTP API

The command-line interface was replaced with a FastAPI backend.

The main endpoint became:

```text
POST /chat
```

A request could contain:

```json
{
    "message": "I want to book an appointment"
}
```

The backend sends the message to the AI agent and returns a response.

### Useful endpoints

```text
GET /
POST /chat
GET /health
```

Swagger documentation was available at:

```text
http://127.0.0.1:8000/docs
```

### Architecture

```text
Client
  ↓
FastAPI
  ↓
Groq Agent
  ↓
Tools
  ↓
PostgreSQL
```

This was an important transition from a **local CLI project** to an actual **backend service**.

---

# Stage 6 — Session-Based Integration

Stage 5 used a single global appointment state.

That works for a simple single-user demonstration, but it creates a problem:

```text
User A
   ↓
current_appointment

User B
   ↓
same current_appointment
```

Different users could potentially interfere with each other's appointment state.

Stage 6 introduced a `session_id`.

Example:

```text
test-user-1
```

Each session received its own appointment state.

Conceptually:

```text
Session 1
 └── Appointment

Session 2
 └── Appointment

Session 3
 └── Appointment
```

A request became:

```json
{
    "session_id": "test-user-1",
    "message": "My name is Tayyiba"
}
```

The same session ID was reused for the conversation.

### Example flow

```text
Request 1
"I want to book an appointment"

        ↓

Request 2
"My name is Tayyiba"

        ↓

Request 3
"Dr Sara"

        ↓

Request 4
"September 20 2026 at 9 AM"

        ↓

Request 5
"Yes, book it"
```

The session allows the assistant to maintain the appointment information across HTTP requests.

Stage 6 also introduced endpoints for retrieving and resetting appointment state.

---

# Stage 7 — Reliable Session State + Tool Flow

Stage 7 was created to fix a state-management issue discovered during testing of Stage 6.

The assistant could sometimes know appointment information in its response while the Python session state still contained:

```json
{
    "patient_name": null,
    "doctor": null,
    "date": null,
    "time": null
}
```

This revealed an important AI engineering lesson:

> The LLM's response should not be treated as the application's source of truth.

The application state should be authoritative.

### Stage 7 improvements

Stage 7 introduced:

* Reliable session state
* Persistent conversation messages
* Correct tool-call history
* Current appointment state supplied to the model
* Availability state
* Confirmation state
* Booking state
* Re-checking availability before booking
* Better protection against stale appointment information

The session now tracks:

```text
appointment
availability_checked
awaiting_confirmation
booking_completed
messages
```

### State flow

```text
User
 ↓
FastAPI
 ↓
Session state
 ↓
Groq
 ↓
Tool selection
 ↓
Python tool execution
 ↓
Session state updated
 ↓
Tool result
 ↓
Groq
 ↓
Final response
```

The current appointment state is treated as authoritative.

For example:

```json
{
    "patient_name": "Tayyiba",
    "doctor": "Dr. Sara",
    "date": "2026-09-20",
    "time": "09:00"
}
```

This state is maintained by Python rather than relying only on what the LLM remembers.

---

# Technologies Used

| Technology    | Purpose                                   |
| ------------- | ----------------------------------------- |
| Python        | Main programming language                 |
| Gemini API    | LLM experimentation in Stages 1–2         |
| Groq API      | LLM and tool calling in later stages      |
| GPT-OSS-20B   | Model used for Groq tool-calling workflow |
| Pydantic      | Structured data and request validation    |
| PostgreSQL    | Persistent appointment storage            |
| psycopg2      | Python–PostgreSQL connection              |
| FastAPI       | Backend API                               |
| Uvicorn       | FastAPI development server                |
| python-dotenv | Environment variable management           |

---

# Project Architecture

The final architecture combines the concepts learned throughout the project:

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
                         GROQ / LLM
                              │
                    ┌─────────┴─────────┐
                    │                   │
                Tool Call           Final Response
                    │
                    ▼
              PYTHON TOOLS
                    │
        ┌───────────┼────────────┐
        │           │            │
        ▼           ▼            ▼
   Check Doctor  Availability  Booking
        │           │            │
        └───────────┼────────────┘
                    ▼
                PostgreSQL
```

---

# Appointment Booking Flow

A typical booking follows this process:

```text
1. User starts a booking
          ↓
2. Assistant asks for missing information
          ↓
3. Patient provides name
          ↓
4. Patient provides doctor
          ↓
5. Doctor is verified
          ↓
6. Patient provides date
          ↓
7. Patient provides time
          ↓
8. Availability is checked
          ↓
9. Assistant reports availability
          ↓
10. User confirms
          ↓
11. Booking tool executes
          ↓
12. PostgreSQL stores appointment
          ↓
13. Assistant confirms booking
```

---

# Important AI Engineering Concepts Learned

## 1. LLM API Integration

Learned how to:

* Connect Python to an LLM
* Send prompts
* Receive model responses
* Use system instructions
* Maintain conversations

---

## 2. Structured Output

Instead of relying on free-form text, information can be represented as structured data.

Example:

```python
class Appointment(BaseModel):
    patient_name: str | None = None
    doctor: str | None = None
    date: str | None = None
    time: str | None = None
```

This makes downstream Python logic more reliable.

---

## 3. Tool Calling

The model can decide:

```text
"I need to check availability."
```

and request:

```text
check_availability(...)
```

Python then executes the actual function.

This creates a separation between:

```text
AI decision-making
```

and

```text
real-world execution
```

---

## 4. Agent Loop

The project learned the basic agent loop:

```text
Think / decide
     ↓
Tool call
     ↓
Tool execution
     ↓
Tool result
     ↓
Think / decide again
     ↓
Final answer
```

This is fundamentally different from simply asking an LLM a question and printing its response.

---

## 5. Database Integration

The assistant is connected to a real PostgreSQL database.

This means confirmed appointments are no longer just temporary Python objects.

They are persisted in the database.

---

## 6. State Management

The project progressed from:

```text
Python list
```

to:

```text
current appointment
```

to:

```text
session-based appointment state
```

This demonstrated why state becomes increasingly important as an AI application becomes multi-turn and multi-user.

---

## 7. Backend Development

The final stages introduced FastAPI so the AI agent could be accessed through HTTP rather than only through a command-line interface.

---

# Security

API keys are stored in environment variables rather than directly in source code.

Example:

```text
.env
```

with variables such as:

```text
GROQ_API_KEY=your_api_key
POSTGRES_HOST=...
POSTGRES_PORT=...
POSTGRES_DB=...
POSTGRES_USER=...
POSTGRES_PASSWORD=...
```

The `.env` file should **not** be committed to GitHub.

---

# Running the Project

Create and activate the virtual environment:

```powershell
python -m venv venv
```

Activate it:

```powershell
.\venv\Scripts\Activate.ps1
```

Install the required packages:

```powershell
pip install groq python-dotenv pydantic psycopg2-binary fastapi uvicorn
```

For the FastAPI stages, run:

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

The project is intentionally divided into Git stages so that each major learning milestone is preserved.

```text
stage-1
    Gemini API + basic tool calling

stage-2
    Structured output + appointment extraction

stage-3
    PostgreSQL + Python-controlled appointment workflow

stage-4
    Groq function/tool calling + agent loop

stage-5
    FastAPI backend

stage-6
    Session-based final integration

stage-7
    Reliable session state + improved tool flow
```

This allows the project to show not only the final result, but also the **development and learning progression**.

---

# What This Project Demonstrates

This project demonstrates the progression from a basic LLM application to a small agentic AI system:

```text
LLM
 ↓
Structured Data
 ↓
Tools
 ↓
Database
 ↓
Agent
 ↓
API
 ↓
Session State
 ↓
Integrated AI Backend
```

The main learning outcome was understanding that an AI application is not simply:

```text
User → LLM → Answer
```

Instead, a useful AI system can be:

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
Database / External System
 ↓
Tool Result
 ↓
LLM
 ↓
User
```

This project was built progressively to understand each part of that architecture.
