from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import os
import pandas as pd
import io
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone, timedelta

# Timezone and Selection Window
IST = timezone(timedelta(hours=5, minutes=30))
SELECTION_START = datetime(2025, 8, 2, 18, 0, tzinfo=IST)
SELECTION_DEADLINE = datetime(2025, 8, 4, 18, 0, tzinfo=IST)

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "default_secret")

# Firebase Initialization
cred = credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin@treamis.org")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin@2025")

@app.route('/')
def home():
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        user_type = request.form.get("role")

        if not user_type:
            return render_template("login.html", error="Please select a role.")

        if user_type == "student":
            students = db.collection("students").where("email", "==", email).stream()
            for student in students:
                student_data = student.to_dict()
                if student_data["password"] == password:
                    session["student_id"] = student.id
                    return redirect(url_for("student_dashboard"))
            return render_template("login.html", error="Invalid student credentials.")

        elif user_type == "admin":
            if email == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                session["admin"] = True
                return redirect(url_for("admin_dashboard"))
            else:
                return render_template("login.html", error="Invalid admin credentials.")
        else:
            return render_template("login.html", error="Invalid role selected.")

    return render_template("login.html")

@app.route('/admin')
def admin_dashboard():
    if 'admin' not in session:
        return redirect(url_for('home'))
    return render_template('admin.html')

@app.route('/upload_students', methods=['POST'])
def upload_students():
    if 'admin' not in session:
        return redirect(url_for('home'))

    file = request.files['students_file']
    if file and file.filename.endswith('.xlsx'):
        df = pd.read_excel(file)
        df.columns = df.columns.str.strip()

        for _, row in df.iterrows():
            student_id = str(row['StudentID']).strip()
            data = {
                'name': row['StudentName'],
                'email': row['EmailID'],
                'grade': row['GradeSection'],
                'password': str(row['Password']),
                'selected_club': ''
            }
            db.collection("students").document(student_id).set(data)
        flash("Student data uploaded successfully", "success")
    else:
        flash("Invalid file. Please upload a .xlsx file.", "error")
    return redirect(url_for('admin_dashboard'))

@app.route('/upload_clubs', methods=['POST'])
def upload_clubs():
    if 'admin' not in session:
        return redirect(url_for('home'))

    file = request.files['clubs_file']
    if file and file.filename.endswith('.xlsx'):
        df = pd.read_excel(file)
        df.columns = df.columns.str.strip()

        for _, row in df.iterrows():
            club_id = str(row['ClubID']).strip()
            data = {
                'name': row['ClubName'],
                'description': row['Description'],
                'max_members': int(row['MaxMembers']),
                'selected_students': []
            }
            db.collection("clubs").document(club_id).set(data)
        flash("Club data uploaded successfully", "success")
    else:
        flash("Invalid file. Please upload a .xlsx file.", "error")
    return redirect(url_for('admin_dashboard'))

@app.route('/clear_club_selections')
def clear_selections():
    if 'admin' not in session:
        return redirect(url_for('home'))

    for student in db.collection("students").stream():
        db.collection("students").document(student.id).update({'selected_club': ''})
    for club in db.collection("clubs").stream():
        db.collection("clubs").document(club.id).update({'selected_students': []})

    flash("All club selections have been cleared.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/clear_all_data')
def clear_all_data():
    if 'admin' not in session:
        return redirect(url_for('home'))

    for student in db.collection("students").stream():
        db.collection("students").document(student.id).delete()
    for club in db.collection("clubs").stream():
        db.collection("clubs").document(club.id).delete()

    flash("All student and club data has been deleted.", "warning")
    return redirect(url_for('admin_dashboard'))

@app.route('/download_all_students')
def download_all_students():
    if 'admin' not in session:
        return redirect(url_for('home'))

    students_raw = db.collection("students").stream()
    clubs_raw = {doc.id: doc.to_dict() for doc in db.collection("clubs").stream()}

    data = []
    for doc in students_raw:
        s = doc.to_dict()
        club_name = clubs_raw[s['selected_club']]['name'] if s.get('selected_club') in clubs_raw else ''
        grade = s.get('grade', '')
        data.append({
            'Student ID': doc.id,
            'Name': s['name'],
            'Grade': grade,
            'Club': club_name or '—'
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="Selections")
    output.seek(0)

    return send_file(output, as_attachment=True, download_name="student_selections.xlsx",
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/clubs', methods=['GET', 'POST'])
def choose_club():
    if 'student_id' not in session:
        return redirect(url_for('home'))

    now = datetime.now(IST)
    if now < SELECTION_START:
        flash("Club selection has not opened yet.", "info")
        return redirect(url_for('student_dashboard'))
    if now > SELECTION_DEADLINE:
        flash("Club selection is closed.", "error")
        return redirect(url_for('student_dashboard'))

    student_id = session['student_id']
    student_ref = db.collection('students').document(student_id)
    student = student_ref.get().to_dict()

    if request.method == 'POST':
        new_club_id = request.form['club_id']
        new_club_ref = db.collection("clubs").document(new_club_id)
        new_club = new_club_ref.get().to_dict()

        if not new_club:
            flash("Selected club not found.", "error")
            return redirect(url_for("choose_club"))

        prev_club_id = student.get("selected_club")
        if prev_club_id and prev_club_id != new_club_id:
            prev_club_ref = db.collection("clubs").document(prev_club_id)
            prev_club = prev_club_ref.get().to_dict()
            if prev_club and student_id in prev_club.get("selected_students", []):
                prev_students = prev_club["selected_students"]
                prev_students.remove(student_id)
                prev_club_ref.update({"selected_students": prev_students})

        current_students = new_club.get("selected_students", [])
        if len(current_students) >= new_club["max_members"]:
            flash("The selected club is full. Please choose another one.", "error")
            return redirect(url_for("choose_club"))

        if student_id not in current_students:
            current_students.append(student_id)
            new_club_ref.update({"selected_students": current_students})
            student_ref.update({"selected_club": new_club_id})
            flash("Club changed successfully!", "success")

        return redirect(url_for("choose_club"))

    clubs = {
        doc.id: {
            **doc.to_dict(),
            "id": doc.id,
            "member_count": len(doc.to_dict().get("selected_students", []))
        }
        for doc in db.collection("clubs").stream()
    }

    return render_template(
        'club_selection.html',
        student=student,
        student_id=student_id,
        clubs=clubs,
        selection_start=SELECTION_START,
        selection_deadline=SELECTION_DEADLINE,
        current_time=now
    )

@app.route('/student_dashboard')
def student_dashboard():
    if 'student_id' not in session:
        return redirect(url_for('home'))

    student_id = session['student_id']
    student = db.collection("students").document(student_id).get().to_dict()
    clubs = {doc.id: doc.to_dict() for doc in db.collection("clubs").stream()}

    return render_template('student_dashboard.html',
                           name=student['name'],
                           email=student['email'],
                           student_id=student_id,
                           grade_section=student['grade'],
                           selected_club=clubs[student['selected_club']]['name'] if student.get('selected_club') else None,
                           selection_start=SELECTION_START,
                           selection_deadline=SELECTION_DEADLINE,
                           current_time=datetime.now(IST))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))
