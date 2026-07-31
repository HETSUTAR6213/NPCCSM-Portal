import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client

# Load secrets from the .env file
load_dotenv()

app = Flask(__name__)
# CORS allows your hosted HTML file to talk to this Python server
CORS(app)

# Initialize Supabase connection
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("WARNING: Supabase URL or Key is missing. Check your .env file.")
    
supabase: Client = create_client(url, key)

@app.route('/api/syllabus/state', methods=['GET'])
def get_state():
    """
    Called when the frontend loads. Fetches all syllabus progress from Supabase.
    """
    try:
        # Fetch all rows from the syllabus_state table
        response = supabase.table('syllabus_state').select('*').execute()
        
        # Format the data exactly how the HTML JavaScript expects it
        state_data = {}
        for row in response.data:
            state_data[row['subject_code']] = row['data']
            
        return jsonify({
            'status': 'success',
            'data': state_data
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/syllabus/update', methods=['POST'])
def update_syllabus():
    """
    Called when a Faculty member clicks "Update & Publish".
    """
    try:
        payload = request.json
        subject_code = payload.get('subject_code')
        
        if not subject_code:
            return jsonify({'status': 'error', 'message': 'Missing subject_code'}), 400

        # 1. Update or Insert the current progress into syllabus_state table
        # Supabase 'upsert' acts just like MongoDB's upsert.
        supabase.table('syllabus_state').upsert({
            'subject_code': subject_code,
            'data': payload
        }).execute()

        # 2. Insert a permanent log into the update_history table
        history_entry = {
            'code': subject_code,
            'title': payload.get('title'),
            'date': payload.get('lastUpdated'),
            'faculty': payload.get('facultyName'),
            'semester': payload.get('semester')
        }
        supabase.table('update_history').insert(history_entry).execute()

        return jsonify({'status': 'success', 'message': 'Saved to Supabase successfully'}), 200
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/history', methods=['GET'])
def get_history():
    """
    Called when clicking "Class Update Logs".
    Fetches the history from Supabase, ordered newest first.
    """
    try:
        # Fetch history ordered by ID descending (newest on top)
        response = supabase.table('update_history').select('*').order('id', desc=True).execute()
        
        return jsonify({
            'status': 'success',
            'data': response.data
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    print("--- NPCCSM Supabase Backend Running ---")
    app.run(host='0.0.0.0', port=5000, debug=True)