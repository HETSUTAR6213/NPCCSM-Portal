"""
NPCCSM — Login / Sign-up API
-----------------------------------------------------------------
Reads and writes rows in your Google Sheet to authenticate Students,
Teachers and the Principal for https://npccsm-syllabus.wuaze.com/

IMPORTANT — read this before deploying:
Your free wuaze.com (InfinityFree-family) hosting only serves static
files and PHP — it cannot run this Python file. Deploy this script on
a Python-capable host (Render, PythonAnywhere, Railway, Fly.io, etc.),
then point login.html (hosted on wuaze.com) at that server's URL.
See DEPLOY_README.md for exact steps.

A plain Google API key can only READ a publicly-shared sheet — it
cannot create new rows, so it can't power sign-up. This script instead
uses a Google **service account**, which can both read and write.
Setup steps are in DEPLOY_README.md.
"""

import os
import re
import json
import hashlib
import datetime

from flask import Flask, request, jsonify
from flask_cors import CORS
import gspread
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# From your sheet's URL: https://docs.google.com/spreadsheets/d/<THIS_PART>/edit
SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID", "1CS-FsLIwIzj4X23U616jf6rHsJGGmHxTbxjK9TKybWs"
)

# The page users get redirected to after a successful login.
REDIRECT_URL = os.environ.get("REDIRECT_URL", "https://npccsm-syllabus.wuaze.com/")

# Where login.html is hosted — used for CORS. Add more origins if needed.
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS", "https://npccsm-syllabus.wuaze.com"
).split(",")

# Service account credentials: either a file path OR the raw JSON contents
# pasted into an environment variable (handy on hosts with no file upload).
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")  # optional

SHEET_STUDENTS = "Students"
SHEET_TEACHERS = "Teachers"
SHEET_PRINCIPAL = "Principal"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS + ["http://localhost:*", "http://127.0.0.1:*"]}})

_gc = None


def get_client():
    """Lazily create and cache the authorized gspread client."""
    global _gc
    if _gc is not None:
        return _gc

    if CREDENTIALS_JSON:
        info = json.loads(CREDENTIALS_JSON)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)

    _gc = gspread.authorize(creds)
    return _gc


def get_sheet(name):
    """Return the worksheet tab, creating it with headers if it doesn't exist."""
    sh = get_client().open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=1000, cols=6)
        headers = (
            ["Timestamp", "EnrollmentNumber", "Name", "Email", "PasswordHash"]
            if name == SHEET_STUDENTS
            else ["Timestamp", "Name", "Email", "PasswordHash"]
        )
        ws.append_row(headers)
    return ws


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def norm(v):
    return str(v or "").strip().lower()


def valid_email(email):
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email or "") is not None


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify(status="ok", message="NPCCSM auth server is running.")


@app.route("/api/signup", methods=["POST"])
def signup():
    body = request.get_json(force=True, silent=True) or {}
    role = body.get("role")
    password = body.get("password") or ""
    email = (body.get("email") or "").strip()
    name = (body.get("name") or "").strip()

    if role not in ("student", "teacher", "principal"):
        return jsonify(status="error", message="Invalid role."), 400
    if len(password) < 4:
        return jsonify(status="error", message="Password must be at least 4 characters."), 400
    if not valid_email(email):
        return jsonify(status="error", message="Enter a valid email address."), 400
    if not name:
        return jsonify(status="error", message="Name is required."), 400

    pw_hash = hash_password(password)
    now = datetime.datetime.utcnow().isoformat()

    try:
        if role == "student":
            enrollment = (body.get("enrollmentNumber") or "").strip()
            if not enrollment:
                return jsonify(status="error", message="Enrollment number is required."), 400

            ws = get_sheet(SHEET_STUDENTS)
            rows = ws.get_all_values()[1:]
            for r in rows:
                if len(r) >= 4 and (norm(r[1]) == norm(enrollment) or norm(r[3]) == norm(email)):
                    return jsonify(status="error", message="An account with this enrollment number or email already exists."), 409
            ws.append_row([now, enrollment, name, email, pw_hash])
        else:
            ws = get_sheet(SHEET_TEACHERS if role == "teacher" else SHEET_PRINCIPAL)
            rows = ws.get_all_values()[1:]
            for r in rows:
                if len(r) >= 3 and norm(r[2]) == norm(email):
                    return jsonify(status="error", message="An account with this email already exists."), 409
            ws.append_row([now, name, email, pw_hash])
    except Exception as exc:  # noqa: BLE001
        return jsonify(status="error", message=f"Server error: {exc}"), 500

    return jsonify(status="success", message="Account created. You can now sign in.")


@app.route("/api/login", methods=["POST"])
def login():
    body = request.get_json(force=True, silent=True) or {}
    role = body.get("role")
    password = body.get("password") or ""
    email = (body.get("email") or "").strip()

    if role not in ("student", "teacher", "principal"):
        return jsonify(status="error", message="Invalid role."), 400

    pw_hash = hash_password(password)

    try:
        if role == "student":
            enrollment = (body.get("enrollmentNumber") or "").strip()
            ws = get_sheet(SHEET_STUDENTS)
            rows = ws.get_all_values()[1:]
            for r in rows:
                if len(r) >= 5 and norm(r[1]) == norm(enrollment) and norm(r[3]) == norm(email):
                    if r[4] == pw_hash:
                        return jsonify(
                            status="success", role="student", name=r[2],
                            enrollmentNumber=r[1], email=r[3], redirect=REDIRECT_URL,
                        )
                    return jsonify(status="error", message="Incorrect password."), 401
            return jsonify(status="error", message="No student account matches that enrollment number and email."), 404
        else:
            ws = get_sheet(SHEET_TEACHERS if role == "teacher" else SHEET_PRINCIPAL)
            rows = ws.get_all_values()[1:]
            for r in rows:
                if len(r) >= 4 and norm(r[2]) == norm(email):
                    if r[3] == pw_hash:
                        return jsonify(
                            status="success", role=role, name=r[1],
                            email=r[2], redirect=REDIRECT_URL,
                        )
                    return jsonify(status="error", message="Incorrect password."), 401
            return jsonify(status="error", message="No account found with that email."), 404
    except Exception as exc:  # noqa: BLE001
        return jsonify(status="error", message=f"Server error: {exc}"), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
