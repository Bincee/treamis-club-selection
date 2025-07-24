from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import os
import pandas as pd
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import pytz
from io import BytesIO
import math

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "secret123")

# Firebase Admin SDK Initialization
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase_key.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Helper Functions
def is_selection_open():
    deadline_doc = db.collection("config").document("deadline").get()
    if deadline_doc.exists:
        data = deadline_doc.to_dict()
        tz = pytz.timezone("Asia/Kolkata")
        now = datetime.now(tz)
        start = data.get("start_time")
        end = data.get("end_time")
        if start and end:
            return start <= now <= end
    return False

def clean_student_data():
    students_ref = db.collection("students")
    for student in students_ref.stream():
        data = student.to_dict()
        updated = False

        if "StudentName" in data:
            data["Name"] = data.pop("StudentName")
            updated = True

        if "EmailID" in data and isinstance(data["EmailID"], str):
            data["EmailID"] = data["EmailID"].lower().strip()
            updated = True

        if "Password" in data and isinstance(data["Password"], str):
            try:
                data["Password"] = int(data["Password"])
                updated = True
            except ValueError:
                pass

        keys_to_remove = [k for k in data
                         if (isinstance(data[k], float) and math.isnan(data[k]))
                         or str(k).startswith('Unnamed')]

        if keys_to_remove:
            for key in keys_to_remove:
                del data[key]
            updated = True

        if updated:
            students_ref.document(student.id).set(data)
            print(f"Updated student {student.id}")

# Routes
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/club_selection', methods=["GET", "POST"])
def club_selection():
    student_id = session.get("student_id")
    if not student_id:
        return redirect(url_for("login"))

    student = db.collection("students").document(student_id).get()
    if not student.exists:
        return redirect(url_for("logout"))

    if not is_selection_open():
        flash("Selection window is closed.", "error")
        return redirect(url_for("student_dashboard"))

    deadline_doc = db.collection("config").document("deadline").get()
    deadline = deadline_doc.to_dict().get("end_time") if deadline_doc.exists else None

    if request.method == "POST":
        club_id = request.form.get("club_id")
        previous_selection = student.to_dict().get("SelectedClub")

        if not club_id:
            if previous_selection:
                prev_club_ref = db.collection("clubs").document(previous_selection)
                prev_club = prev_club_ref.get()
                if prev_club.exists:
                    prev_data = prev_club.to_dict()
                    current = prev_data.get("CurrentMembers", 0)
                    prev_club_ref.update({
                        "CurrentMembers": max(0, current - 1)
                    })
            db.collection("students").document(student_id).update({
                "SelectedClub": firestore.DELETE_FIELD
            })
            flash("Club selection removed.", "success")
            return redirect(url_for("student_dashboard"))

        club_ref = db.collection("clubs").document(club_id)
        club_doc = club_ref.get()
        if not club_doc.exists:
            flash("Selected club does not exist.", "error")
            return redirect(url_for("club_selection"))

        if previous_selection and previous_selection != club_id:
            prev_club_ref = db.collection("clubs").document(previous_selection)
            prev_club = prev_club_ref.get()
            if prev_club.exists:
                prev_data = prev_club.to_dict()
                current = prev_data.get("CurrentMembers", 0)
                prev_club_ref.update({
                    "CurrentMembers": max(0, current - 1)
                })

        current = club_doc.to_dict().get("CurrentMembers", 0)
        club_ref.update({
            "CurrentMembers": current + 1
        })

        db.collection("students").document(student_id).update({
            "SelectedClub": club_id
        })
        flash("Club selected successfully!", "success")
        return redirect(url_for("student_dashboard"))

    clubs = []
    for c in db.collection("clubs").stream():
        data = c.to_dict()
        clubs.append({
            "id": c.id,
            "name": data.get("Name", data.get("ClubName", "")),
            "description": data.get("Description", ""),
            "current_members": data.get("CurrentMembers", 0),
            "max_members": data.get("MaxMembers", 0)
        })

    student_data = student.to_dict()
    selected_club = student_data.get("SelectedClub")

    return render_template("club_selection.html",
        clubs=clubs,
        selected_club=selected_club,
        is_selection_active=is_selection_open(),
        deadline=deadline
    )

# KEEP ALL REMAINING ROUTES THE SAME (as per your working version)
# login, logout, student_dashboard, admin_dashboard, view_results, etc.

# Final run
if __name__ == "__main__":
    clean_student_data()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
