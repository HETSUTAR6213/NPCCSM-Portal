import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# Enable CORS so your frontend HTML files can communicate with this API without cross-origin errors
CORS(app)

# Initialize the Supabase client using environment variables
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("WARNING: Supabase environment variables are not set. The API will fail to connect.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/api/signup', methods=['POST'])
def signup():
    """
    Handles new user registration, checking for duplicate emails or enrollment numbers.
    """
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        role = data.get('role')
        name = data.get('name')
        enrollment_number = data.get('enrollmentNumber') # Only provided if role is 'student'

        # Check if a user with this email already exists
        existing_user = supabase.table('users').select('*').eq('email', email).execute()
        if len(existing_user.data) > 0:
            return jsonify({"status": "error", "message": "An account with this email already exists."}), 400

        # Check if a student with this enrollment number already exists
        if role == 'student' and enrollment_number:
            existing_enrollment = supabase.table('users').select('*').eq('enrollment_number', enrollment_number).execute()
            if len(existing_enrollment.data) > 0:
                return jsonify({"status": "error", "message": "This enrollment number is already registered."}), 400

        # Securely hash the password before storing it
        hashed_password = generate_password_hash(password)

        # Insert the new user into the database
        new_user_data = {
            "email": email,
            "password_hash": hashed_password,
            "role": role,
            "name": name,
            "enrollment_number": enrollment_number if role == 'student' else None
        }
        
        supabase.table('users').insert(new_user_data).execute()
        
        return jsonify({"status": "success", "message": "Account created successfully."}), 201

    except Exception as e:
        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500


@app.route('/api/login', methods=['POST'])
def login():
    """
    Authenticates an existing user and ensures they are logging into the correct role portal.
    """
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        role_attempted = data.get('role')
        enrollment_attempted = data.get('enrollmentNumber')

        # Retrieve the user from the database by email
        response = supabase.table('users').select('*').eq('email', email).execute()
        
        if len(response.data) == 0:
            return jsonify({"status": "error", "message": "No account found with this email."}), 404
            
        user = response.data[0]

        # Verify password
        if not check_password_hash(user['password_hash'], password):
            return jsonify({"status": "error", "message": "Incorrect password."}), 401

        # Role validation: Ensure the user is logging into the correct portal tab
        if user['role'] != role_attempted:
            return jsonify({"status": "error", "message": f"Account role mismatch. You are registered as a {user['role']}."}), 403

        # For students, strictly enforce that they provide their correct enrollment number to log in
        if role_attempted == 'student':
            if user['enrollment_number'] != enrollment_attempted:
                return jsonify({"status": "error", "message": "Incorrect enrollment number for this email."}), 401

        # Return successful auth profile to the frontend
        return jsonify({
            "status": "success",
            "name": user['name'],
            "role": user['role'],
            "email": user['email'],
            "enrollmentNumber": user.get('enrollment_number')
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500


@app.route('/api/syllabus/update', methods=['POST'])
def update_syllabus():
    """
    Receives syllabus completion data from the Faculty portal and inserts it into the database.
    """
    try:
        data = request.json
        subject_code = data.get('subject_code')
        faculty_name = data.get('facultyName')
        lecture_date = data.get('lastUpdated')
        
        covered_topics = data.get('coveredTopics', [])
        topic_notes = data.get('topicNotes', {})

        if not covered_topics:
            return jsonify({"status": "error", "message": "No topics were marked as covered."}), 400

        # Loop through the submitted topics and insert them as separate records
        for topic in covered_topics:
            note = topic_notes.get(topic, "")
            
            # Check if this exact topic was already marked as covered for this subject to prevent duplicates
            existing = supabase.table('faculty_lecture_updates').select('*').eq('subject_code', subject_code).eq('covered_topic', topic).execute()
            
            if len(existing.data) == 0:
                supabase.table('faculty_lecture_updates').insert({
                    "faculty_name": faculty_name,
                    "subject_code": subject_code,
                    "lecture_date": lecture_date,
                    "covered_topic": topic,
                    "mandatory_note": note
                }).execute()
            else:
                # If it exists, update the note and date to the most recent lecture
                supabase.table('faculty_lecture_updates').update({
                    "faculty_name": faculty_name,
                    "lecture_date": lecture_date,
                    "mandatory_note": note
                }).eq('subject_code', subject_code).eq('covered_topic', topic).execute()
            
        return jsonify({"status": "success", "message": "Successfully published updates to Database."}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/syllabus/state', methods=['GET'])
def get_syllabus_state():
    """
    Aggregates all syllabus updates into a formatted JSON state object for the frontends
    to render progress bars, completion checkmarks, and notes.
    """
    try:
        # Fetch all updates
        response = supabase.table('faculty_lecture_updates').select("*").execute()
        records = response.data
        
        state = {}
        # Reconstruct the flat SQL rows back into the nested dictionary expected by the JS application
        for row in records:
            code = row['subject_code']
            
            if code not in state:
                state[code] = {
                    "coveredTopics": [],
                    "topicNotes": {},
                    "facultyName": row['faculty_name'],
                    "lastUpdated": row['lecture_date']
                }
            
            if row['covered_topic'] not in state[code]['coveredTopics']:
                state[code]['coveredTopics'].append(row['covered_topic'])
            
            if row['mandatory_note']:
                state[code]['topicNotes'][row['covered_topic']] = row['mandatory_note']

            # Keep the most recent lecture date and faculty name as the primary display
            if row['lecture_date'] > state[code]['lastUpdated']:
                state[code]['lastUpdated'] = row['lecture_date']
                state[code]['facultyName'] = row['faculty_name']

        return jsonify({"status": "success", "data": state}), 200
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/history', methods=['GET'])
def get_history():
    """
    Fetches the latest lecture updates for the history modal in the Faculty Studio.
    """
    try:
        response = supabase.table('faculty_lecture_updates') \
            .select("subject_code, faculty_name, lecture_date") \
            .order("lecture_date", desc=True) \
            .limit(50) \
            .execute()
        
        # Format the history records
        history = []
        seen_combinations = set()
        
        for row in response.data:
            # Create a unique key to prevent spamming the history list if a teacher submitted 10 topics in 1 day
            combo_key = f"{row['subject_code']}_{row['lecture_date']}"
            if combo_key not in seen_combinations:
                history.append({
                    "code": row['subject_code'],
                    "title": "Module Update", # Optional: Map this to real titles if needed
                    "faculty": row['faculty_name'],
                    "date": row['lecture_date'],
                    "semester": "Active" 
                })
                seen_combinations.add(combo_key)
            
        return jsonify({"status": "success", "data": history}), 200
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # Binds to 0.0.0.0 to ensure it is externally accessible when hosted on Render
    app.run(host='0.0.0.0', port=5000, debug=True)
