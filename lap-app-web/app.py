# requirements.txt must include:
#   streamlit
#   supabase
#   streamlit-js-eval

import hashlib
import streamlit as st
from supabase import create_client
import streamlit_js_eval
print(streamlit_js_eval.__version__)

# ============================================================
#  CHECKPOINT COORDINATES — EDIT THESE TO CHANGE THE ROUTE
# ============================================================
# Each entry is [latitude, longitude] in decimal degrees.
# To find coordinates: open Google Maps, right-click any spot,
# and copy the numbers shown (latitude first, longitude second).
#
CP1 = [43.540951, -80.255961]   # ← Checkpoint 1   [lat, lon]
CP2 = [43.541119, -80.256094]   # ← Checkpoint 2   [lat, lon]
CP3 = [43.541163, -80.256000]   # ← Checkpoint 3   [lat, lon]
CP4 = [43.5410022, -80.255871]   # ← Checkpoint 4   [lat, lon]

# How close (in degrees) the user must be to trigger a checkpoint.
# 0.0002° ≈ 22 metres.  Raise (e.g. 0.0005 ≈ 55 m) if triggers are too strict.
CHECKPOINT_RADIUS = 0.0001
# ============================================================


# --- GPS library -------------------------------------------
# pip install streamlit-js-eval   (add to requirements.txt)
#
# Both branches are imported here so the names are always defined.
# If the library is missing, stubs are used and _LOC_OK = False;
# get_location() will show an error instead of crashing.
try:
    from streamlit_js_eval import get_geolocation as _get_geo
    from streamlit_js_eval import streamlit_js_eval as _js_eval
    _LOC_OK = True
except ImportError:
    # Stubs — only reached when streamlit-js-eval is not installed.
    # get_location() guards _LOC_OK before calling either helper,
    # so these will never actually execute.
    def _get_geo(*args, **kwargs): return None   # noqa: E704
    def _js_eval(*args, **kwargs): return None   # noqa: E704
    _LOC_OK = False


# --- Supabase client ----------------------------------------

@st.cache_resource
def get_client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# --- Session-state defaults ---------------------------------

