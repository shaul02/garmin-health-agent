"""Garmin Health Agent — personal health & training dashboard.

Run locally:  streamlit run app.py
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from ai_agent import RulesBackend, get_agent
from analysis import sleep_debt, training_readiness_verdict, trend, weekly_load
from garmin_client import GarminData

st.set_page_config(page_title="סוכן בריאות ואימונים", page_icon="🏃", layout="wide")

# Keep the CSS light: only right-align the main content. A broad `direction: rtl`
# on .stApp / the sidebar leaves repaint trails ("smearing") during Streamlit's
# sidebar-collapse animation. Hebrew still renders right-to-left on its own.
st.markdown(
    """
    <style>
      section[data-testid="stMain"] .block-container { text-align: right; }
    </style>
    """,
    unsafe_allow_html=True,
)

HE_TREND = {"rising": "עולה", "falling": "יורדת", "stable": "יציבה", "unknown": "לא ידועה"}


@st.cache_resource
def _garmin() -> GarminData:
    g = GarminData()
    g.try_resume()
    return g


@st.cache_data(ttl=900, show_spinner="מושך נתונים מ-Garmin…")
def _load(_g: GarminData, day: str):
    snap = _g.wellness_snapshot(day)
    hist = _g.history(days=14, end=day)
    acts = _g.recent_activities(limit=12)
    try:
        sync = _g.last_sync_time()
    except Exception:  # noqa: BLE001
        sync = None
    return snap, hist, acts, sync


def _fmt(v, unit="", prefix=False):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if isinstance(v, float):
        v = round(v, 1)
    if prefix and unit:
        return f"{unit} {v}"
    return f"{v} {unit}".strip()


def _delta(cur, base):
    if cur is None or base is None:
        return None
    return f"{round(cur - base, 1):+g}"


def _spark(dates, values, title, color):
    fig = go.Figure(go.Scatter(x=list(dates), y=list(values), mode="lines+markers",
                               line=dict(color=color)))
    fig.update_layout(title=title, height=210, showlegend=False,
                      margin=dict(l=10, r=10, t=40, b=10))
    return fig


def _auth_gate(g: GarminData) -> bool:
    if g.connected:
        return True
    st.info("נדרשת התחברות ל-Garmin Connect פעם אחת. הסיסמה אינה נשמרת — רק אסימון גישה מקומי.")
    with st.form("login"):
        email = st.text_input("אימייל Garmin", value=config.GARMIN_EMAIL or "")
        password = st.text_input("סיסמה", type="password")
        submitted = st.form_submit_button("התחבר")
    if submitted and email and password:
        try:
            state = g.begin_login(email, password)
        except Exception as e:  # noqa: BLE001
            st.error(f"התחברות נכשלה: {e}")
            return False
        if state == "mfa":
            st.session_state["awaiting_mfa"] = True
        else:
            st.rerun()
    if st.session_state.get("awaiting_mfa"):
        code = st.text_input("קוד אימות דו־שלבי (MFA)")
        if st.button("אשר קוד") and code:
            try:
                g.complete_mfa(code)
                st.session_state.pop("awaiting_mfa", None)
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"קוד שגוי: {e}")
    return False


def _run_agent(method: str, agent, *args):
    try:
        return getattr(agent, method)(*args)
    except Exception as e:  # noqa: BLE001
        return (f"_מנוע ה-AI נכשל ({e}) — הצגת ניתוח כללים:_\n\n"
                + getattr(RulesBackend(), method)(*args))


def main():
    g = _garmin()
    st.title("🏃 סוכן בריאות ואימונים אישי")
    if not _auth_gate(g):
        st.stop()

    with st.sidebar:
        st.header("הגדרות")
        day = st.date_input("תאריך", value=dt.date.today(), max_value=dt.date.today())
        provider = st.selectbox(
            "מנוע AI",
            ["(אוטומטי)", "rules", "gemini", "claude", "openai", "ollama"],
            help="'rules' עובד בלי מפתח API. השאר דורשים מפתח ב-secrets.",
        )
        if st.button("🔄 רענן עכשיו"):
            _load.clear()
        st.caption(f"מנוע ברירת מחדל: {config.effective_provider()}")

    day_s = day.isoformat()
    try:
        snap, hist, acts, sync = _load(g, day_s)
    except Exception as e:  # noqa: BLE001
        st.error(f"שגיאה בשליפת נתונים מ-Garmin: {e}")
        st.stop()

    if sync:
        age_min = (dt.datetime.now() - sync).total_seconds() / 60
        if age_min > 90:
            st.caption(f"סנכרון אחרון מהשעון: {sync:%Y-%m-%d %H:%M} (לפני {age_min / 60:.1f} שעות)")
        else:
            st.caption(f"סנכרון אחרון מהשעון: {sync:%H:%M} (לפני {age_min:.0f} דקות)")

    verdict = training_readiness_verdict(snap, config.SLEEP_TARGET_HOURS)

    banner = {"hard": st.success, "moderate": st.info,
              "easy": st.warning, "rest": st.error}[verdict.level]
    banner(f"**המלצת היום:** {verdict.headline}")
    with st.expander("למה?", expanded=True):
        for r in verdict.reasons:
            st.write(f"- {r}")

    m = st.columns(5)
    m[0].metric("HRV אתמול", _fmt(snap.get("hrv_last_night"), "ms"),
                _delta(snap.get("hrv_last_night"), snap.get("hrv_7d_avg")))
    m[1].metric("שינה", _fmt(snap.get("sleep_hours"), "ש'"),
                _fmt(snap.get("sleep_score"), "ציון", prefix=True))
    m[2].metric("Body Battery", _fmt(snap.get("body_battery_now")))
    m[3].metric("דופק מנוחה", _fmt(snap.get("resting_hr"), "bpm"),
                _delta(snap.get("resting_hr"), snap.get("resting_hr_7d_avg")),
                delta_color="inverse")
    m[4].metric("סטרס ממוצע", _fmt(snap.get("stress_avg")))

    sel = None if provider == "(אוטומטי)" else provider
    agent = get_agent(sel)
    if getattr(agent, "init_error", None):
        st.warning(f"מנוע AI לא זמין ({agent.init_error}) — עברתי ל-rules.")

    st.subheader("סיכום בוקר")
    with st.spinner("מנתח…"):
        st.markdown(_run_agent("brief", agent, snap, hist, acts))

    st.subheader("שאל את הסוכן")
    q = st.text_input("שאלה חופשית", placeholder="כדאי לי לרוץ היום? מה מצב ה-HRV שלי?")
    if q:
        with st.spinner("חושב…"):
            st.markdown(_run_agent("ask", agent, q, snap, hist, acts))

    st.subheader("מגמות (14 ימים)")
    hdf = pd.DataFrame(hist)
    if not hdf.empty:
        t = st.columns(3)
        t[0].plotly_chart(_spark(hdf["date"], hdf["hrv_last_night"], "HRV לילי", "#1976d2"),
                          use_container_width=True)
        t[1].plotly_chart(_spark(hdf["date"], hdf["sleep_hours"], "שעות שינה", "#6a1b9a"),
                          use_container_width=True)
        t[2].plotly_chart(_spark(hdf["date"], hdf["resting_hr"], "דופק מנוחה", "#c62828"),
                          use_container_width=True)
        sl = [x for x in hdf["sleep_hours"].tolist() if pd.notna(x)]
        hv = [x for x in hdf["hrv_last_night"].tolist() if pd.notna(x)]
        st.caption(
            f"מגמת HRV: {HE_TREND[trend(hv)]}  ·  "
            f"חוב שינה מצטבר: {sleep_debt(sl, config.SLEEP_TARGET_HOURS)} שעות"
        )

    st.subheader("אימונים אחרונים")
    adf = pd.DataFrame(acts)
    if not adf.empty:
        load = weekly_load(acts)
        if load["flag"]:
            st.warning(load["flag"])
        st.caption(f"עומס אימונים: 7 ימים אחרונים {load['this_week']}  ·  "
                   f"7 שלפניהם {load['prev_week']}  ·  יחס {load['ratio']}")
        cols = [c for c in ["date", "type", "distance_km", "duration_min",
                            "avg_hr", "training_load", "aerobic_te"] if c in adf.columns]
        st.dataframe(adf[cols], hide_index=True, use_container_width=True)

    st.divider()
    st.caption("נתונים דרך Garmin Connect (API לא רשמי). המלצות כלליות לכושר, לא ייעוץ רפואי.")


if __name__ == "__main__":
    main()
