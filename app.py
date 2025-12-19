# --- Imports ---
import os
import io
import json
import base64
import smtplib, ssl
from email.mime.text import MIMEText
from sqlalchemy import func
import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from flask import Flask, request, redirect, session, url_for, render_template, jsonify, current_app
from flask_sqlalchemy import SQLAlchemy
import logging
from utils import extract_text_from_file

from theory_analyzer import analyze_theory_submission
from programming_analyzer import analyze_programming_submission
from plagiarism_checker import check_plagiarism_for_assignment

from dotenv import load_dotenv
load_dotenv()

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')

# --- Flask App Initialization ---
app = Flask(__name__)
app.secret_key = os.urandom(24)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

app.config['SENDER_EMAIL'] = os.environ.get("SENDER_EMAIL")
app.config['SENDER_APP_PASSWORD'] = os.environ.get("SENDER_APP_PASSWORD")


CLIENT_SECRETS_FILE = "client_secret.json"

# --- Google API Scopes ---
SCOPES = [
    'https://www.googleapis.com/auth/classroom.courses.readonly',
    'https://www.googleapis.com/auth/classroom.coursework.students.readonly',
    'https://www.googleapis.com/auth/classroom.rosters.readonly',
    'https://www.googleapis.com/auth/classroom.student-submissions.students.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]
API_SERVICE_NAME = 'classroom'
API_VERSION = 'v1'

# --- Database Configuration ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///results.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Database Models ---
class PlagiarismResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.String(100), nullable=False)
    student_id_1 = db.Column(db.String(100), nullable=False)
    student_id_2 = db.Column(db.String(100), nullable=False)
    plagiarism_score = db.Column(db.Float, nullable=False)
    domain = db.Column(db.String(20), nullable=False)
    __table_args__ = (
        db.UniqueConstraint('assignment_id', 'student_id_1', 'student_id_2', name='_assignment_student_pair_uc'),
    )

class Result(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.String(100), nullable=False)
    student_id = db.Column(db.String(100), nullable=False)
    assignment_id = db.Column(db.String(100), nullable=False)
    accuracy_score = db.Column(db.Float, nullable=False)
    justification = db.Column(db.String(500), nullable=True)
    __table_args__ = (db.UniqueConstraint('course_id', 'student_id', 'assignment_id', name='_course_student_assignment_uc'),)


# --- Create Tables Before First Request ---
@app.before_request
def create_tables():
    with app.app_context(): db.create_all()
    if 'create_tables' in getattr(app, 'before_request_funcs', {}).get(None, []):
        app.before_request_funcs[None].remove(create_tables)

# --- SMTP Email Helper (FINAL DIAGNOSTIC VERSION) ---
def send_smtp_email(sender_email, password, receiver_email, subject, body):
    if not sender_email or not password:
        app.logger.error("SMTP DIAGNOSTIC: Sender email or password not configured.")
        return False

    message = MIMEText(body, "plain")
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = receiver_email
    
    context = ssl.create_default_context()
    server = None
    try:
        # Add a 15-second timeout to force an error if the connection hangs
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
        server.starttls(context=context)
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, message.as_string())
        app.logger.info(f"SMTP DIAGNOSTIC: Successfully sent email to {receiver_email}")
        return True
    except TimeoutError:
        app.logger.error("SMTP DIAGNOSTIC: The connection timed out. This strongly suggests a network block (possibly ISP).")
        return False
    except smtplib.SMTPAuthenticationError:
        app.logger.error("SMTP DIAGNOSTIC: Authentication failed. Credentials incorrect.")
        return False
    except Exception as e:
        app.logger.error(f"SMTP DIAGNOSTIC: An unexpected error occurred: {e}")
        return False
    finally:
        if server:
            server.quit()

# --- Routes ---
# ... (Most routes remain unchanged) ...
@app.route("/")
def index():
    return render_template('index.html')

@app.route("/login")
def login():
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = url_for('oauth2callback', _external=True)
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    session['state'] = state
    return redirect(authorization_url)

@app.route("/callback")
def oauth2callback():
    state = session['state']
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
    flow.redirect_uri = url_for('oauth2callback', _external=True)
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session['credentials'] = {'token': credentials.token, 'refresh_token': credentials.refresh_token, 'token_uri': credentials.token_uri, 'client_id': credentials.client_id, 'client_secret': credentials.client_secret, 'scopes': credentials.scopes}
    return redirect(url_for('dashboard'))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('index'))

def build_service():
    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    return build(API_SERVICE_NAME, API_VERSION, credentials=credentials)

@app.route("/dashboard")
def dashboard():
    if 'credentials' not in session: return redirect(url_for('login'))
    service = build_service()
    courses = service.courses().list(pageSize=10).execute().get('courses', [])
    return render_template('dashboard.html', courses=courses)

@app.route('/api/assignments/<course_id>')
def get_assignments(course_id):
    if 'credentials' not in session: return {"error": "Not authenticated"}, 401
    service = build_service()
    coursework = service.courses().courseWork().list(courseId=course_id, pageSize=20).execute().get('courseWork', [])
    return {"assignments": coursework}

