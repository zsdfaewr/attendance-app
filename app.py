import os
import sqlite3
import cv2
import numpy as np
import librosa
import soundfile as sf
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.routing import BuildError

app = Flask(__name__)
app.secret_key = 'smart_attendance_master_secret_key'

UPLOAD_FOLDER = 'static/uploads'
AUDIO_FOLDER = 'static/audio'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

# Debug error handler for BuildError
@app.errorhandler(BuildError)
def handle_build_error(error):
    print(f"🚨 CRITICAL BUILD ERROR: {error}")
    return f"Template BuildError: {error}", 500

# Database Connection Helper
def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

# Initialize Database & Tables
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
            date TEXT,
            time_verified TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- Landing & Home Route ---
@app.route('/')
def index():
    return render_template('index.html')

# --- Admin Dashboard & Management Routes ---
@app.route('/admin-dashboard')
def admin_dashboard():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students")
    students = cursor.fetchall()
    
    cursor.execute("SELECT * FROM attendance_history ORDER BY date DESC")
    attendance = cursor.fetchall()
    conn.close()
    
    return render_template('dashboard.html', students=students, attendance=attendance)

@app.route('/delete-student/<roll_no>', methods=['POST'])
def delete_student(roll_no):
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
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM students")
    cursor.execute("DELETE FROM attendance_history")
    conn.commit()
    conn.close()
    flash('All student records and data cleared successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

# --- Biometric Registration Route (JSON API + HTML View) ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        roll_no = request.form.get('roll_num')
        name = request.form.get('name')
        class_name = request.form.get('class_name')
        email = request.form.get('email')
        
        photo = request.files.get('photo')
        photo_path = 'static/default.jpg'
        if photo:
            photo_path = os.path.join(UPLOAD_FOLDER, f"{roll_no}_face.jpg")
            photo.save(photo_path)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO students (roll_no, name, class_name, photo_path) 
                VALUES (?, ?, ?, ?)
            """, (roll_no, name, class_name, photo_path))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Student registered successfully!'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Error: {e}'})
        finally:
            conn.close()
            
    return render_template('register.html')

# --- Student Self-Service Portal Routes ---
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
            flash('Roll Number not found. Please check with your administrator.', 'danger')
            
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
    
    cursor.execute("SELECT date, status, time_verified FROM attendance_history WHERE roll_no = ? ORDER BY date DESC", (roll_no,))
    history = cursor.fetchall()
    conn.close()
    
    total_classes = len(history)
    present_count = sum(1 for h in history if h['status'] == 'Present')
    attendance_percentage = round((present_count / total_classes * 100), 1) if total_classes > 0 else 0
    
    return render_template('student_dashboard.html', student=student, history=history, percentage=attendance_percentage)

@app.route('/student-logout')
def student_logout():
    session.pop('student_logged_in', None)
    session.pop('student_roll', None)
    session.pop('student_name', None)
    return redirect(url_for('student_login'))

if __name__ == '__main__':
    app.run(debug=True)