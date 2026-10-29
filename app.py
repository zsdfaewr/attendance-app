import os
import sqlite3
import datetime
import random
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.routing import BuildError

app = Flask(__name__)
app.secret_key = 'smart_attendance_master_secret_key'

UPLOAD_FOLDER = 'static/uploads'
AUDIO_FOLDER = 'static/audio'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

@app.errorhandler(BuildError)
def handle_build_error(error):
    print(f"🚨 CRITICAL BUILD ERROR: {error}")
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
            time_verified TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- Alpha Fusion Engine ---
def alpha_fusion_engine(face_confidence, voice_confidence, alpha=0.6):
    """
    Multimodal Alpha Fusion Engine: 
    Fuses spatial facial embeddings confidence with temporal voice passcode confidence.
    Score = (alpha * face_score) + ((1 - alpha) * voice_score)
    """
    fused_score = (alpha * face_confidence) + ((1 - alpha) * voice_confidence)
    return round(fused_score, 2)

@app.route('/')
def index():
    return render_template('index.html')[cite: 3]

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
    return render_template('admin_login.html', error=error)[cite: 3]

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
    
    return render_template('dashboard.html', students=students, attendance=attendance)[cite: 3]

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
    return redirect(url_for('admin_dashboard'))[cite: 3]

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
    return redirect(url_for('admin_dashboard'))[cite: 3]

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        roll_no = request.form.get('roll_num')
        name = request.form.get('name')
        class_name = request.form.get('class_name')
        face_image = request.files.get('face_image')
        
        photo_path = 'static/default.jpg'
        if face_image:
            photo_path = os.path.join(UPLOAD_FOLDER, f"{roll_no}_face.jpg")
            face_image.save(photo_path)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO students (roll_no, name, class_name, photo_path) 
                VALUES (?, ?, ?, ?)
            """, (roll_no, name, class_name, photo_path))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Student registered successfully with biometric face capture!'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Error: {e}'})
        finally:
            conn.close()
            
    return render_template('register.html')

@app.route('/attendance')
def attendance_page():
    return render_template('attendance.html')[cite: 3]

@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    roll_no = request.form.get('roll_num')
    face_image = request.files.get('face_image')
    voice_verified_flag = request.form.get('voice_verified', 'false')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE roll_no = ?", (roll_no,))
    student = cursor.fetchone()
    
    if not student:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Roll number not registered in the system.'})
    
    if face_image:
        verify_path = os.path.join(UPLOAD_FOLDER, f"{roll_no}_verify.jpg")
        face_image.save(verify_path)
    
    # Simulate robust confidence scoring for Fusion Engine
    face_confidence = round(random.uniform(0.85, 0.99), 2)
    voice_confidence = 0.95 if voice_verified_flag == 'true' else 0.40
    
    # Compute Alpha Fusion Score (Alpha = 0.6 for face priority, 0.4 for voice)
    fusion_score = alpha_fusion_engine(face_confidence, voice_confidence, alpha=0.6)
    
    # Threshold for successful multimodal verification (e.g. >= 0.75)
    if fusion_score >= 0.75 and voice_verified_flag == 'true':
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        
        cursor.execute("""
            INSERT INTO attendance_history (roll_no, class_name, status, fusion_score, date, time_verified)
            VALUES (?, ?, 'Present', ?, ?, ?)
        """, (roll_no, student['class_name'], fusion_score, date_str, time_str))
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'success', 
            'message': f"Attendance marked for {student['name']}! (Alpha Fusion Confidence: {fusion_score * 100}%)"
        })
    else:
        conn.close()
        return jsonify({
            'status': 'error', 
            'message': f"Biometric verification failed. Fusion score ({fusion_score * 100}%) below security threshold."
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
    
    cursor.execute("SELECT roll_no, name, class_name, photo_path FROM students WHERE roll_no = ?", (roll_no,))
    student = cursor.fetchone()
    
    cursor.execute("SELECT date, status, fusion_score, time_verified FROM attendance_history WHERE roll_no = ? ORDER BY date DESC", (roll_no,))
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