@app.route('/analyze', methods=['POST'])
def analyze():
    if 'credentials' not in session: return {"error": "Not authenticated"}, 401
    data = request.get_json()
    course_id, assignment_id, domain = data.get('course_id'), data.get('assignment_id'), data.get('domain')
    service, drive_service = build_service(), build('drive', 'v3', credentials=google.oauth2.credentials.Credentials(**session['credentials']))
    question = ""
    try:
        assignment_details = service.courses().courseWork().get(courseId=course_id, id=assignment_id).execute()
        question = f"{assignment_details.get('title', '')}\n\n{assignment_details.get('description', '')}".strip()
        students = service.courses().students().list(courseId=course_id).execute().get('students', [])
        student_ids = {s['userId'] for s in students}
        submissions = service.courses().courseWork().studentSubmissions().list(courseId=course_id, courseWorkId=assignment_id, states=['TURNED_IN']).execute().get('studentSubmissions', [])
    except Exception as e: return {"error": f"Failed to fetch Classroom data: {e}"}, 500
    student_texts_for_plagiarism, processed_student_ids = {}, set()
    for sub in submissions:
        student_id = sub['userId']
        processed_student_ids.add(student_id)
        if Result.query.filter_by(course_id=course_id, student_id=student_id, assignment_id=assignment_id).first(): continue
        attachments = sub.get('assignmentSubmission', {}).get('attachments', [])
        total_score, processed_count, all_justifications = 0.0, 0, []
        for attachment in attachments:
            try:
                drive_file = attachment.get('driveFile')
                if not drive_file: continue
                file_id = drive_file['id']
                mime_type = drive_service.files().get(fileId=file_id, fields='mimeType').execute().get('mimeType')
                fh = io.BytesIO()
                MediaIoBaseDownload(fh, drive_service.files().get_media(fileId=file_id)).next_chunk()
                ocr_text = extract_text_from_file(fh.getvalue(), mime_type)
                if not ocr_text or ocr_text == "Unsupported File Type": continue
                student_texts_for_plagiarism.setdefault(student_id, "")
                student_texts_for_plagiarism[student_id] += ocr_text + "\n"
                grading_result = analyze_theory_submission(question, ocr_text) if domain == 'theory' else analyze_programming_submission(question, ocr_text)
                total_score += grading_result.get('score', 0.0)
                all_justifications.append(grading_result.get('justification', 'AI analysis failed.'))
                processed_count += 1
            except Exception as e: print(f"Could not process attachment for student {student_id}. Error: {e}")
        final_score = (total_score / processed_count) if processed_count > 0 else 0.0
        final_justification = " | ".join(all_justifications) if all_justifications else "No processable attachments found."
        try:
            db.session.add(Result(course_id=course_id, student_id=student_id, assignment_id=assignment_id, accuracy_score=final_score, justification=final_justification))
            db.session.commit()
        except Exception as e: db.session.rollback()
    plagiarism_results = check_plagiarism_for_assignment(student_texts_for_plagiarism, domain)
    PlagiarismResult.query.filter_by(assignment_id=assignment_id).delete()
    for presult in plagiarism_results:
        sid1, sid2 = sorted([presult['student1'], presult['student2']])
        db.session.add(PlagiarismResult(assignment_id=assignment_id, student_id_1=sid1, student_id_2=sid2, plagiarism_score=presult['score'], domain=domain))
    for student_id in (student_ids - processed_student_ids):
        if not Result.query.filter_by(course_id=course_id, student_id=student_id, assignment_id=assignment_id).first():
            db.session.add(Result(course_id=course_id, student_id=student_id, assignment_id=assignment_id, accuracy_score=0.0, justification="No submission found."))
    try: db.session.commit()
    except Exception as e: db.session.rollback()
    return {"status": "Analysis complete!", "redirect": url_for('show_results', course_id=course_id, assignment_id=assignment_id)}


