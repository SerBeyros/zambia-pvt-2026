"""
Zambia PVT 2026 - Complete Production Backend
Updated Version with Observer Management & Manual Station Entry
Deploy to Render.com
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import jwt
import hashlib
from datetime import datetime, timedelta
from functools import wraps
import json
import os
import traceback

app = Flask(__name__, static_folder='.')

# CORS configuration
CORS(app)

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

SECRET_KEY = os.environ.get('SECRET_KEY', 'zambia-pvt-2026-production-key')
DB_NAME = 'zambia_pvt_2026.db'

def init_database():
    """Initialize database with all tables"""
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        # Users table with additional observer fields
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            national_id TEXT,
            organization TEXT,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER,
            is_active INTEGER DEFAULT 1
        )''')
        
        # Polling stations table (kept for future use, not currently used)
        c.execute('''CREATE TABLE IF NOT EXISTS stations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            province TEXT NOT NULL,
            district TEXT NOT NULL,
            constituency TEXT NOT NULL,
            ward TEXT NOT NULL,
            registered_voters INTEGER NOT NULL,
            latitude REAL,
            longitude REAL
        )''')
        
        c.execute('CREATE INDEX IF NOT EXISTS idx_station_province ON stations(province)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_station_code ON stations(code)')
        
        # Submissions table with observer info and manual station entry
        c.execute('''CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observer_id INTEGER NOT NULL,
            observer_full_name TEXT NOT NULL,
            observer_phone TEXT NOT NULL,
            observer_email TEXT,
            observer_national_id TEXT,
            province TEXT NOT NULL,
            district TEXT NOT NULL,
            town TEXT,
            constituency TEXT NOT NULL,
            ward TEXT NOT NULL,
            polling_station TEXT NOT NULL,
            gps_lat REAL NOT NULL,
            gps_lon REAL NOT NULL,
            presidential_data TEXT NOT NULL,
            parliamentary_data TEXT NOT NULL,
            council_data TEXT NOT NULL,
            photos TEXT,
            status TEXT DEFAULT 'pending',
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at TIMESTAMP,
            approved_by INTEGER,
            FOREIGN KEY (observer_id) REFERENCES users (id)
        )''')
        
        c.execute('CREATE INDEX IF NOT EXISTS idx_submission_status ON submissions(status)')
        
        conn.commit()
        
        # Create default admin user
        c.execute("SELECT COUNT(*) FROM users")
        if c.fetchone()[0] == 0:
            users = [
                ('admin', 'admin2026', 'System Administrator', '+260977000000', 'admin@pvt.zm', None, 'Electoral Commission', 'admin'),
            ]
            
            for username, password, name, phone, email, nid, org, role in users:
                pwd_hash = hashlib.sha256(password.encode()).hexdigest()
                c.execute("INSERT INTO users (username, password_hash, full_name, phone, email, national_id, organization, role, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                         (username, pwd_hash, name, phone, email, nid, org, role))
            
            conn.commit()
            print("✓ Admin user created")
        
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Database init error: {e}")
        traceback.print_exc()
        return False

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Allow OPTIONS requests without authentication
        if request.method == 'OPTIONS':
            return '', 200
            
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'error': 'Token missing'}), 401
        
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            
            conn = sqlite3.connect(DB_NAME)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE id = ?", (data['user_id'],))
            user = c.fetchone()
            conn.close()
            
            if not user:
                return jsonify({'error': 'Invalid token'}), 401
            
            return f(dict(user), *args, **kwargs)
        except Exception as e:
            return jsonify({'error': 'Invalid token', 'details': str(e)}), 401
    
    return decorated

# ==================== INITIALIZE ON STARTUP ====================
print("=" * 70)
print("🗳️  ZAMBIA PVT 2026 - INITIALIZING...")
print("=" * 70)

init_success = init_database()

if init_success:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE role = 'observer'")
    observer_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users")
    user_count = c.fetchone()[0]
    conn.close()
    
    print(f"✅ System Ready")
    print(f"   Total Users: {user_count}")
    print(f"   Observers: {observer_count}")
    print("=" * 70)

# ==================== ROUTES ====================

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'name': 'Zambia PVT 2026 API',
        'status': 'operational',
        'version': '2.0.0',
        'endpoints': {
            'status': '/api/status',
            'login': '/api/login',
            'observers': '/api/observers',
            'submit': '/api/submit',
            'submissions': '/api/submissions',
            'results': '/api/results',
            'stats': '/api/stats'
        }
    })

@app.route('/api/status', methods=['GET', 'OPTIONS'])
def status():
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE role = 'observer'")
        observers = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM submissions")
        submissions = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
        conn.close()
        
        return jsonify({
            'name': 'Zambia PVT 2026',
            'status': 'operational',
            'version': '2.0.0',
            'observers': observers,
            'submissions': submissions,
            'users': users
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/api/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400
        
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ? AND password_hash = ? AND is_active = 1", (username, password_hash))
        user = c.fetchone()
        conn.close()
        
        if not user:
            return jsonify({'error': 'Invalid credentials or account disabled'}), 401
        
        token = jwt.encode({
            'user_id': user['id'],
            'exp': datetime.utcnow() + timedelta(days=30)
        }, SECRET_KEY, algorithm='HS256')
        
        return jsonify({
            'token': token,
            'user': {
                'id': user['id'],
                'username': user['username'],
                'full_name': user['full_name'],
                'phone': user['phone'],
                'email': user['email'],
                'national_id': user['national_id'],
                'organization': user['organization'],
                'role': user['role']
            }
        })
    except Exception as e:
        return jsonify({'error': 'Login failed', 'details': str(e)}), 500

# ==================== OBSERVER MANAGEMENT ====================

@app.route('/api/observers', methods=['GET', 'OPTIONS'])
@token_required
def get_observers(current_user):
    if request.method == 'OPTIONS':
        return '', 200
    
    if current_user['role'] != 'admin':
        return jsonify({'error': 'Admin access only'}), 403
    
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""SELECT id, username, full_name, phone, email, national_id, organization, 
                            is_active, created_at FROM users WHERE role = 'observer' ORDER BY created_at DESC""")
        observers = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify({'observers': observers})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/observers', methods=['POST'])
