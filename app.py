from flask import Flask, render_template, request, redirect, url_for, session, Response
import firebase_admin
from firebase_admin import credentials, firestore
import csv
import io

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with your own secure secret

# Initialize Firebase
cred = credentials.Certificate("firebase_key.json")  # Path to your Firebase service account key
firebase_admin.initialize_app(cred)
db = firestore.client()

STUDENTS_COLLECTION = 'students'
CLUBS_COLLECTION = 'clubs'


@app.route('/')
def home():
    return redirect(url_for('login'))


# ---------------- STUDENT LOGIN ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        student_id = request.form['student_id'].strip()
        password = request.form['password'].strip()

        student_ref = db.collection(STUDENTS_COLLECTION).document(student_id)
        doc = student_ref.get()

        if doc.exists:
            student_data = doc.to_dict()
            if student_data.get('password') == password:
                session['student_id'] = student_id
                return redirect(url_for('clubs'))
            else:
                error = 'Incorrect password.'
        else:
            error = 'Student ID not found.'

    return render_template('login.html', error=error)


# ---------------- STUDENT CLUB SELECTION ----------------
@app.route('/clubs', methods=['GET', 'POST'])
def clubs():
    if 'student_id' not in session:
        return redirect(url_for('login'))

    student_id = session['student_id']
    student_ref = db.collection(STUDENTS_COLLECTION).document(student_id)
    student_data = student_ref.get().to_dict()

    clubs_query = db.collection(CLUBS_COLLECTION).stream()
    clubs = []
    for c in clubs_query:
        club_data = c.to_dict()
        club_data['id'] = c.id
        club_data['members'] = club_data.get('members', [])
        clubs.append(club_data)

    message = None

    if request.method == 'POST':
        club_id = request.form.get('club_id')
        action = request.form.get('action')

        selected_club_ref = db.collection(CLUBS_COLLECTION).document(club_id)
        selected_club = selected_club_ref.get().to_dict()
        selected_club['members'] = selected_club.get('members', [])

        if action == 'join':
            if student_data.get('club_id') and student_data['club_id'] != club_id:
                message = "❌ You already joined a different club. Please leave it first."
            elif student_id in selected_club['members']:
                message = "⚠️ You are already in this club."
            elif len(selected_club['members']) >= selected_club['max_members']:
                message = "❌ This club is full!"
            else:
                selected_club['members'].append(student_id)
                selected_club_ref.update({'members': selected_club['members']})
                student_ref.update({'club_id': club_id})
                student_data['club_id'] = club_id
                message = f"✅ Joined {selected_club['name']}."

        elif action == 'leave':
            if student_data.get('club_id') != club_id:
                message = "❌ You are not in this club."
            else:
                if student_id in selected_club['members']:
                    selected_club['members'].remove(student_id)
                    selected_club_ref.update({'members': selected_club['members']})
                student_ref.update({'club_id': firestore.DELETE_FIELD})
                student_data['club_id'] = None
                message = f"✅ You have left {selected_club['name']}."

    return render_template('clubs.html', student_id=student_id, student=student_data, clubs=clubs, message=message)


# ---------------- LOGOUT ----------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------- ADMIN DASHBOARD ----------------
@app.route('/admin')
def admin():
    students = db.collection(STUDENTS_COLLECTION).stream()
    clubs = {doc.id: doc.to_dict().get('name') for doc in db.collection(CLUBS_COLLECTION).stream()}

    student_data = []
    for s in students:
        data = s.to_dict()
        student_data.append({
            'student_id': s.id,
            'name': data.get('name', ''),
            'grade': data.get('grade', ''),
            'club': clubs.get(data.get('club_id'), 'Not Joined')
        })

    # Sort by student_id
    student_data.sort(key=lambda x: x['student_id'])

    return render_template('admin.html', students=student_data)


# ---------------- EXPORT CSV ----------------
@app.route('/admin/export')
def export_csv():
    students = db.collection(STUDENTS_COLLECTION).stream()
    clubs = {doc.id: doc.to_dict().get('name') for doc in db.collection(CLUBS_COLLECTION).stream()}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Student ID', 'Name', 'Grade', 'Club'])

    for s in students:
        data = s.to_dict()
        writer.writerow([
            s.id,
            data.get('name', ''),
            data.get('grade', ''),
            clubs.get(data.get('club_id'), 'Not Joined')
        ])

    output.seek(0)
    return Response(output, mimetype='text/csv',
                    headers={"Content-Disposition": "attachment;filename=students_clubs.csv"})


if __name__ == '__main__':
    app.run(debug=True)
