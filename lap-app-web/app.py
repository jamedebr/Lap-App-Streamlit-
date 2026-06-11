import hashlib
import json
import streamlit as st
import st.iframe as components
from supabase import create_client

# ---------------------------------------------------------------------------
# CHECKPOINT CONFIGURATION — edit these to move checkpoints
# Each entry is [latitude, longitude]
# RADIUS_DEG is how close (in degrees) the user must be to trigger a checkpoint.
# ~0.0001 degrees ≈ 11 m; ~0.001 degrees ≈ 111 m — adjust for your course.
# ---------------------------------------------------------------------------
CHECKPOINTS = {
    "cp1": [43.493045, -80.416328],
    "cp2": [43.493446, -80.416336],
    "cp3": [43.493610, -80.416313],
    "cp4": [43.493358, -80.416084],
}
RADIUS_DEG = 0.0001       # ~11 m — increase if GPS drift causes missed checkpoints
POLL_INTERVAL_MS = 5000   # how often JS polls GPS (milliseconds)
# ---------------------------------------------------------------------------


# --- Supabase client ---

@st.cache_resource
def get_client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# --- Session state defaults ---

if "page" not in st.session_state:
    st.session_state.page = "signin"
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "pending_laps" not in st.session_state:
    st.session_state.pending_laps = 0


# ---------------------------------------------------------------------------
# Lap increment — called by Python after JS signals a completed lap
# ---------------------------------------------------------------------------

def increment_laps(count: int = 1) -> None:
    client = get_client()
    result = (
        client.table("accounts")
        .select("laps")
        .eq("email", st.session_state.user_email)
        .execute()
    )
    if result.data:
        current_laps = result.data[0]["laps"]
        new_laps = current_laps + count
        client.table("accounts").update(
            {"laps": new_laps}
        ).eq("email", st.session_state.user_email).execute()
        print(f"Lap recorded for {st.session_state.user_email} — total: {new_laps}")


# ---------------------------------------------------------------------------
# GPS component — all checkpoint logic runs in JS, only lap completions
# are posted back to Python via a hidden Streamlit text input
# ---------------------------------------------------------------------------

def render_gps_component() -> None:
    # Serialize checkpoint config to pass into JS
    cp_json = json.dumps(CHECKPOINTS)

    # Each lap completion posts a message to the parent Streamlit frame.
    # We receive it via a hidden st.query_params trick: JS sets a URL hash,
    # which triggers a Streamlit rerun, and we read the lap count from it.
    # To keep things simple and reliable we use a hidden st.text_input that
    # JS writes to via the input's React synthetic event dispatch.
    gps_html = f"""
    <script>
    (function() {{
        const CHECKPOINTS = {cp_json};
        const RADIUS = {RADIUS_DEG};
        const INTERVAL = {POLL_INTERVAL_MS};

        // Checkpoint hit state — persists across polls within this page load
        const hit = {{}};
        for (const key in CHECKPOINTS) hit[key] = false;

        function near(lat, lon, target) {{
            return Math.abs(lat - target[0]) < RADIUS &&
                   Math.abs(lon - target[1]) < RADIUS;
        }}

        function notifyLap() {{
            // Find the hidden input Streamlit rendered and set its value,
            // then fire the React change + blur events so Streamlit picks it up.
            const inputs = window.parent.document.querySelectorAll('input[aria-label="lap_signal"]');
            if (inputs.length === 0) {{
                console.warn("lap_signal input not found");
                return;
            }}
            const input = inputs[0];
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.parent.HTMLInputElement.prototype, 'value'
            ).set;
            // Increment whatever value is already there so repeated laps work
            const current = parseInt(input.value) || 0;
            nativeInputValueSetter.call(input, current + 1);
            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            input.blur();
        }}

        function checkLocation() {{
            navigator.geolocation.getCurrentPosition(
                function(pos) {{
                    const lat = pos.coords.latitude;
                    const lon = pos.coords.longitude;
                    console.log("GPS:", lat, lon);

                    // Mark newly reached checkpoints
                    for (const key in CHECKPOINTS) {{
                        if (!hit[key] && near(lat, lon, CHECKPOINTS[key])) {{
                            hit[key] = true;
                            console.log("Checkpoint hit:", key);
                        }}
                    }}

                    // Check if all checkpoints are done
                    const allHit = Object.values(hit).every(Boolean);
                    if (allHit) {{
                        console.log("Lap complete!");
                        // Reset all flags
                        for (const key in hit) hit[key] = false;
                        notifyLap();
                    }}
                }},
                function(err) {{
                    console.warn("GPS error:", err.message);
                }},
                {{ enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }}
            );
        }}

        // Poll immediately then on interval
        checkLocation();
        setInterval(checkLocation, INTERVAL);
    }})();
    </script>
    """

    # Render the JS (zero height, invisible)
    components.html(gps_html, height=0)

    # Hidden input — JS writes lap completions here; Streamlit reads it
    lap_signal = st.text_input("lap_signal", value="0", label_visibility="collapsed", key="lap_signal_input")

    try:
        laps_completed = int(lap_signal)
    except (ValueError, TypeError):
        laps_completed = 0

    # If JS has signalled one or more new laps, process them
    prev = st.session_state.pending_laps
    if laps_completed > prev:
        new_laps = laps_completed - prev
        st.session_state.pending_laps = laps_completed
        increment_laps(new_laps)
        st.rerun()