@token_required
def create_observer(current_user):
    if current_user['role'] != 'admin':
        return jsonify({'error': 'Admin access only'}), 403
    
    try:
        data = request.get_json()
        
        required = ['username', 'password', 'full_name', 'phone']
        if not all(field in data for field in required):
            return jsonify({'error': 'Missing required fields'}), 400
        
        password_hash = hashlib.sha256(data['password'].encode()).hexdigest()
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        # Check if username exists
        c.execute("SELECT id FROM users WHERE username = ?", (data['username'],))
        if c.fetchone():
            conn.close()
            return jsonify({'error': 'Username already exists'}), 400
        
        c.execute("""INSERT INTO users 
                    (username, password_hash, full_name, phone, email, national_id, organization, role, created_by, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'observer', ?, 1)""",
                 (data['username'], password_hash, data['full_name'], data['phone'], 
                  data.get('email'), data.get('national_id'), data.get('organization'), current_user['id']))
        
        observer_id = c.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': 'Observer created successfully',
            'observer_id': observer_id
        }), 201
    except Exception as e:
        return jsonify({'error': 'Failed to create observer', 'details': str(e)}), 500

@app.route('/api/observers/<int:id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_observer(current_user, id):
    if request.method == 'OPTIONS':
        return '', 200
    
    if current_user['role'] != 'admin':
        return jsonify({'error': 'Admin access only'}), 403
    
    try:
        data = request.get_json()
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        # Build update query dynamically
        updates = []
        params = []
        
        if 'full_name' in data:
            updates.append('full_name = ?')
            params.append(data['full_name'])
        if 'phone' in data:
            updates.append('phone = ?')
            params.append(data['phone'])
        if 'email' in data:
            updates.append('email = ?')
            params.append(data['email'])
        if 'national_id' in data:
            updates.append('national_id = ?')
            params.append(data['national_id'])
        if 'organization' in data:
            updates.append('organization = ?')
            params.append(data['organization'])
        if 'is_active' in data:
            updates.append('is_active = ?')
            params.append(1 if data['is_active'] else 0)
        if 'password' in data:
            updates.append('password_hash = ?')
            params.append(hashlib.sha256(data['password'].encode()).hexdigest())
        
        if not updates:
            return jsonify({'error': 'No fields to update'}), 400
        
        params.append(id)
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = ? AND role = 'observer'"
        c.execute(query, params)
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Observer updated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/observers/<int:id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_observer(current_user, id):
    if request.method == 'OPTIONS':
        return '', 200
    
    if current_user['role'] != 'admin':
        return jsonify({'error': 'Admin access only'}), 403
    
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("UPDATE users SET is_active = 0 WHERE id = ? AND role = 'observer'", (id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Observer deactivated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== SUBMISSIONS ====================

@app.route('/api/submit', methods=['POST', 'OPTIONS'])
@token_required
def submit_results(current_user):
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        
        required = ['observer_full_name', 'observer_phone', 'province', 'district', 
                   'constituency', 'ward', 'polling_station', 'gps_lat', 'gps_lon', 
                   'presidential', 'parliamentary', 'council']
        if not all(field in data for field in required):
            missing = [f for f in required if f not in data]
            return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        # Check for duplicate submission from same observer at same station
        c.execute("""SELECT id FROM submissions 
                    WHERE observer_id = ? AND province = ? AND district = ? 
                    AND constituency = ? AND ward = ? AND polling_station = ?""",
                 (current_user['id'], data['province'], data['district'], 
                  data['constituency'], data['ward'], data['polling_station']))
        if c.fetchone():
            conn.close()
            return jsonify({'error': 'You have already submitted results for this polling station'}), 400
        
        c.execute("""INSERT INTO submissions 
                    (observer_id, observer_full_name, observer_phone, observer_email, observer_national_id,
                     province, district, town, constituency, ward, polling_station,
                     gps_lat, gps_lon, presidential_data, parliamentary_data, council_data, photos, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                 (current_user['id'], data['observer_full_name'], data['observer_phone'], 
                  data.get('observer_email'), data.get('observer_national_id'),
                  data['province'], data['district'], data.get('town'), 
                  data['constituency'], data['ward'], data['polling_station'],
                  data['gps_lat'], data['gps_lon'],
                  json.dumps(data['presidential']), json.dumps(data['parliamentary']),
                  json.dumps(data['council']), json.dumps(data.get('photos', []))))
        
        submission_id = c.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': 'Results submitted successfully', 
            'submission_id': submission_id
        }), 201
    except Exception as e:
        print(f"Submit error: {str(e)}")
        return jsonify({'error': 'Submission failed', 'details': str(e)}), 500

@app.route('/api/submissions', methods=['GET', 'OPTIONS'])
@token_required
def get_submissions(current_user):
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        status = request.args.get('status', 'all')
        
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        if current_user['role'] == 'observer':
            query = """SELECT * FROM submissions WHERE observer_id = ?"""
            params = [current_user['id']]
        else:
            query = """SELECT * FROM submissions WHERE 1=1"""
            params = []
        
        if status != 'all':
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY submitted_at DESC"
        c.execute(query, params)
        submissions = [dict(row) for row in c.fetchall()]
        conn.close()
        
        return jsonify({'submissions': submissions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/submissions/<int:id>', methods=['GET', 'OPTIONS'])
@token_required
def get_submission_detail(current_user, id):
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute("SELECT * FROM submissions WHERE id = ?", (id,))
        
        submission = c.fetchone()
        conn.close()
        
        if not submission:
            return jsonify({'error': 'Submission not found'}), 404
        
        result = dict(submission)
        
        # Parse JSON fields
        try:
            result['presidential'] = json.loads(result['presidential_data'])
        except:
            result['presidential'] = []
            
        try:
            result['parliamentary'] = json.loads(result['parliamentary_data'])
        except:
            result['parliamentary'] = []
            
        try:
            result['council'] = json.loads(result['council_data'])
        except:
            result['council'] = []
            
        try:
            result['photos'] = json.loads(result['photos']) if result['photos'] else []
        except:
            result['photos'] = []
        
        # Remove the _data fields from response
        result.pop('presidential_data', None)
        result.pop('parliamentary_data', None)
        result.pop('council_data', None)
        
        return jsonify(result)
    except Exception as e:
        print(f"Error loading submission {id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/submissions/<int:id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_submission(current_user, id):
    if request.method == 'OPTIONS':
        return '', 200
    
    if current_user['role'] != 'admin':
        return jsonify({'error': 'Admin only'}), 403
    
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("UPDATE submissions SET status = 'approved', approved_at = CURRENT_TIMESTAMP, approved_by = ? WHERE id = ?",
                  (current_user['id'], id))
        conn.commit()
        conn.close()
        
        return jsonify({'message': 'Approved successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/submissions/<int:id>/reject', methods=['POST', 'OPTIONS'])
@token_required
def reject_submission(current_user, id):
    if request.method == 'OPTIONS':
        return '', 200
    
    if current_user['role'] != 'admin':
        return jsonify({'error': 'Admin only'}), 403
    
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("UPDATE submissions SET status = 'rejected', approved_at = CURRENT_TIMESTAMP, approved_by = ? WHERE id = ?",
                  (current_user['id'], id))
        conn.commit()
        conn.close()
        
        return jsonify({'message': 'Rejected successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== RESULTS & STATS ====================

@app.route('/api/results', methods=['GET', 'OPTIONS'])
@token_required
def get_results(current_user):
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        election_type = request.args.get('type', 'presidential')
        province = request.args.get('province')
        
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        if province:
            c.execute("""SELECT presidential_data, parliamentary_data, council_data
                         FROM submissions
                         WHERE status = 'approved' AND province = ?""", (province,))
        else:
            c.execute("SELECT presidential_data, parliamentary_data, council_data FROM submissions WHERE status = 'approved'")
        
        results = {}
        total_votes = 0
        
        for row in c.fetchall():
            if election_type == 'presidential':
                data = json.loads(row['presidential_data'])
            elif election_type == 'parliamentary':
                data = json.loads(row['parliamentary_data'])
            else:
                data = json.loads(row['council_data'])
            
            for candidate in data:
                key = f"{candidate['candidate']}|{candidate['party']}"
                results[key] = results.get(key, 0) + candidate['votes']
                total_votes += candidate['votes']
        
        conn.close()
        
        formatted = []
        for key, votes in sorted(results.items(), key=lambda x: x[1], reverse=True):
            candidate, party = key.split('|')
            percentage = (votes / total_votes * 100) if total_votes > 0 else 0
            formatted.append({'candidate': candidate, 'party': party, 'votes': votes, 'percentage': round(percentage, 2)})
        
        return jsonify({'election_type': election_type, 'results': formatted, 'total_votes': total_votes})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_stats(current_user):
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM users WHERE role = 'observer'")
        total_observers = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM submissions")
        total_submissions = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM submissions WHERE status = 'pending'")
        pending = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM submissions WHERE status = 'approved'")
        approved = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM submissions WHERE status = 'rejected'")
        rejected = c.fetchone()[0]
        
        c.execute("""SELECT province, COUNT(*) as count
                     FROM submissions
                     WHERE status = 'approved'
                     GROUP BY province 
                     ORDER BY province""")
        provinces = [{'province': row[0], 'count': row[1]} for row in c.fetchall()]
        
        conn.close()
        
        return jsonify({
            'total_observers': total_observers,
            'total_submissions': total_submissions,
            'pending': pending,
            'approved': approved,
            'rejected': rejected,
            'provinces': provinces
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error', 'details': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)