import hashlib
import streamlit as st
from supabase import create_client
from streamlit_js_eval import get_geolocation
from streamlit_autorefresh import st_autorefresh

# ---------------------------------------------------------------------------
# CHECKPOINT CONFIGURATION — edit these to move checkpoints
# Each entry is [latitude, longitude]
# RADIUS_DEG is how close (in degrees) the user must be to trigger a checkpoint.
# ~0.0001 degrees ≈ 11 m; ~0.001 degrees ≈ 111 m — adjust for your course.
# ---------------------------------------------------------------------------
CHECKPOINTS = {
    "cp1": [43.540951, -80.255961],
    "cp2": [43.541119, -80.256094],
    "cp3": [43.541163, -80.256000],
    "cp4": [43.5410022, -80.255871],
}
RADIUS_DEG = 0.0001          # ~11 m — tighten or loosen as needed
POLL_INTERVAL_MS = 5_000     # how often to re-check location (milliseconds)
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

# Checkpoint hit flags — one per key in CHECKPOINTS
for _cp_key in CHECKPOINTS:
    if _cp_key not in st.session_state:
        st.session_state[_cp_key] = False


# ---------------------------------------------------------------------------
# Lap / checkpoint logic
# ---------------------------------------------------------------------------

def _near(lat: float, lon: float, target: list) -> bool:
    """Return True when (lat, lon) is within RADIUS_DEG of target."""
    return (
        abs(lat - target[0]) < RADIUS_DEG
        and abs(lon - target[1]) < RADIUS_DEG
    )


def process_location(lat: float, lon: float) -> None:
    """
    Check every checkpoint and, if all have been hit, increment the
    user's lap count in Supabase and reset the flags.
    Checkpoints can be claimed in any order.
    """
    # Mark any newly-reached checkpoints
    for cp_key, coords in CHECKPOINTS.items():
        if not st.session_state[cp_key] and _near(lat, lon, coords):
            st.session_state[cp_key] = True

    # If every checkpoint has been hit → completed lap
    if all(st.session_state[cp_key] for cp_key in CHECKPOINTS):
        client = get_client()
        # Fetch current lap count
        result = (
            client.table("accounts")
            .select("laps")
            .eq("email", st.session_state.user_email)
            .execute()
        )
        if result.data:
            current_laps = result.data[0]["laps"]
            client.table("accounts").update(
                {"laps": current_laps + 1}
            ).eq("email", st.session_state.user_email).execute()

        # Reset checkpoint flags
        for cp_key in CHECKPOINTS:
            st.session_state[cp_key] = False


def run_location_tracking() -> None:
    """
    Called on every rerun while the user is logged in.
    Requests the browser's geolocation (GPS on mobile) and processes it.
    The autorefresh timer drives repeated calls.
    """
    location = get_geolocation()          # non-blocking JS bridge
    if location and "coords" in location:
        lat = location["coords"]["latitude"]
        lon = location["coords"]["longitude"]
        process_location(lat, lon)


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
            st.session_state.page = "home"
            st.rerun()
    with col2:
        if st.button("Already have an account? Sign in", use_container_width=True):
            st.session_state.page = "signin"
            st.rerun()


# --- Page: Home / Leaderboard ---

def show_home():
    # Auto-refresh drives the location polling loop
    st_autorefresh(interval=POLL_INTERVAL_MS, key="location_refresh")

    # Run location tracking silently (no UI)
    run_location_tracking()

    client = get_client()
    rows = (
        client.table("accounts")
        .select("email, laps")
        .order("laps", desc=True)
        .execute()
        .data
    )

    st.title("Leaderboard")

    # Top 5
    top5 = rows[:5]
    leaderboard_data = []
    for i, row in enumerate(top5, start=1):
        username = row["email"].replace("@woodland.on.ca", "")
        leaderboard_data.append({"Rank": i, "Name": username, "Laps": row["laps"]})
    st.table(leaderboard_data)

    # Current user stats
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
