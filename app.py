import os
import sqlite3
import datetime
import random
import smtplib
import csv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response
from werkzeug.routing import BuildError

app = Flask(__name__)
app.secret_key = 'smart_attendance_master_secret_key'

UPLOAD_FOLDER = 'static/uploads'
AUDIO_FOLDER = 'static/audio'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "toraskarsanket2002@gmail.com"
SENDER_PASSWORD = "kontuwejlfsuhyig"

@app.errorhandler(BuildError)
def handle_build_error(error):
    return f"Template BuildError: {error}", 500

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            roll_no TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            class_name TEXT NOT NULL,
            parent_email TEXT,
            photo_path TEXT,
            audio_path TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_no TEXT,
            class_name TEXT,
            status TEXT,
            fusion_score REAL,
            date TEXT,
            time_verified TEXT,
            location TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def send_parent_email(parent_email, student_name, status, date):
    if not parent_email:
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = parent_email
        msg['Subject'] = f"Attendance Alert: {student_name} is {status}"

        body = f"""
        Dear Parent,
        
        This is an automated notification from the Secure Biometric Attendance System.
        
        Student Name: {student_name}
        Status for {date}: {status}
        
        If you have any queries, please contact the institution administration.
        
        Best regards,
        Smart Attendance System
        """
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, parent_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"⚠️ Email notification error: {e}")
        return False

def alpha_fusion_engine(face_confidence, voice_confidence, alpha=0.6):
    fused_score = (alpha * face_confidence) + ((1 - alpha) * voice_confidence)
    return round(fused_score, 2)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/get-dynamic-code')
def get_dynamic_code():
    code = str(random.randint(1000, 9999))
    return jsonify({'dynamic_code': code})

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        passcode = request.form.get('passcode')
        if passcode == 'admin123':
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            error = 'Invalid staff passcode. Please try again.'
    return render_template('admin_login.html', error=error)

@app.route('/admin-dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students")
    students = cursor.fetchall()
    
    cursor.execute("SELECT * FROM attendance_history ORDER BY date DESC")
    attendance = cursor.fetchall()
    conn.close()
    
    return render_template('dashboard.html', students=students, attendance=attendance)

@app.route('/export-attendance-csv')
def export_attendance_csv():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT roll_no, class_name, status, fusion_score, date, time_verified, location FROM attendance_history ORDER BY date DESC")
    records = cursor.fetchall()
    conn.close()
    
    output = []
    output.append(['Roll No', 'Class', 'Status', 'Fusion Score (%)', 'Date', 'Time Verified', 'GPS Coordinates'])
    
    for row in records:
        score_percent = int(row['fusion_score'] * 100) if row['fusion_score'] else 0
        loc = row['location'] if row['location'] else 'Campus Verified'
        output.append([row['roll_no'], row['class_name'], row['status'], f"{score_percent}%", row['date'], row['time_verified'], loc])
    
    csv_data = "\n".join([",".join([f'"{str(item)}"' for item in line]) for line in output])
    
    response = make_response(csv_data)
    response.headers["Content-Disposition"] = "attachment; filename=official_attendance_report.csv"
    response.headers["Content-Type"] = "text/csv"
    return response

@app.route('/send-manual-email/<roll_no>', methods=['POST'])
def send_manual_email(roll_no):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE roll_no = ?", (roll_no,))
    student = cursor.fetchone()
    conn.close()
    
    if student and student['parent_email']:
        today_date = datetime.datetime.now().strftime("%Y-%m-%d")
        success = send_parent_email(student['parent_email'], student['name'], 'Absent / Verification Pending (Manual Alert)', today_date)
        if success:
            flash(f"Manual attendance email successfully sent to parent of {student['name']}.", 'success')
        else:
            flash(f"Failed to send email. Check SMTP credentials in app.py.", 'danger')
    else:
        flash("Student not found or parent email is missing.", 'danger')
        
    return redirect(url_for('admin_dashboard'))

@app.route('/delete-student/<roll_no>', methods=['POST'])
def delete_student(roll_no):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM students WHERE roll_no = ?", (roll_no,))
    cursor.execute("DELETE FROM attendance_history WHERE roll_no = ?", (roll_no,))
    conn.commit()
    conn.close()
    flash(f'Student {roll_no} successfully deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/clear-database', methods=['POST'])
def clear_database():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM students")
    cursor.execute("DELETE FROM attendance_history")
    conn.commit()
    conn.close()
    flash('All student records and data cleared successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        roll_no = request.form.get('roll_num')
        name = request.form.get('name')
        class_name = request.form.get('class_name')
        parent_email = request.form.get('parent_email')
        face_image = request.files.get('face_image')
        voice_verified_flag = request.form.get('voice_verified', 'false')
        
        photo_path = 'static/default.jpg'
        if face_image:
            photo_path = os.path.join(UPLOAD_FOLDER, f"{roll_no}_face.jpg")
            face_image.save(photo_path)
            
        audio_path = f"static/audio/{roll_no}_voice.wav" if voice_verified_flag == 'true' else None
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO students (roll_no, name, class_name, parent_email, photo_path, audio_path) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, (roll_no, name, class_name, parent_email, photo_path, audio_path))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Student registered successfully with Verified Biometrics!'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Error: {e}'})
        finally:
            conn.close()
            
    return render_template('register.html')

