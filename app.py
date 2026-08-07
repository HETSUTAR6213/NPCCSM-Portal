import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)  # Allows your HTML files to communicate with this API

# Initialize Supabase
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

@app.route('/api/syllabus/update', methods=['POST'])
def update_syllabus():
    data = request.json
    subject_code = data.get('subject_code')
    faculty_name = data.get('facultyName')
    lecture_date = data.get('lastUpdated')
    
    # The frontend sends a list of covered topics and a dictionary of notes
    covered_topics = data.get('coveredTopics', [])
    topic_notes = data.get('topicNotes', {})

    try:
        # Insert a row for each covered topic
        for topic in covered_topics:
            note = topic_notes.get(topic, "")
            supabase.table('faculty_lecture_updates').insert({
                "faculty_name": faculty_name,
                "subject_code": subject_code,
                "lecture_date": lecture_date,
                "covered_topic": topic,
                "mandatory_note": note
            }).execute()
            
        return jsonify({"status": "success", "message": "Successfully updated Supabase"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/syllabus/state', methods=['GET'])
def get_syllabus_state():
    # This endpoint aggregates data so the Principal and Student portals 
    # can calculate the progress bars and view notes.
    try:
        response = supabase.table('faculty_lecture_updates').select("*").execute()
        records = response.data
        
        # Transform the flat SQL rows back into the JSON state object the frontend expects
        state = {}
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

        return jsonify({"status": "success", "data": state})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/history', methods=['GET'])
def get_history():
    # Fetches the log history for the Faculty Studio modal
    try:
        response = supabase.table('faculty_lecture_updates')\
            .select("subject_code, faculty_name, lecture_date")\
            .order("lecture_date", desc=True)\
            .limit(50)\
            .execute()
        
        history = []
        for row in response.data:
            history.append({
                "code": row['subject_code'],
                "title": "Academic Subject", # Could be joined from a subjects table
                "faculty": row['faculty_name'],
                "date": row['lecture_date'],
                "semester": "N/A" 
            })
            
        return jsonify({"status": "success", "data": history})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(port=5000, debug=True)
