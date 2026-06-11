import hashlib
import json
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
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
RADIUS_DEG = 0.0002       # ~11 m — increase if GPS drift causes missed checkpoints
POLL_INTERVAL_MS = 5000   # how often JS polls GPS (milliseconds)
REFRESH_INTERVAL_MS = 2000  # how often Python checks for new laps in the URL
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
if "laps_offset" not in st.session_state:
    st.session_state.laps_offset = 0


# ---------------------------------------------------------------------------
# Read lap signal from URL query params and write to Supabase if new
# ---------------------------------------------------------------------------

def process_pending_laps() -> None:
    """
    JS writes ?laps=N into the URL via pushState (no page reload).
    st_autorefresh triggers Python reruns so we can read it here.
    laps_offset tracks what we've already processed this session.
    """
    try:
        url_laps = int(st.query_params.get("laps", 0))
    except (ValueError, TypeError):
        url_laps = 0

    new_laps = url_laps - st.session_state.laps_offset
    if new_laps <= 0:
        return

    st.session_state.laps_offset = url_laps

    client = get_client()
    result = (
        client.table("accounts")
        .select("laps")
        .eq("email", st.session_state.user_email)
        .execute()
    )
    if result.data:
        current_laps = result.data[0]["laps"]
        updated = current_laps + new_laps
        client.table("accounts").update(
            {"laps": updated}
        ).eq("email", st.session_state.user_email).execute()
        print(f"Lap recorded for {st.session_state.user_email} — total now: {updated}")


# ---------------------------------------------------------------------------
# GPS component — all checkpoint + lap logic lives in JS.
# Uses pushState to update ?laps=N without a page reload so session
# state is preserved. st_autorefresh polls for the change in Python.
# ---------------------------------------------------------------------------

def render_gps_component() -> None:
    cp_json = json.dumps(CHECKPOINTS)

    try:
        current_url_laps = int(st.query_params.get("laps", 0))
    except (ValueError, TypeError):
        current_url_laps = 0

    gps_html = f"""
    <script>
    (function() {{
        const CHECKPOINTS = {cp_json};
        const RADIUS      = {RADIUS_DEG};
        const INTERVAL    = {POLL_INTERVAL_MS};

        let lapCount = {current_url_laps};

        const hit = {{}};
        for (const key in CHECKPOINTS) hit[key] = false;

        function near(lat, lon, target) {{
            return Math.abs(lat - target[0]) < RADIUS &&
                   Math.abs(lon - target[1]) < RADIUS;
        }}

        function onLapComplete() {{
            lapCount += 1;
            console.log("Lap complete! Total laps this session:", lapCount);
            // pushState updates the URL without a page reload,
            // so Streamlit session state is preserved.
            const url = new URL(window.parent.location.href);
            url.searchParams.set("laps", lapCount);
            window.parent.history.pushState({{}}, "", url.toString());
        }}

        function checkLocation() {{
            navigator.geolocation.getCurrentPosition(
                function(pos) {{
                    const lat = pos.coords.latitude;
                    const lon = pos.coords.longitude;
                    console.log("GPS:", lat, lon);

                    for (const key in CHECKPOINTS) {{
                        if (!hit[key] && near(lat, lon, CHECKPOINTS[key])) {{
                            hit[key] = true;
                            console.log("Checkpoint hit:", key);
                        }}
                    }}

                    if (Object.values(hit).every(Boolean)) {{
                        for (const key in hit) hit[key] = false;
                        onLapComplete();
                    }}
                }},
                function(err) {{
                    console.warn("GPS error:", err.message);
                }},
                {{ enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }}
            );
        }}

        checkLocation();
        setInterval(checkLocation, INTERVAL);
    }})();
    </script>
    """

    components.html(gps_html, height=0)


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
                st.session_state.laps_offset = 0
                st.session_state.page = "home"
                st.query_params.clear()
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
            st.session_state.laps_offset = 0
            st.session_state.page = "home"
            st.query_params.clear()
            st.rerun()
    with col2:
        if st.button("Already have an account? Sign in", use_container_width=True):
            st.session_state.page = "signin"
            st.rerun()


# --- Page: Home / Leaderboard ---

def show_home():
    # Autorefresh triggers Python reruns so we can detect URL changes from JS
    st_autorefresh(interval=REFRESH_INTERVAL_MS, key="lap_check_refresh")

    # Check for any laps JS has written to the URL since last rerun
    process_pending_laps()

    # GPS component runs silently in the background
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
        st.session_state.laps_offset = 0
        st.session_state.page = "signin"
        st.query_params.clear()
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
