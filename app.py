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

# Firebase Admin SDK Initialization - Only do this once
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
        
        # Standardize field names
        if "StudentName" in data:
            data["Name"] = data.pop("StudentName")
            updated = True
            
        # Clean email format
        if "EmailID" in data and isinstance(data["EmailID"], str):
            data["EmailID"] = data["EmailID"].lower().strip()
            updated = True
            
        # Convert password to number if possible
        if "Password" in data and isinstance(data["Password"], str):
            try:
                data["Password"] = int(data["Password"])
                updated = True
            except ValueError:
                pass
        
        # Remove NaN values and unnamed fields
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
        club_doc = db.collection("clubs").document(club_id).get()
        if not club_doc.exists:
            flash("Selected club does not exist.", "error")
            return redirect(url_for("club_selection"))

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

@app.route('/student_dashboard')
def student_dashboard():
    student_id = session.get("student_id")
    if not student_id:
        return redirect(url_for("login"))

    student = db.collection("students").document(student_id).get()
    if not student.exists:
        return redirect(url_for("logout"))

    student_data = student.to_dict()
    club_id = student_data.get("SelectedClub")

    # Get club information if selected
    selected_club_info = None
    if club_id:
        club_doc = db.collection("clubs").document(club_id).get()
        if club_doc.exists:
            club_data = club_doc.to_dict()
            selected_club_info = {
                "id": club_id,
                "name": club_data.get("Name", club_data.get("ClubName", "Unnamed Club")),
                "description": club_data.get("Description", "")
            }

    # Get deadline info
    deadline_doc = db.collection("config").document("deadline").get()
    deadline = deadline_doc.to_dict().get("end_time") if deadline_doc.exists else None
    deadline_passed = False
    if deadline:
        tz = pytz.timezone("Asia/Kolkata")
        now = datetime.now(tz)
        deadline_passed = now > deadline

    return render_template("student_dashboard.html",
        student={
            "id": student_id,
            "name": student_data.get("Name", student_data.get("StudentName", "Student")),
            "email": student_data.get("EmailID", ""),
            "grade": student_data.get("GradeSection", ""),
            "selected_clubs": [selected_club_info] if selected_club_info else []
        },
        is_selection_open=is_selection_open(),
        deadline=deadline,
        deadline_passed=deadline_passed,
        max_selections=1
    )

