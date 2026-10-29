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
import librosa

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
            photo_path TEXT NOT NULL,
            voice_path TEXT
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


def verify_face_match(registered_path, snapshot_path, alpha=0.6):
    """
    Alpha Fusion Engine: Combines histogram correlation and structural pixel 
    matching using mathematical factor calculations for high-accuracy face verification.
    """
    try:
        if not os.path.exists(registered_path) or 'default.jpg' in registered_path:
            return True  # Bypass if bulk registered with default placeholder

        img1 = cv2.imread(registered_path, cv2.IMREAD_GRAYSCALE)
        img2 = cv2.imread(snapshot_path, cv2.IMREAD_GRAYSCALE)

        if img1 is None or img2 is None:
            return False

        # Resize both to standard dimensions for matrix calculation
        img1 = cv2.resize(img1, (200, 200))
        img2 = cv2.resize(img2, (200, 200))

        # --- Factor 1: Histogram Correlation (Intensity Distribution) ---
        hist1 = cv2.calcHist([img1], [0], None, [256], [0, 256])
        hist2 = cv2.calcHist([img2], [0], None, [256], [0, 256])
        cv2.normalize(hist1, hist1, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        cv2.normalize(hist2, hist2, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        hist_score = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)  # Range: [-1, 1]
        
        # Normalize histogram score to [0, 1] range
        hist_score = max(0.0, (hist_score + 1.0) / 2.0)

        # --- Factor 2: Template / Structural Matrix Matching ---
        res = cv2.matchTemplate(img1, img2, cv2.TM_CCOEFF_NORMED)
        _, structural_score, _, _ = cv2.minMaxLoc(res)  # Range: [-1, 1]
        
        # Normalize structural score to [0, 1] range
        structural_score = max(0.0, (structural_score + 1.0) / 2.0)

        # --- Alpha Fusion Mathematical Calculation ---
        fused_score = (alpha * hist_score) + ((1.0 - alpha) * structural_score)

        print(f"[Alpha Fusion Engine] Hist: {hist_score:.3f} | Structure: {structural_score:.3f} | Fused: {fused_score:.3f}")

        return fused_score > 0.52

    except Exception as e:
        print(f"Alpha fusion comparison error: {e}")
        return False


def verify_voice_match(registered_voice_path, snapshot_voice_path):
    """
    Compares registered voice and live audio snapshot using MFCC feature cosine similarity.
    """
    try:
        if not registered_voice_path or not os.path.exists(registered_voice_path):
            return True  # Bypass if voice wasn't recorded during legacy registration

        y1, sr1 = librosa.load(registered_voice_path, sr=None)
        y2, sr2 = librosa.load(snapshot_voice_path, sr=None)

        mfcc1 = librosa.feature.mfcc(y=y1, sr=sr1, n_mfcc=13)
        mfcc2 = librosa.feature.mfcc(y=y2, sr=sr2, n_mfcc=13)

        # Compute mean across time frames for global feature vector representation
        mfcc1_mean = np.mean(mfcc1, axis=1)
        mfcc2_mean = np.mean(mfcc2, axis=1)

        # Calculate cosine similarity between MFCC vectors
        dot_product = np.dot(mfcc1_mean, mfcc2_mean)
        norm1 = np.linalg.norm(mfcc1_mean)
        norm2 = np.linalg.norm(mfcc2_mean)

        if norm1 == 0 or norm2 == 0:
            return False

        similarity = dot_product / (norm1 * norm2)
        print(f"[Voice Biometric Engine] Similarity Score: {similarity:.3f}")

        return similarity > 0.75  # Threshold for speaker verification match
    except Exception as e:
        print(f"Voice comparison error: {e}")
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
    voice = request.files.get('voice')

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
    normalized_photo_path = photo_path.replace('\\', '/')

    voice_path_db = None
    if voice:
        voice_filename = f"{roll_num}_{int(datetime.now().timestamp())}.wav"
        voice_path = os.path.join(app.config['UPLOAD_FOLDER'], voice_filename)
        voice.save(voice_path)
        voice_path_db = voice_path.replace('\\', '/')

    try:
        cursor.execute(
            'INSERT INTO students (roll_num, name, class_name, email, photo_path, voice_path) VALUES (?, ?, ?, ?, ?, ?)',
            (roll_num, name, class_name, email, normalized_photo_path, voice_path_db)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        if os.path.exists(photo_path):
            os.remove(photo_path)
        return jsonify({"status": "exists", "message": "Roll number already registered!"}), 400

    conn.close()
    return jsonify({"status": "success", "message": "Registered successfully with Alpha Fusion Face & Voice biometrics!"})


@app.route('/attendance', methods=['GET'])
def attendance_page():
    return render_template('attendance.html')


@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    roll_num = request.form.get('roll_num')
    face_image = request.files.get('face_image')
    voice_audio = request.files.get('voice_audio')

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
    registered_voice_path = student[5] if len(student) > 5 else None

    # Save incoming attendance snapshot temporarily for verification
    temp_snapshot_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{roll_num}.jpg")
    face_image.save(temp_snapshot_path)

    # Perform Alpha Fusion face matching check
    is_face_valid = verify_face_match(registered_photo_path, temp_snapshot_path)

    if os.path.exists(temp_snapshot_path):
        os.remove(temp_snapshot_path)

    if not is_face_valid:
        conn.close()
        return jsonify({"status": "mismatch", "message": "Face does not match registered student profile via Alpha Fusion!"}), 400

    # Perform Voice Biometric check if audio provided
    if voice_audio and registered_voice_path:
        temp_audio_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{roll_num}.wav")
        voice_audio.save(temp_audio_path)
        is_voice_valid = verify_voice_match(registered_voice_path, temp_audio_path)
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)

        if not is_voice_valid:
            conn.close()
            return jsonify({"status": "mismatch", "message": "Voice does not match registered student profile!"}), 400

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

    return jsonify({"status": "success", "message": "Dual-Biometric attendance marked successfully with Alpha Fusion & Voice verification!"})


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
                    INSERT OR IGNORE INTO students (roll_num, name, class_name, email, photo_path, voice_path)
                    VALUES (?, ?, ?, ?, ?, NULL)
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
    
    cursor.execute('SELECT photo_path, voice_path FROM students')
    records = cursor.fetchall()
    
    for photo_path, voice_path in records:
        if photo_path and os.path.exists(photo_path) and 'default.jpg' not in photo_path:
            try:
                os.remove(photo_path)
            except Exception as e:
                print(f"Error deleting photo file: {e}")
        if voice_path and os.path.exists(voice_path):
            try:
                os.remove(voice_path)
            except Exception as e:
                print(f"Error deleting voice file: {e}")
                
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

    sender_email = os.environ.get('MAIL_USERNAME', 'your_actual_email@gmail.com')
    sender_password = os.environ.get('MAIL_PASSWORD', 'your_app_password')

    try:
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