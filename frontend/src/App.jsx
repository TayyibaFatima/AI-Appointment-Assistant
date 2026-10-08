import { useEffect, useState } from "react";
import "./App.css";

const API_URL = "https://ai-appointment-assistant.fastapicloud.dev";

const INACTIVITY_LIMIT = 5 * 60 * 1000;
const APP_ACTIVITY_KEY = "appointment_app_last_activity";

const EMPTY_APPOINTMENT = {
  patient_name: null,
  doctor: null,
  date: null,
  time: null
};

function App() {
  // ------------------------------------------------------------
  // SESSION
  // ------------------------------------------------------------

  // A new appointment session is created when the page is loaded.
  // This is separate from the app-wide inactivity timer.
  const [sessionId] = useState(() => {
    return "web-user-" + Date.now();
  });

  // ------------------------------------------------------------
  // CHAT STATE
  // ------------------------------------------------------------

  const [message, setMessage] = useState("");

  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Hello! I'm your AI clinic appointment assistant. How can I help you today?"
    }
  ]);

  // ------------------------------------------------------------
  // APPOINTMENT STATE
  // ------------------------------------------------------------

  const [appointment, setAppointment] = useState(
    EMPTY_APPOINTMENT
  );

  const [availabilityChecked, setAvailabilityChecked] =
    useState(false);

  const [awaitingConfirmation, setAwaitingConfirmation] =
    useState(false);

  const [bookingCompleted, setBookingCompleted] =
    useState(false);

  // ------------------------------------------------------------
  // UI STATE
  // ------------------------------------------------------------

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [showWakeUp, setShowWakeUp] = useState(false);

  const [showResetPopup, setShowResetPopup] = useState(false);

  // ------------------------------------------------------------
  // INITIAL LOAD
  // ------------------------------------------------------------

  useEffect(() => {
    loadAppointment();
  }, []);

  // ------------------------------------------------------------
  // LOAD APPOINTMENT STATE
  // ------------------------------------------------------------

  async function loadAppointment() {
    try {
      const response = await fetch(
        `${API_URL}/appointment/${sessionId}`
      );

      if (!response.ok) {
        return;
      }

      const data = await response.json();

      setAppointment(data.appointment);
      setAvailabilityChecked(
        data.availability_checked
      );
      setAwaitingConfirmation(
        data.awaiting_confirmation
      );
      setBookingCompleted(
        data.booking_completed
      );
    } catch (error) {
      console.log(
        "Could not load appointment state."
      );
    }
  }

  // ------------------------------------------------------------
  // APP ACTIVITY
  // ------------------------------------------------------------

  function getLastAppActivity() {
    const storedActivity = localStorage.getItem(
      APP_ACTIVITY_KEY
    );

    if (!storedActivity) {
      return null;
    }

    const timestamp = Number(storedActivity);

    if (Number.isNaN(timestamp)) {
      return null;
    }

    return timestamp;
  }

  function updateAppActivity() {
    localStorage.setItem(
      APP_ACTIVITY_KEY,
      Date.now().toString()
    );
  }

  function shouldShowWakeUp() {
    const lastActivity = getLastAppActivity();

    // First-ever use of the app should NOT show wake-up.
    if (lastActivity === null) {
      return false;
    }

    return (
      Date.now() - lastActivity >=
      INACTIVITY_LIMIT
    );
  }

  // ------------------------------------------------------------
  // SEND MESSAGE
  // ------------------------------------------------------------

  async function sendMessage() {
    const trimmedMessage = message.trim();

    if (!trimmedMessage || loading) {
      return;
    }

    // The timer belongs to the application, not
    // to the current appointment session.
    const wakeUpRequired = shouldShowWakeUp();

    setShowWakeUp(wakeUpRequired);

    setMessages((previous) => [
      ...previous,
      {
        role: "user",
        content: trimmedMessage
      }
    ]);

    setMessage("");
    setLoading(true);
    setError("");

    try {
      const response = await fetch(
        `${API_URL}/chat`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            session_id: sessionId,
            message: trimmedMessage
          })
        }
      );

      if (!response.ok) {
        throw new Error(
          "Backend request failed."
        );
      }

      const data = await response.json();

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: data.response
        }
      ]);

      setAppointment(data.appointment);

      setAvailabilityChecked(
        data.availability_checked
      );

      setAwaitingConfirmation(
        data.awaiting_confirmation
      );

      setBookingCompleted(
        data.booking_completed
      );

      // Update the APP-WIDE activity timestamp.
      // This is intentionally NOT stored in the session.
      updateAppActivity();

      // Backend can also tell us whether it detected
      // that its own activity was idle for 5+ minutes.
      if (data.wake_up === true) {
        setShowWakeUp(true);
      }
    } catch (error) {
      setError(
        "Unable to connect to the appointment assistant. Please try again."
      );
    } finally {
      setLoading(false);
    }
  }

  // ------------------------------------------------------------
  // RESET APPOINTMENT
  // ------------------------------------------------------------

  function requestReset() {
    setShowResetPopup(true);
  }

  function cancelReset() {
    setShowResetPopup(false);
  }

  async function confirmReset() {
    setShowResetPopup(false);

    try {
      const response = await fetch(
        `${API_URL}/appointment/${sessionId}`,
        {
          method: "DELETE"
        }
      );

      if (!response.ok) {
        throw new Error(
          "Reset request failed."
        );
      }

      setAppointment(EMPTY_APPOINTMENT);

      setAvailabilityChecked(false);
      setAwaitingConfirmation(false);
      setBookingCompleted(false);

      setMessages([
        {
          role: "assistant",
          content:
            "Your appointment information has been reset. How can I help you?"
        }
      ]);

      setError("");

      // Resetting an appointment is still app activity.
      updateAppActivity();
    } catch (error) {
      setError(
        "Could not reset the appointment. Please try again."
      );
    }
  }

  // ------------------------------------------------------------
  // FORMAT DATE
  // ------------------------------------------------------------

  function formatDate(date) {
    if (!date) {
      return "Not provided";
    }

    const parsedDate = new Date(
      date + "T00:00:00"
    );

    return parsedDate.toLocaleDateString(
      "en-US",
      {
        year: "numeric",
        month: "long",
        day: "numeric"
      }
    );
  }

  // ------------------------------------------------------------
  // APPOINTMENT STATUS
  // ------------------------------------------------------------

  function getStatus() {
    if (bookingCompleted) {
      return "Booked";
    }

    if (awaitingConfirmation) {
      return "Awaiting confirmation";
    }

    if (availabilityChecked) {
      return "Slot available";
    }

    if (
      appointment.patient_name ||
      appointment.doctor ||
      appointment.date ||
      appointment.time
    ) {
      return "Collecting details";
    }

    return "Ready to book";
  }

  // ------------------------------------------------------------
  // RENDER
  // ------------------------------------------------------------

  return (
    <div className="app">

      {/* ======================================================
          TOP BAR
          ====================================================== */}

      <header className="topbar">

        <div>
          <h1>
            AI Appointment Assistant
          </h1>

          <p>
            Smart clinic appointment booking
          </p>
        </div>

        <div className="backend-status">
          <span className="status-dot"></span>
          AI Assistant
        </div>

      </header>


      {/* ======================================================
          MAIN CONTENT
          ====================================================== */}

      <main className="main-container">

        {/* ====================================================
            CHAT
            ==================================================== */}

        <section className="chat-card">

          <div className="chat-header">

            <div>
              <h2>
                Appointment Assistant
              </h2>

              <p>
                Book your clinic appointment through chat
              </p>
            </div>

          </div>


          {/* ==================================================
              MESSAGES
              ================================================== */}

          <div className="messages">

            {messages.map((item, index) => (

              <div
                key={index}
                className={`message-row ${item.role}`}
              >

                <div className="message">
                  {item.content}
                </div>

              </div>

            ))}


            {/* =================================================
                LOADING MESSAGE
                ================================================= */}

            {loading && (

              <div className="message-row assistant">

                <div className="message typing">

                  {showWakeUp ? (
                    <>
                      ⏳ Waking up the AI assistant...

                      <br />

                      <small>
                        This may take up to about 1 minute
                        on the first request.
                        <br />
                        Thanks for your patience!
                      </small>
                    </>
                  ) : (
                    "Thinking..."
                  )}

                </div>

              </div>

            )}

          </div>


          {/* ==================================================
              ERROR
              ================================================== */}

          {error && (
            <div className="error">
              {error}
            </div>
          )}


          {/* ==================================================
              INPUT
              ================================================== */}

          <div className="input-area">

            <input
              type="text"
              value={message}
              placeholder="Type your message..."
              onChange={(event) =>
                setMessage(event.target.value)
              }
              onKeyDown={(event) => {
                if (
                  event.key === "Enter"
                ) {
                  sendMessage();
                }
              }}
              disabled={loading}
            />

            <button
              onClick={sendMessage}
              disabled={
                loading ||
                !message.trim()
              }
            >
              Send
            </button>

          </div>

        </section>


        {/* ====================================================
            APPOINTMENT CARD
            ==================================================== */}

        <aside className="appointment-card">

          <div className="appointment-header">

            <div>
              <h2>
                Appointment
              </h2>

              <p>
                Current booking details
              </p>
            </div>

            <span className="session-badge">
              Active
            </span>

          </div>


          <div className="details">

            <Detail
              label="Patient"
              value={appointment.patient_name}
            />

            <Detail
              label="Doctor"
              value={appointment.doctor}
            />

            <Detail
              label="Date"
              value={formatDate(
                appointment.date
              )}
            />

            <Detail
              label="Time"
              value={appointment.time}
            />

          </div>


          <div className="booking-status">

            <span>
              Status
            </span>

            <strong>
              {getStatus()}
            </strong>

          </div>


          <button
            className="reset-button"
            onClick={requestReset}
          >
            Reset Appointment
          </button>

        </aside>

      </main>


      {/* ======================================================
          FOOTER
          ====================================================== */}

      <footer>
        AI Appointment Assistant
      </footer>


      {/* ======================================================
          RESET CONFIRMATION MODAL
          ====================================================== */}

      {showResetPopup && (

        <div
          className="modal-overlay"
          onClick={cancelReset}
        >

          <div
            className="reset-modal"
            onClick={(event) =>
              event.stopPropagation()
            }
          >

            <h2>
              Start over?
            </h2>

            <p>
              This will clear your current
              appointment details. It will not
              cancel an already booked appointment.
            </p>

            <div className="modal-buttons">

              <button
                className="modal-cancel"
                onClick={cancelReset}
              >
                Cancel
              </button>

              <button
                className="modal-confirm"
                onClick={confirmReset}
              >
                Start Over
              </button>

            </div>

          </div>

        </div>

      )}

    </div>
  );
}


// ============================================================
// DETAIL COMPONENT
// ============================================================

function Detail({ label, value }) {
  return (
    <div className="detail">

      <span>
        {label}
      </span>

      <strong>
        {value || "Not provided"}
      </strong>

    </div>
  );
}


export default App;