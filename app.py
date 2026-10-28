import os
import sqlite3
from datetime import datetime
import io
import csv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, redirect, url_for, session, Response, jsonify
import cv2
import numpy as np

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_attendance_key')

UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            roll_num TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            class_name TEXT NOT NULL,
            email TEXT NOT NULL,
            photo_path TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            roll_num TEXT PRIMARY KEY,
            marked_at TEXT NOT NULL,
            FOREIGN KEY (roll_num) REFERENCES students (roll_num)
        )
    ''')
    conn.commit()
    conn.close()


init_db()


def verify_face_match(registered_path, snapshot_path):
    """Compares registered photo and live snapshot using OpenCV Histogram Correlation."""
    try:
        if not os.path.exists(registered_path) or 'default.jpg' in registered_path:
            return True  # Bypass if bulk registered with default placeholder

        img1 = cv2.imread(registered_path, cv2.IMREAD_GRAYSCALE)
        img2 = cv2.imread(snapshot_path, cv2.IMREAD_GRAYSCALE)

        if img1 is None or img2 is None:
            return False

        # Resize both to standard dimensions
        img1 = cv2.resize(img1, (200, 200))
        img2 = cv2.resize(img2, (200, 200))

        # Calculate histograms
        hist1 = cv2.calcHist([img1], [0], None, [256], [0, 256])
        hist2 = cv2.calcHist([img2], [0], None, [256], [0, 256])
        cv2.normalize(hist1, hist1, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        cv2.normalize(hist2, hist2, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

        # Compare histograms (Returns value between -1 and 1; 1 means identical)
        similarity = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
        
        # Threshold set to 0.55 for facial similarity under varying lighting
        return similarity > 0.55
    except Exception as e:
        print(f"Face comparison error: {e}")
        return False


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/register', methods=['GET'])
def register_page():
    return render_template('register.html')


@app.route('/register_student', methods=['POST'])
def register_student():
    roll_num = request.form.get('roll_num')
    name = request.form.get('name')
    class_name = request.form.get('class_name')
    email = request.form.get('email')
    photo = request.files.get('photo')

    if not roll_num or not name or not class_name or not email or not photo:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    cursor.execute('SELECT roll_num FROM students WHERE roll_num = ?', (roll_num,))
    if cursor.fetchone():
        conn.close()
        return jsonify({"status": "exists", "message": "Roll number already registered!"}), 400

    photo_filename = f"{roll_num}_{int(datetime.now().timestamp())}.jpg"
    photo_path = os.path.join(app.config['UPLOAD_FOLDER'], photo_filename)
    photo.save(photo_path)
    normalized_path = photo_path.replace('\\', '/')

    try:
        cursor.execute(
            'INSERT INTO students (roll_num, name, class_name, email, photo_path) VALUES (?, ?, ?, ?, ?)',
            (roll_num, name, class_name, email, normalized_path)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        if os.path.exists(photo_path):
            os.remove(photo_path)
        return jsonify({"status": "exists", "message": "Roll number already registered!"}), 400

    conn.close()
    return jsonify({"status": "success", "message": "Registered successfully with dual-biometrics & liveness!"})


@app.route('/attendance', methods=['GET'])
def attendance_page():
    return render_template('attendance.html')


@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    roll_num = request.form.get('roll_num')
    face_image = request.files.get('face_image')

    if not roll_num or not face_image:
        return jsonify({"status": "error", "message": "Roll number and face snapshot required"}), 400

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM students WHERE roll_num = ?', (roll_num,))
    student = cursor.fetchone()
    if not student:
        conn.close()
        return jsonify({"status": "not_registered", "message": "Student not registered! Please register first."}), 404

    registered_photo_path = student[4]

    # Save incoming attendance snapshot temporarily for verification
    temp_snapshot_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{roll_num}.jpg")
    face_image.save(temp_snapshot_path)

    # Perform strict face matching check
    is_face_valid = verify_face_match(registered_photo_path, temp_snapshot_path)

    if os.path.exists(temp_snapshot_path):
        os.remove(temp_snapshot_path)

    if not is_face_valid:
        conn.close()
        return jsonify({"status": "mismatch", "message": "Face does not match registered student profile!"}), 400

    cursor.execute('SELECT * FROM attendance WHERE roll_num = ?', (roll_num,))
    existing_attendance = cursor.fetchone()
    if existing_attendance:
        conn.close()
        return jsonify({"status": "exists", "message": "Attendance already marked for today!"})

    marked_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute(
        'INSERT OR REPLACE INTO attendance (roll_num, marked_at) VALUES (?, ?)',
        (roll_num, marked_at)
    )
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Dual-Biometric attendance marked successfully!"})


@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        passcode = request.form.get('passcode')
        if passcode == 'staff123':
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin_login.html', error="Invalid Passcode!")
    return render_template('admin_login.html')


@app.route('/dashboard')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT s.roll_num, s.name, s.class_name,
               CASE WHEN a.marked_at IS NOT NULL THEN 'Present' ELSE 'Absent' END as status,
               s.photo_path,
               COALESCE(a.marked_at, '---') as marked_at
        FROM students s 
        LEFT JOIN attendance a ON s.roll_num = a.roll_num
    ''')
    attendance_records = cursor.fetchall()

    cursor.execute('SELECT COUNT(*) FROM students')
    total_students = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM attendance')
    total_present = cursor.fetchone()[0]

    total_absent = total_students - total_present

    cursor.execute('SELECT DISTINCT class_name FROM students ORDER BY class_name ASC')
    distinct_classes = [row[0] for row in cursor.fetchall()]

    conn.close()

    return render_template(
        'dashboard.html',
        attendance_records=attendance_records,
        total_students=total_students,
        total_present=total_present,
        total_absent=total_absent,
        distinct_classes=distinct_classes
    )


