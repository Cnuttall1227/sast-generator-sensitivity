import os
from datetime import date
from urllib.parse import urlencode

import streamlit as st
import streamlit.components.v1 as components

ORGANIZATION = os.environ.get("CERT_ORG", "Northside Coding Club")
COURSES = {
    "py101": "Introduction to Python",
    "web201": "Building Web Apps",
    "data150": "Data Analysis with pandas",
}
SIGNATORY = os.environ.get("CERT_SIGNATORY", "Program Director")

st.set_page_config(page_title="Certificate maker", layout="centered")

CERT_STYLE = """
body { margin: 0; font-family: Georgia, serif; background: #f6f3ea; }
.cert { margin: 1rem; padding: 2.5rem; border: 10px double #8a6d3b; background: #fffdf6; text-align: center; }
.cert h1 { letter-spacing: .15em; font-size: 1.6rem; margin: 0 0 1rem; color: #5a4520; }
.cert .name { font-size: 2.2rem; margin: 1rem 0; font-style: italic; }
.cert .course { font-size: 1.2rem; }
.cert .footer { display: flex; justify-content: space-between; margin-top: 2.5rem; font-size: .9rem; }
.cert .note { color: #555; margin-top: 1rem; }
"""


def build_certificate_html(recipient, course_title, completed_on, note):
    note_html = f'<p class="note">{note}</p>' if note else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CERT_STYLE}</style></head>
<body><div class="cert">
<h1>CERTIFICATE OF COMPLETION</h1>
<p>This certifies that</p>
<p class="name">{recipient}</p>
<p>has successfully completed</p>
<p class="course">{course_title}</p>
{note_html}
<div class="footer"><span>{completed_on:%d %B %Y}</span><span>{SIGNATORY}, {ORGANIZATION}</span></div>
</div>
<script>
  document.title = "Certificate";
</script>
</body></html>"""


def read_shared_params():
    params = st.query_params
    course = params.get("course", "py101")
    if course not in COURSES:
        course = "py101"
    try:
        completed = date.fromisoformat(params.get("date", date.today().isoformat()))
    except ValueError:
        completed = date.today()
    return {
        "name": params.get("name", "")[:80],
        "course": course,
        "date": completed,
        "note": params.get("note", "")[:200],
    }


def share_link(values):
    query = urlencode({
        "name": values["name"],
        "course": values["course"],
        "date": values["date"].isoformat(),
        "note": values["note"],
    })
    return f"?{query}"


def main():
    st.title("Certificate maker")
    st.caption(f"Issue completion certificates for {ORGANIZATION} courses.")
    shared = read_shared_params()

    with st.form("certificate"):
        name = st.text_input("Recipient name", value=shared["name"], max_chars=80)
        course = st.selectbox(
            "Course",
            options=list(COURSES),
            index=list(COURSES).index(shared["course"]),
            format_func=lambda key: COURSES[key],
        )
        completed = st.date_input("Completed on", value=shared["date"])
        note = st.text_input("Optional note (e.g. 'with distinction')", value=shared["note"], max_chars=200)
        submitted = st.form_submit_button("Preview certificate")

    values = {"name": name.strip(), "course": course, "date": completed, "note": note.strip()}
    if submitted:
        st.query_params.update({
            "name": values["name"], "course": values["course"],
            "date": values["date"].isoformat(), "note": values["note"],
        })

    if not values["name"]:
        st.info("Enter a recipient name to see the certificate, or open a shared certificate link.")
        return

    components.html(
        build_certificate_html(values["name"], COURSES[values["course"]], values["date"], values["note"]),
        height=520,
        scrolling=False,
    )
    st.write("Share this certificate:")
    st.code(share_link(values), language=None)
    st.caption("Use your browser's print dialog on the preview to save it as a PDF.")


main()