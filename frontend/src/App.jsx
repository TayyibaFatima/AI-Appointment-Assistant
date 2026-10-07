import { useEffect, useState } from "react";
import "./App.css";

const API_URL = "https://ai-appointment-assistant.fastapicloud.dev";

// Show wake-up message after 5 minutes of inactivity.
const INACTIVITY_LIMIT = 5 * 60 * 1000;

function App() {

  // Create a completely new session whenever the page is refreshed.
  const [sessionId] = useState(() => {
    return "web-user-" + Date.now();
  });

  const [message, setMessage] = useState("");

  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Hello! I'm your AI clinic appointment assistant. How can I help you today?"
    }
  ]);

  const [appointment, setAppointment] = useState({
    patient_name: null,
    doctor: null,
    date: null,
    time: null
  });

  const [availabilityChecked, setAvailabilityChecked] = useState(false);
  const [awaitingConfirmation, setAwaitingConfirmation] = useState(false);
  const [bookingCompleted, setBookingCompleted] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Stores the time of the previous completed request.
  const [lastActivity, setLastActivity] = useState(null);

  // Controls which loading message is displayed.
  const [showWakeUp, setShowWakeUp] = useState(true);


  useEffect(() => {
    loadAppointment();
  }, []);


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
      setAvailabilityChecked(data.availability_checked);
      setAwaitingConfirmation(data.awaiting_confirmation);
      setBookingCompleted(data.booking_completed);

    } catch (error) {

      console.log("Could not load appointment state.");

    }
  }


  async function sendMessage() {

    const trimmedMessage = message.trim();

    if (!trimmedMessage || loading) {
      return;
    }

    // Determine whether this request should show
    // the wake-up message BEFORE changing lastActivity.
    const now = Date.now();

    const shouldWakeUp =
      lastActivity === null ||
      now - lastActivity >= INACTIVITY_LIMIT;

    setShowWakeUp(shouldWakeUp);

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

      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          session_id: sessionId,
          message: trimmedMessage
        })
      });

      if (!response.ok) {
        throw new Error("Backend request failed.");
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
      setAvailabilityChecked(data.availability_checked);
      setAwaitingConfirmation(data.awaiting_confirmation);
      setBookingCompleted(data.booking_completed);

    } catch (error) {

      setError(
        "Unable to connect to the appointment assistant."
      );

    } finally {

      // Mark this request as the latest activity
      // after the request has finished.
      setLastActivity(Date.now());

      setLoading(false);
    }
  }


  async function resetAppointment() {

    try {

      await fetch(
        `${API_URL}/appointment/${sessionId}`,
        {
          method: "DELETE"
        }
      );

      setAppointment({
        patient_name: null,
        doctor: null,
        date: null,
        time: null
      });

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

    } catch (error) {

      setError(
        "Could not reset the appointment."
      );
    }
  }


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


  function getStatus() {

    // Successful booking gets highest priority.
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


  return (
    <div className="app">


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


      <main className="main-container">


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


          {error && (

            <div className="error">
              {error}
            </div>

          )}


          <div className="input-area">


            <input
              type="text"
              value={message}
              placeholder="Type your message..."
              onChange={(event) =>
                setMessage(event.target.value)
              }
              onKeyDown={(event) => {

                if (event.key === "Enter") {
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
              value={formatDate(appointment.date)}
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
            onClick={resetAppointment}
          >
            Reset Appointment
          </button>


        </aside>


      </main>


      <footer>
        AI Appointment Assistant
      </footer>


    </div>
  );
}


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