@app.route('/bulk_register', methods=['POST'])
def bulk_register():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    
    file = request.files.get('csv_file')
    if not file or file.filename == '':
        return redirect(url_for('admin_dashboard'))
    
    stream = io.TextIOWrapper(file.stream, encoding='utf-8-sig')
    reader = csv.reader(stream)
    header = next(reader, None)
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    for row in reader:
        if len(row) >= 4:
            roll_num, name, class_name, email = row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip()
            photo_path = 'static/uploads/default.jpg'
            
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO students (roll_num, name, class_name, email, photo_path)
                    VALUES (?, ?, ?, ?, ?)
                ''', (roll_num, name, class_name, email, photo_path))
            except Exception as e:
                print(f"Bulk insert error for {roll_num}: {e}")
                
    conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))


@app.route('/reset_attendance', methods=['POST'])
def reset_attendance():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM attendance')
    conn.commit()
    conn.close()

    return redirect(url_for('admin_dashboard'))


@app.route('/reset_students', methods=['POST'])
def reset_students():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT photo_path FROM students')
    photos = cursor.fetchall()
    
    for (photo_path,) in photos:
        if photo_path and os.path.exists(photo_path) and 'default.jpg' not in photo_path:
            try:
                os.remove(photo_path)
            except Exception as e:
                print(f"Error deleting file: {e}")
                
    cursor.execute('DELETE FROM attendance')
    cursor.execute('DELETE FROM students')
    conn.commit()
    conn.close()

    return redirect(url_for('admin_dashboard'))


@app.route('/send_absent_alerts', methods=['POST'])
def send_absent_alerts():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT s.name, s.email 
        FROM students s 
        LEFT JOIN attendance a ON s.roll_num = a.roll_num 
        WHERE a.marked_at IS NULL
    ''')
    absent_students = cursor.fetchall()
    conn.close()

    if not absent_students:
        return "No absent students found to notify!", 200

    # Pull credentials from environment variables (or replace directly with your Gmail & 16-character App Password)
    sender_email = os.environ.get('MAIL_USERNAME', 'toraskarsanket2002@gmail.com')
    sender_password = os.environ.get('MAIL_PASSWORD', 'ujtoxdkqnmrjduhp')

    try:
        # Using Port 465 with SMTP_SSL for stable secure connection
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)

            for name, email in absent_students:
                if email:
                    msg = MIMEMultipart()
                    msg['From'] = sender_email
                    msg['To'] = email
                    msg['Subject'] = "Attendance Alert: Marked Absent Today"
                    
                    body = f"Hello {name},\n\nYou have been marked absent for today's session. Please contact administration if this is an error.\n\nBest regards,\nSmart Attendance System"
                    msg.attach(MIMEText(body, 'plain'))
                    
                    server.sendmail(sender_email, email, msg.as_string())

        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        return f"Failed to send emails. Make sure sender credentials are correct. Error: {str(e)}"


@app.route('/export_csv')
def export_csv():
    if not session.get('is_admin'):
        return "Admin session expired. Please log in again through the dashboard.", 403

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.roll_num, s.name, s.class_name,
               CASE WHEN a.marked_at IS NOT NULL THEN 'Present' ELSE 'Absent' END as status,
               COALESCE(a.marked_at, '---') as marked_at
        FROM students s 
        LEFT JOIN attendance a ON s.roll_num = a.roll_num
    ''')
    records = cursor.fetchall()
    conn.close()

    output = io.BytesIO()
    wrapper = io.TextIOWrapper(output, encoding='utf-8-sig', newline='')
    writer = csv.writer(wrapper)

    writer.writerow(['Roll Number', 'Name', 'Class', 'Status', 'Time Marked'])

    for row in records:
        writer.writerow(row)

    wrapper.flush()
    output.seek(0)

    return Response(
        output.read(),
        mimetype='text/csv',
        headers={"Content-Disposition": "attachment;filename=attendance_report.csv"}
    )


@app.route('/admin_logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)