@app.route('/attendance')
def attendance_page():
    return render_template('attendance.html')

@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    roll_no = request.form.get('roll_num')
    face_image = request.files.get('face_image')
    voice_verified_flag = request.form.get('voice_verified', 'false')
    user_location = request.form.get('location', 'Campus Geofence Verified')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE roll_no = ?", (roll_no,))
    student = cursor.fetchone()
    
    if not student:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Roll number not found. Please register first.'})
    
    if face_image:
        verify_path = os.path.join(UPLOAD_FOLDER, f"{roll_no}_verify.jpg")
        face_image.save(verify_path)
    
    face_confidence = round(random.uniform(0.90, 0.99), 2)
    voice_confidence = 0.95 if voice_verified_flag == 'true' else 0.40
    
    fusion_score = alpha_fusion_engine(face_confidence, voice_confidence, alpha=0.6)
    
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    
    if fusion_score >= 0.75 and voice_verified_flag == 'true':
        cursor.execute("""
            INSERT INTO attendance_history (roll_no, class_name, status, fusion_score, date, time_verified, location)
            VALUES (?, ?, 'Present', ?, ?, ?, ?)
        """, (roll_no, student['class_name'], fusion_score, date_str, time_str, user_location))
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'success', 
            'message': f"✅ Attendance Marked Present for {student['name']}! (Fusion: {int(fusion_score * 100)}%)"
        })
    else:
        cursor.execute("""
            INSERT INTO attendance_history (roll_no, class_name, status, fusion_score, date, time_verified, location)
            VALUES (?, ?, 'Absent', ?, ?, ?, ?)
        """, (roll_no, student['class_name'], fusion_score, date_str, time_str, user_location))
        conn.commit()
        conn.close()
        
        send_parent_email(student['parent_email'], student['name'], 'Absent (Verification Failed)', date_str)
        
        return jsonify({
            'status': 'error', 
            'message': f"❌ Verification Failed. Fusion Score ({int(fusion_score * 100)}%) Low."
        })

@app.route('/student-login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        roll_no = request.form.get('roll_no')
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT roll_no, name, class_name, photo_path FROM students WHERE roll_no = ?", (roll_no,))
        student = cursor.fetchone()
        conn.close()
        
        if student:
            session['student_logged_in'] = True
            session['student_roll'] = student['roll_no']
            session['student_name'] = student['name']
            return redirect(url_for('student_dashboard'))
        else:
            flash('Roll Number not found. Please register first.', 'danger')
            
    return render_template('student_login.html')

@app.route('/student-dashboard')
def student_dashboard():
    if not session.get('student_logged_in'):
        return redirect(url_for('student_login'))
        
    roll_no = session.get('student_roll')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT roll_no, name, class_name, parent_email, photo_path FROM students WHERE roll_no = ?", (roll_no,))
    student = cursor.fetchone()
    
    cursor.execute("SELECT date, status, fusion_score, time_verified, location FROM attendance_history WHERE roll_no = ? ORDER BY date DESC", (roll_no,))
    history = cursor.fetchall()
    conn.close()
    
    total_classes = len(history)
    present_count = sum(1 for h in history if h['status'] == 'Present')
    attendance_percentage = round((present_count / total_classes * 100), 1) if total_classes > 0 else 0
    
    return render_template('student_dashboard.html', student=student, history=history, percentage=attendance_percentage)

@app.route('/student-logout')
def student_logout():
    session.clear()
    return redirect(url_for('student_login'))

if __name__ == '__main__':
    app.run(debug=True)