@app.route('/email_reports/<course_id>/<assignment_id>', methods=['POST'])
def email_reports(course_id, assignment_id):
    if 'credentials' not in session: return jsonify({"error": "Not authenticated"}), 401
    
    service = build_service()
    successful_sends, failed_sends = 0, 0
    
    sender_email = current_app.config.get('SENDER_EMAIL')
    sender_password = current_app.config.get('SENDER_APP_PASSWORD')

    try:
        assignment_details = service.courses().courseWork().get(courseId=course_id, id=assignment_id).execute()
        assignment_title = assignment_details.get('title', 'Assignment Report')
        
        local_results = Result.query.filter_by(course_id=course_id, assignment_id=assignment_id).all()
        
        plagiarized_students = {p.student_id_1 for p in PlagiarismResult.query.filter(PlagiarismResult.assignment_id==assignment_id, PlagiarismResult.plagiarism_score >= 0.75).all()}
        plagiarized_students.update({p.student_id_2 for p in PlagiarismResult.query.filter(PlagiarismResult.assignment_id==assignment_id, PlagiarismResult.plagiarism_score >= 0.75).all()})

        for result in local_results:
            try:
                profile = service.userProfiles().get(userId=result.student_id).execute()
                student_email = profile.get('emailAddress')
                if not student_email:
                    failed_sends += 1
                    continue

                subject = f"Feedback for your submission: {assignment_title}"
                
                if result.student_id in plagiarized_students:
                    body = "Hello,\n\nYour submission for this assignment has been flagged for a high similarity score with another submission. Please review your work and resubmit a new version.\n\nThank you."
                else:
                    final_remark = result.justification.rsplit('Final Remark:', 1)[-1].strip() if 'Final Remark:' in result.justification else result.justification
                    body = f"Hello,\n\nHere is the feedback on your recent submission:\n\n---\n{final_remark}\n---\n\nIf you have any questions, please let me know."

                if send_smtp_email(sender_email, sender_password, student_email, subject, body):
                    successful_sends += 1
                else:
                    failed_sends += 1
            except Exception as e:
                failed_sends += 1
                app.logger.error(f"Failed to process email for student {result.student_id}: {e}")
                continue

        status_message = f"Process complete. Successfully sent {successful_sends} emails."
        if failed_sends > 0:
            status_message += f" Failed to send {failed_sends} emails. Please check server logs for details."
        
        return jsonify({"status": status_message})

    except Exception as e:
        return jsonify({"error": f"A critical error occurred: {e}"}), 500

@app.route('/clear_analysis/<course_id>/<assignment_id>', methods=['POST'])
def clear_analysis(course_id, assignment_id):
    if 'credentials' not in session: return {"error": "Not authenticated"}, 401
    try:
        num_deleted = Result.query.filter_by(course_id=course_id, assignment_id=assignment_id).delete()
        db.session.commit()
        return {"status": f"Successfully cleared {num_deleted} results."}
    except Exception as e:
        db.session.rollback()
        return {"error": "Failed to clear analysis data."}, 500

@app.route('/mark_sheet/<course_id>')
def mark_sheet(course_id):
    if 'credentials' not in session: return redirect(url_for('login'))
    service = build_service()
    try:
        course_details = service.courses().get(id=course_id).execute()
        course_title = course_details.get('name', 'Mark Sheet')
        student_scores = db.session.query(Result.student_id, func.avg(Result.accuracy_score).label('average_score')).filter(Result.course_id == course_id).group_by(Result.student_id).all()
        display_data = []
        for student_id, avg_score in student_scores:
            student_name = f"ID: {student_id}"
            try:
                profile = service.userProfiles().get(userId=student_id).execute()
                student_name = profile.get('name', {}).get('fullName', student_name)
            except Exception: pass
            display_data.append({'name': student_name, 'average_score': avg_score * 100})
    except Exception as e: return f"An error occurred: {e}"
    return render_template('mark_sheet.html', results=display_data, course_title=course_title)

@app.route('/results/<course_id>/<assignment_id>')
def show_results(course_id, assignment_id):
    if 'credentials' not in session: return redirect(url_for('login'))
    service = build_service()
    results_from_db = Result.query.filter_by(assignment_id=assignment_id, course_id=course_id).all()
    display_data, assignment_title = [], "Unknown Assignment"
    try:
        assignment_details = service.courses().courseWork().get(courseId=course_id, id=assignment_id).execute()
        assignment_title = assignment_details.get('title', 'Unknown Assignment')
        for result in results_from_db:
            student_name = f"ID: {result.student_id}"
            try:
                profile = service.userProfiles().get(userId=result.student_id).execute()
                student_name = profile.get('name', {}).get('fullName', student_name)
            except Exception: pass
            display_data.append({'name': student_name, 'score': result.accuracy_score * 100, 'justification': result.justification})
    except Exception as e: pass
    return render_template('results.html', results=display_data, assignment_title=assignment_title)

@app.route('/plagiarism_report/<course_id>/<assignment_id>')
def plagiarism_report(course_id, assignment_id):
    if 'credentials' not in session: return redirect(url_for('login'))
    service = build_service()
    plag_results = PlagiarismResult.query.filter_by(assignment_id=assignment_id).order_by(PlagiarismResult.plagiarism_score.desc()).all()
    assignment_details = service.courses().courseWork().get(courseId=course_id, id=assignment_id).execute()
    assignment_title = assignment_details.get('title', 'Plagiarism Report')
    display_data = []
    for result in plag_results:
        if result.plagiarism_score < 0.75: continue
        try:
            profile1 = service.userProfiles().get(userId=result.student_id_1).execute()
            name1 = profile1.get('name', {}).get('fullName', f"ID: {result.student_id_1}")
            profile2 = service.userProfiles().get(userId=result.student_id_2).execute()
            name2 = profile2.get('name', {}).get('fullName', f"ID: {result.student_id_2}")
            display_data.append({'name1': name1, 'name2': name2, 'score': result.plagiarism_score})
        except Exception: continue
    return render_template('plagiarism_report.html', results=display_data, assignment_title=assignment_title)

if __name__ == "__main__":
    app.run(debug=True, port=5000)

