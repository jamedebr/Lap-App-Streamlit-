import hashlib
import streamlit as st
from supabase import create_client

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