# --- Page: Sign In ---

def show_signin():
    st.title("Lap App — Sign In")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Sign In", use_container_width=True):
            if not email or not password:
                st.error("Please enter your email and password.")
                return
            client = get_client()
            result = (
                client.table("accounts")
                .select("*")
                .eq("email", email)
                .eq("password", hash_password(password))
                .execute()
            )
            if result.data:
                st.session_state.user_email = email
                st.session_state.pending_laps = 0
                st.session_state.page = "home"
                st.rerun()
            else:
                st.error("Invalid email or password.")
    with col2:
        if st.button("Create an account", use_container_width=True):
            st.session_state.page = "signup"
            st.rerun()


# --- Page: Sign Up ---

def show_signup():
    st.title("Lap App — Create Account")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Submit", use_container_width=True):
            if not email or not password:
                st.error("Please fill in all fields.")
                return
            if "@woodland.on.ca" not in email:
                st.error("Only @woodland.on.ca email addresses are allowed.")
                return
            client = get_client()
            existing = (
                client.table("accounts").select("email").eq("email", email).execute()
            )
            if existing.data:
                st.error("An account with that email already exists.")
                return
            client.table("accounts").insert(
                {"email": email, "password": hash_password(password), "laps": 0}
            ).execute()
            st.session_state.user_email = email
            st.session_state.pending_laps = 0
            st.session_state.page = "home"
            st.rerun()
    with col2:
        if st.button("Already have an account? Sign in", use_container_width=True):
            st.session_state.page = "signin"
            st.rerun()


# --- Page: Home / Leaderboard ---

def show_home():
    # GPS component runs silently in background
    render_gps_component()

    client = get_client()
    rows = (
        client.table("accounts")
        .select("email, laps")
        .order("laps", desc=True)
        .execute()
        .data
    )

    st.title("Leaderboard")

    top5 = rows[:5]
    leaderboard_data = []
    for i, row in enumerate(top5, start=1):
        username = row["email"].replace("@woodland.on.ca", "")
        leaderboard_data.append({"Rank": i, "Name": username, "Laps": row["laps"]})
    st.table(leaderboard_data)

    st.divider()
    st.subheader("Your Stats")
    current_email = st.session_state.user_email
    user_rank = next(
        (i + 1 for i, r in enumerate(rows) if r["email"] == current_email), None
    )
    user_laps = next((r["laps"] for r in rows if r["email"] == current_email), 0)
    username = current_email.replace("@woodland.on.ca", "")

    if user_rank:
        st.table([{"Rank": user_rank, "Name": username, "Laps": user_laps}])
    else:
        st.info("Your account was not found in the leaderboard.")

    if st.button("Sign Out"):
        st.session_state.user_email = None
        st.session_state.pending_laps = 0
        st.session_state.page = "signin"
        st.rerun()


# --- Router ---

if st.session_state.page == "signin":
    show_signin()
elif st.session_state.page == "signup":
    show_signup()
elif st.session_state.page == "home":
    if st.session_state.user_email is None:
        st.session_state.page = "signin"
        st.rerun()
    else:
        show_home()