@app.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":
        session.pop('_flashes', None)
        
        user_type = request.form.get("user_type")
        user_id = request.form.get("user_id").strip().lower()
        password = request.form.get("password")

        if user_type == "admin":
            if user_id == "admin@treamis.org" and password == "admin@2025":
                session['admin'] = True
                return redirect(url_for('admin_dashboard'))
            flash("Invalid admin credentials", "error")
            return redirect(url_for('login'))

        elif user_type == "student":
            try:
                print(f"Attempting login with email: {user_id}")  # Debug log
                
                # First check if the email is in the correct format
                if '@' not in user_id:
                    flash("Invalid email format", "error")
                    return redirect(url_for('login'))
                
                # For treamis.org emails, keep the dots in the username part
                if user_id.endswith('@treamis.org'):
                    normalized_email = user_id.lower().strip()
                else:
                    # For other domains, you might want different normalization
                    normalized_email = user_id.lower().strip()
                
                print(f"Normalized email: {normalized_email}")  # Debug log
                
                # Query with the exact email
                students_ref = db.collection("students")
                query = students_ref.where("EmailID", "==", normalized_email).limit(1)
                results = list(query.stream())
                
                if results:
                    student = results[0]
                    student_data = student.to_dict()
                    stored_password = str(student_data.get("Password", ""))
                    print(f"Found student: {student.id}")  # Debug log
                    print(f"Stored password: {stored_password}")  # Debug log
                    print(f"Input password: {password}")  # Debug log
                    
                    if stored_password == str(password):
                        session['student_id'] = student.id
                        print("Login successful!")  # Debug log
                        return redirect(url_for('student_dashboard'))
                    else:
                        print("Password mismatch")  # Debug log
                else:
                    print("No student found with this email")  # Debug log
                
                flash("Invalid email or password", "error")
            except Exception as e:
                print(f"Login error: {str(e)}")  # Debug log
                flash("System error during login", "error")
            return redirect(url_for('login'))

    return render_template("login.html")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin', methods=["GET", "POST"])
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('login'))

    action = request.form.get("action")

    if action == "upload":
        student_file = request.files.get("student_file")
        club_file = request.files.get("club_file")

        if student_file and club_file:
            try:
                # Process student file
                student_df = pd.read_excel(student_file)
                for _, row in student_df.iterrows():
                    sid = str(row.iloc[0])
                    data = {k: v for k, v in row.dropna().to_dict().items() 
                           if not str(k).startswith('Unnamed')}
                    
                    # Standardize field names
                    if 'StudentName' in data:
                        data['Name'] = data.pop('StudentName')
                    
                    # Clean email format
                    if 'EmailID' in data and isinstance(data['EmailID'], str):
                        data['EmailID'] = data['EmailID'].lower().strip()
                    
                    db.collection("students").document(sid).set(data)

                # Process club file
                club_df = pd.read_excel(club_file)
                for _, row in club_df.iterrows():
                    cid = str(row.iloc[0])
                    data = {k: v for k, v in row.dropna().to_dict().items() 
                           if not str(k).startswith('Unnamed')}
                    db.collection("clubs").document(cid).set(data)

                flash("Student and Club data uploaded successfully.", "success")
            except Exception as e:
                flash(f"Upload failed: {e}", "error")

    elif action == "set_window":
        start = request.form.get("start_time")
        end = request.form.get("end_time")
        try:
            tz = pytz.timezone("Asia/Kolkata")
            start_dt = datetime.strptime(start, "%Y-%m-%dT%H:%M").astimezone(tz)
            end_dt = datetime.strptime(end, "%Y-%m-%dT%H:%M").astimezone(tz)
            db.collection("config").document("deadline").set({
                "start_time": start_dt,
                "end_time": end_dt
            })
            flash("Selection window updated successfully.", "success")
        except Exception as e:
            flash(f"Failed to set selection window: {e}", "error")


    elif action == "export":
        students = db.collection("students").stream()
        rows = []
        for s in students:
            data = s.to_dict()
        
            # Get club name if selected
            club_name = ""
            selected_club_id = data.get("SelectedClub", "")
            if selected_club_id:
                club_doc = db.collection("clubs").document(selected_club_id).get()
                if club_doc.exists:
                    club_data = club_doc.to_dict()
                    club_name = club_data.get("Name", club_data.get("ClubName", ""))
        
            rows.append({
            "Student ID": s.id,
            "Student Name": data.get("Name", data.get("StudentName", "")),
            "Grade/Section": data.get("GradeSection", ""),
            "Selected Club ID": selected_club_id,
            "Club Name": club_name
            })

        df = pd.DataFrame(rows)
        output = BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)
        return send_file(output, download_name="club_selections.xlsx", as_attachment=True)
    
    

    elif action == "clear":
        students = db.collection("students").stream()
        for s in students:
            db.collection("students").document(s.id).update({"SelectedClub": firestore.DELETE_FIELD})
        flash("All selections cleared.", "success")

    selection_doc = db.collection("config").document("deadline").get()
    selection_start = selection_doc.to_dict().get("start_time") if selection_doc.exists else None
    selection_end = selection_doc.to_dict().get("end_time") if selection_doc.exists else None

    student_count = len(list(db.collection("students").stream()))
    club_count = len(list(db.collection("clubs").stream()))

    return render_template("admin.html",
        selection_start=selection_start,
        selection_end=selection_end,
        is_selection_active=is_selection_open(),
        student_count=student_count,
        club_count=club_count
    )

@app.route('/view_results')
def view_results():
    if not session.get('admin'):
        return redirect(url_for('login'))

    students = db.collection("students").stream()
    selected_by_grade = {}
    not_selected_by_grade = {}

    for s in students:
        data = s.to_dict()

        name = data.get("Name", data.get("StudentName", "Unnamed"))
        email = data.get("EmailID", "N/A")
        grade = data.get("GradeSection", "Unspecified")

        club_id = data.get("SelectedClub")
        if club_id:
            club_doc = db.collection("clubs").document(club_id).get()
            if club_doc.exists:
                club_data = club_doc.to_dict()
                club_name = club_data.get("Name", club_data.get("ClubName", club_id))
            else:
                club_name = "Unknown Club"
            group = selected_by_grade.setdefault(grade, [])
            group.append({
                "StudentID": s.id,
                "Name": name,
                "Email": email,
                "SelectedClub": club_name
            })
        else:
            group = not_selected_by_grade.setdefault(grade, [])
            group.append({
                "StudentID": s.id,
                "Name": name,
                "Email": email,
                "SelectedClub": "Not Selected"
            })

    return render_template("view_results.html", 
        selected_by_grade=selected_by_grade,
        not_selected_by_grade=not_selected_by_grade
    )




if __name__ == "__main__":
    # Run data cleanup when starting the app
    clean_student_data()
    app.run(debug=True)