for _k, _v in {
    "page":       "signin",
    "user_email": None,
    "cp1_done":   False,
    "cp2_done":   False,
    "cp3_done":   False,
    "cp4_done":   False,
    "lap_notice": None,   # success message for completed lap  (survives rerun)
    "cp_notice":  None,   # success message for a checkpoint   (survives rerun)
    "geo_req":    0,      # incremented to force a fresh GPS fix
    "user_agent": None,   # cached browser UA string
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

_CP_KEYS  = ["cp1_done", "cp2_done", "cp3_done", "cp4_done"]
_CP_NAMES = ["Checkpoint 1", "Checkpoint 2", "Checkpoint 3", "Checkpoint 4"]


# --- Device detection ---------------------------------------

def _ua() -> str:
    """Return browser user-agent, fetched once per session via JS."""
    if st.session_state.user_agent is None and _LOC_OK:
        raw = _js_eval(js_expressions="navigator.userAgent", key="ua_str")
        if raw:
            st.session_state.user_agent = str(raw)
    return st.session_state.user_agent or ""


# --- Platform-specific location helpers --------------------

def _loc_ios(key: str):
    """
    iPhone / iPad:
    Uses streamlit_js_eval's built-in get_geolocation(), which wraps
    iOS Safari's WebKit Geolocation API.
    Returns [lat, lon] or None.
    """
    loc = _get_geo(key=key)
    if loc and "coords" in loc:
        return [loc["coords"]["latitude"], loc["coords"]["longitude"]]
    return None


def _loc_android(key: str):
    """
    Android / desktop Chrome:
    Calls navigator.geolocation.getCurrentPosition() directly via a
    raw JavaScript Promise evaluated by streamlit_js_eval.
    Returns [lat, lon] or None.
    """
    result = _js_eval(
        js_expressions=(
            "await new Promise(function(resolve) {"
            "  if (!navigator.geolocation) { resolve(null); return; }"
            "  navigator.geolocation.getCurrentPosition("
            "    function(p) { resolve({lat: p.coords.latitude, lon: p.coords.longitude}); },"
            "    function()  { resolve(null); },"
            "    {enableHighAccuracy: true, timeout: 10000, maximumAge: 0}"
            "  );"
            "})"
        ),
        key=key,
    )
    if result and "lat" in result:
        return [result["lat"], result["lon"]]
    return None


def get_location(key: str = "geo_0"):
    """
    Returns [latitude, longitude] for the current device, or None on failure.
    Pass a unique `key` each time you need a fresh GPS fix.
    Automatically selects the iOS-specific or Android/generic JS path.
    """
    if not _LOC_OK:
        st.error(
            "**streamlit-js-eval** not found — GPS tracking is disabled.  "
            "Add `streamlit-js-eval` to your requirements.txt and redeploy."
        )
        return None

    ua = _ua()
    if "iPhone" in ua or "iPad" in ua:
        return _loc_ios(key)
    return _loc_android(key)


def _near(loc, checkpoint) -> bool:
    """True if loc is within CHECKPOINT_RADIUS of checkpoint."""
    return (
        abs(loc[0] - checkpoint[0]) < CHECKPOINT_RADIUS
        and abs(loc[1] - checkpoint[1]) < CHECKPOINT_RADIUS
    )


# --- Lap helper --------------------------------------------

def _complete_lap():
    """Increment DB lap count, stash a success notice, reset all checkpoints."""
    data = (
        get_client()
        .table("accounts")
        .select("laps")
        .eq("email", st.session_state.user_email)
        .execute()
        .data
    )
    if data:
        new_laps = data[0]["laps"] + 1
        get_client().table("accounts").update({"laps": new_laps}).eq(
            "email", st.session_state.user_email
        ).execute()
        st.session_state.lap_notice = (
            f"Lap complete!  You now have **{new_laps}** lap(s)."
        )
    for k in _CP_KEYS:
        st.session_state[k] = False


# --- Page: Sign In -----------------------------------------

def show_signin():
    st.title("Lap App — Sign In")
    email    = st.text_input("Email")
    password = st.text_input("Password", type="password")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Sign In", use_container_width=True):
            if not email or not password:
                st.error("Please enter your email and password.")
                return
            result = (
                get_client()
                .table("accounts")
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


# --- Page: Sign Up -----------------------------------------

def show_signup():
    print("signup page")
    st.title("Lap App — Create Account")
    email    = st.text_input("Email")
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
            if client.table("accounts").select("email").eq("email", email).execute().data:
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


# --- Page: Leaderboard / Home ------------------------------

def show_home():
    print("home page")
    rows = (
        get_client()
        .table("accounts")
        .select("email, laps")
        .order("laps", desc=True)
        .execute()
        .data
    )

    st.title("Leaderboard u idiot")
    st.table(
        [
            {
                "Rank": i,
                "Name": r["email"].replace("@woodland.on.ca", ""),
                "Laps": r["laps"],
            }
            for i, r in enumerate(rows[:5], start=1)
        ]
    )

    st.divider()
    st.subheader("Your Stats")
    email = st.session_state.user_email
    rank  = next((i + 1 for i, r in enumerate(rows) if r["email"] == email), None)
    laps  = next((r["laps"] for r in rows if r["email"] == email), 0)
    name  = email.replace("@woodland.on.ca", "")
    st.table([{"Rank": rank or "—", "Name": name, "Laps": laps}])

    st.divider()

    print("Reached button section") # ----------------------------------------------------------

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Start Tracking", use_container_width=True):
            st.session_state.page = "tracking"
            st.rerun()
    with col2:
        if st.button("Sign Out", use_container_width=True):
            st.session_state.user_email = None
            st.session_state.page = "signin"
            st.rerun()


# --- Page: Tracking ----------------------------------------

def show_tracking():
    CHECKPOINTS = [CP1, CP2, CP3, CP4]

    st.title("Lap Tracker")

    # ---- Persistent notices (survive st.rerun) -------------
    if st.session_state.lap_notice:
        st.success(st.session_state.lap_notice)
        st.balloons()
        st.session_state.lap_notice = None
    if st.session_state.cp_notice:
        st.success(st.session_state.cp_notice)
        st.session_state.cp_notice = None

    # ---- Checkpoint status grid ----------------------------
    cols = st.columns(4)
    for col, key, name in zip(cols, _CP_KEYS, _CP_NAMES):
        with col:
            if st.session_state[key]:
                st.success(f"Y: {name}")
            else:
                st.info(f"N: {name}")

    next_idx = next((i for i, k in enumerate(_CP_KEYS) if not st.session_state[k]), None)
    if next_idx is not None:
        st.caption(f"Head to **{_CP_NAMES[next_idx]}** next.")

    st.divider()

    # ---- Live GPS (fetched at render time; counter-keyed) --
    # geo_req increments after each successful checkpoint to
    # ensure a fresh fix is obtained for the next one.
    geo_key  = f"geo_{st.session_state.geo_req}"
    location = get_location(key=geo_key) if _LOC_OK else None

    if location:
        st.caption(f"{location[0]:.6f}°,  {location[1]:.6f}°")
    elif _LOC_OK:
        st.caption("Fetching GPS… (allow location access when prompted)")
    else:
        st.warning("Install **streamlit-js-eval** to enable GPS tracking.")

    # ---- Action buttons ------------------------------------
    col_check, col_refresh = st.columns(2)

    with col_check:
        if st.button("I'm at a Checkpoint", use_container_width=True, type="primary"):
            if location is None:
                st.error("No location yet — wait a moment or tap Refresh GPS.")
            elif next_idx is None:
                st.info("All checkpoints already hit for this lap!")
            elif _near(location, CHECKPOINTS[next_idx]):
                st.session_state[_CP_KEYS[next_idx]] = True
                if all(st.session_state[k] for k in _CP_KEYS):
                    _complete_lap()
                else:
                    st.session_state.cp_notice = f"🎯 {_CP_NAMES[next_idx]} reached!"
                st.session_state.geo_req += 1   # fresh fix for next checkpoint
                st.rerun()
            else:
                st.warning(
                    f"Not at {_CP_NAMES[next_idx]} yet — keep going!  "
                    f"(Your position: {location[0]:.5f}°, {location[1]:.5f}°)"
                )

    with col_refresh:
        if st.button("Refresh GPS", use_container_width=True):
            st.session_state.geo_req += 1
            st.rerun()

    st.divider()
    col_home, col_reset = st.columns(2)
    with col_home:
        if st.button("Leaderboard", use_container_width=True):
            st.session_state.page = "home"
            st.rerun()
    with col_reset:
        if st.button("↩ Reset Checkpoints", use_container_width=True):
            for k in _CP_KEYS:
                st.session_state[k] = False
            st.rerun()


# --- Router ------------------------------------------------

_p = st.session_state.page

if _p == "signin":
    show_signin()
elif _p == "signup":
    show_signup()
elif _p in ("home", "tracking"):
    if st.session_state.user_email is None:
        st.session_state.page = "signin"
        st.rerun()
    elif _p == "home":
        show_home()
    else:
        show_tracking()
