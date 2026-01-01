"""
Zambia PVT 2026 - Complete Production Backend
FIXED: All routes working, database auto-initializes
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

# Enhanced CORS configuration
CORS(app, 
     resources={r"/*": {"origins": "*"}},
     allow_headers=["Content-Type", "Authorization", "Access-Control-Allow-Origin"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     expose_headers=["Content-Type", "Authorization"],
     supports_credentials=True,
     send_wildcard=True,
     max_age=3600)

SECRET_KEY = os.environ.get('SECRET_KEY', 'zambia-pvt-2026-production-key')
DB_NAME = 'zambia_pvt_2026.db'

def init_database():
    """Initialize database with all tables"""
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        # Users table
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Polling stations table
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
        
        # Submissions table
        c.execute('''CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observer_id INTEGER NOT NULL,
            station_id INTEGER NOT NULL,
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
            FOREIGN KEY (observer_id) REFERENCES users (id),
            FOREIGN KEY (station_id) REFERENCES stations (id)
        )''')
        
        c.execute('CREATE INDEX IF NOT EXISTS idx_submission_status ON submissions(status)')
        
        conn.commit()
        
        # Create default users
        c.execute("SELECT COUNT(*) FROM users")
        if c.fetchone()[0] == 0:
            users = [
                ('observer1', 'obs2026', 'Demo Observer 1', '+260977111111', 'observer'),
                ('observer2', 'obs2026', 'Demo Observer 2', '+260977222222', 'observer'),
                ('observer3', 'obs2026', 'Demo Observer 3', '+260977333333', 'observer'),
                ('admin', 'admin2026', 'System Administrator', '+260977000000', 'admin'),
            ]
            
            for username, password, name, phone, role in users:
                pwd_hash = hashlib.sha256(password.encode()).hexdigest()
                c.execute("INSERT INTO users (username, password_hash, full_name, phone, role) VALUES (?, ?, ?, ?, ?)",
                         (username, pwd_hash, name, phone, role))
            
            conn.commit()
            print("✓ Users created")
        
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Database init error: {e}")
        traceback.print_exc()
        return False

def generate_stations():
    """Generate realistic Zambian polling stations"""
    province_data = {
        'Lusaka': {'count': 2196, 'districts': ['Lusaka', 'Kafue', 'Chilanga', 'Chongwe', 'Rufunsa']},
        'Copperbelt': {'count': 1952, 'districts': ['Ndola', 'Kitwe', 'Mufulira', 'Luanshya', 'Chingola']},
        'Southern': {'count': 1464, 'districts': ['Choma', 'Livingstone', 'Mazabuka', 'Monze', 'Kalomo']},
        'Eastern': {'count': 1342, 'districts': ['Chipata', 'Lundazi', 'Petauke', 'Katete', 'Chadiza']},
        'Central': {'count': 1220, 'districts': ['Kabwe', 'Kapiri Mposhi', 'Mkushi', 'Serenje', 'Mumbwa']},
        'Northern': {'count': 1220, 'districts': ['Kasama', 'Mbala', 'Mpika', 'Luwingu', 'Mporokoso']},
        'Western': {'count': 1098, 'districts': ['Mongu', 'Senanga', 'Kalabo', 'Lukulu', 'Kaoma']},
        'Luapula': {'count': 976, 'districts': ['Mansa', 'Kawambwa', 'Nchelenge', 'Mwense', 'Samfya']},
        'North-Western': {'count': 854, 'districts': ['Solwezi', 'Mwinilunga', 'Zambezi', 'Kabompo', 'Kasempa']},
        'Muchinga': {'count': 854, 'districts': ['Chinsali', 'Isoka', 'Nakonde', 'Mpulungu', 'Shiwangandu']}
    }
    
    venues = ['Primary School', 'Secondary School', 'Community Hall', 'Civic Centre', 
              'Health Centre', 'Church', 'Market', 'Youth Centre']
    
    stations = []
    station_id = 1
    
    for province, data in province_data.items():
        districts = data['districts']
        target = data['count']
        per_district = target // len(districts)
        
        for dist_idx, district in enumerate(districts):
            district_count = per_district + (target % len(districts) if dist_idx == 0 else 0)
            
            for i in range(district_count):
                constituency = f"{district} Constituency"
                ward = f"Ward {(i % 10) + 1}"
                venue = venues[i % len(venues)]
                
                stations.append({
                    'code': f"{province[:3].upper()}{station_id:05d}",
                    'name': f"{district} {venue} {(i % 5) + 1}",
                    'province': province,
                    'district': district,
                    'constituency': constituency,
                    'ward': ward,
                    'registered_voters': 800 + (i * 17) % 1700,
                    'latitude': -15.0 + (station_id % 1000) * 0.01,
                    'longitude': 28.0 + (station_id % 1000) * 0.01
                })
                station_id += 1
    
    return stations

def load_stations():
    """Load polling stations into database"""
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM stations")
        existing = c.fetchone()[0]
        
        if existing > 0:
            print(f"✓ Database has {existing:,} stations")
            conn.close()
            return True
        
        print("Generating 12,200 polling stations...")
        stations = generate_stations()
        
        for station in stations:
            c.execute("""INSERT INTO stations 
                        (code, name, province, district, constituency, ward, registered_voters, latitude, longitude)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                     (station['code'], station['name'], station['province'], station['district'],
                      station['constituency'], station['ward'], station['registered_voters'],
                      station['latitude'], station['longitude']))
        
        conn.commit()
        conn.close()
        print(f"✓ Loaded {len(stations):,} polling stations")
        return True
    except Exception as e:
        print(f"❌ Station load error: {e}")
        traceback.print_exc()
        return False

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
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
    stations_success = load_stations()
    
    if stations_success:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM stations")
        station_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users")
        user_count = c.fetchone()[0]
        conn.close()
        
        print(f"✅ System Ready")
        print(f"   Stations: {station_count:,}")
        print(f"   Users: {user_count}")
        print("=" * 70)

# ==================== ROUTES ====================

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'name': 'Zambia PVT 2026 API',
        'status': 'operational',
        'version': '1.0.0',
        'endpoints': {
            'status': '/api/status',
            'login': '/api/login',
            'provinces': '/api/provinces',
            'stations': '/api/stations',
            'submit': '/api/submit',
            'submissions': '/api/submissions',
            'results': '/api/results',
            'stats': '/api/stats'
        }
    })

@app.route('/api/status', methods=['GET', 'OPTIONS'])
def status():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM stations")
        stations = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM submissions")
        submissions = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
        conn.close()
        
        return jsonify({
            'name': 'Zambia PVT 2026',
            'status': 'operational',
            'version': '1.0.0',
            'stations': stations,
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
        return '', 204
    
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
        c.execute("SELECT * FROM users WHERE username = ? AND password_hash = ?", (username, password_hash))
        user = c.fetchone()
        conn.close()
        
        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401
        
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
                'role': user['role']
            }
        })
    except Exception as e:
        return jsonify({'error': 'Login failed', 'details': str(e)}), 500

@app.route('/api/provinces', methods=['GET', 'OPTIONS'])
@token_required
def get_provinces(current_user):
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT DISTINCT province FROM stations ORDER BY province")
        provinces = [row[0] for row in c.fetchall()]
        conn.close()
        return jsonify({'provinces': provinces})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stations', methods=['GET', 'OPTIONS'])
@token_required
def get_stations(current_user):
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        province = request.args.get('province')
        
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        if province:
            c.execute("SELECT * FROM stations WHERE province = ? ORDER BY code LIMIT 500", (province,))
        else:
            c.execute("SELECT * FROM stations ORDER BY code LIMIT 100")
        
        stations = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify({'stations': stations})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/submit', methods=['POST', 'OPTIONS'])
@token_required
def submit_results(current_user):
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.get_json()
        
        required = ['station_id', 'gps_lat', 'gps_lon', 'presidential', 'parliamentary', 'council']
        if not all(field in data for field in required):
            return jsonify({'error': 'Missing required fields'}), 400
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        # Check for duplicate
        c.execute("SELECT id FROM submissions WHERE observer_id = ? AND station_id = ?",
                  (current_user['id'], data['station_id']))
        if c.fetchone():
            conn.close()
            return jsonify({'error': 'Already submitted for this station'}), 400
        
        c.execute("""INSERT INTO submissions 
                    (observer_id, station_id, gps_lat, gps_lon, 
                     presidential_data, parliamentary_data, council_data, photos, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                  (current_user['id'], data['station_id'], data['gps_lat'], data['gps_lon'],
                   json.dumps(data['presidential']), json.dumps(data['parliamentary']),
                   json.dumps(data['council']), json.dumps(data.get('photos', []))))
        
        submission_id = c.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': 'Submitted successfully', 
            'submission_id': submission_id
        }), 201
    except Exception as e:
        return jsonify({'error': 'Submission failed', 'details': str(e)}), 500

@app.route('/api/submissions', methods=['GET', 'OPTIONS'])
@token_required
def get_submissions(current_user):
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        status = request.args.get('status', 'all')
        
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        if current_user['role'] == 'observer':
            query = """SELECT s.*, st.code, st.name, st.province, st.district
                       FROM submissions s
                       JOIN stations st ON s.station_id = st.id
                       WHERE s.observer_id = ?"""
            params = [current_user['id']]
        else:
            query = """SELECT s.*, st.code, st.name, st.province, st.district,
                              u.full_name as observer_name, u.phone as observer_phone
                       FROM submissions s
                       JOIN stations st ON s.station_id = st.id
                       JOIN users u ON s.observer_id = u.id
                       WHERE 1=1"""
            params = []
        
        if status != 'all':
            query += " AND s.status = ?"
            params.append(status)
        
        query += " ORDER BY s.submitted_at DESC"
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
        return '', 204
    
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute("""SELECT s.*, st.*, u.full_name as observer_name, u.phone as observer_phone
                     FROM submissions s
                     JOIN stations st ON s.station_id = st.id
                     JOIN users u ON s.observer_id = u.id
                     WHERE s.id = ?""", (id,))
        
        submission = c.fetchone()
        conn.close()
        
        if not submission:
            return jsonify({'error': 'Not found'}), 404
        
        result = dict(submission)
        result['presidential'] = json.loads(result['presidential_data'])
        result['parliamentary'] = json.loads(result['parliamentary_data'])
        result['council'] = json.loads(result['council_data'])
        result['photos'] = json.loads(result['photos']) if result['photos'] else []
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/submissions/<int:id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_submission(current_user, id):
    if request.method == 'OPTIONS':
        return '', 204
    
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
        return '', 204
    
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

@app.route('/api/results', methods=['GET', 'OPTIONS'])
@token_required
def get_results(current_user):
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        election_type = request.args.get('type', 'presidential')
        province = request.args.get('province')
        
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        if province:
            c.execute("""SELECT s.presidential_data, s.parliamentary_data, s.council_data
                         FROM submissions s
                         JOIN stations st ON s.station_id = st.id
                         WHERE s.status = 'approved' AND st.province = ?""", (province,))
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
        return '', 204
    
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM stations")
        total_stations = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM submissions")
        total_submissions = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM submissions WHERE status = 'pending'")
        pending = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM submissions WHERE status = 'approved'")
        approved = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM submissions WHERE status = 'rejected'")
        rejected = c.fetchone()[0]
        
        c.execute("""SELECT st.province, COUNT(DISTINCT s.station_id) as count
                     FROM stations st
                     LEFT JOIN submissions s ON st.id = s.station_id AND s.status = 'approved'
                     GROUP BY st.province ORDER BY st.province""")
        provinces = [{'province': row[0], 'count': row[1]} for row in c.fetchall()]
        
        conn.close()
        
        return jsonify({
            'total_stations': total_stations,
            'total_submissions': total_submissions,
            'pending': pending,
            'approved': approved,
            'rejected': rejected,
            'coverage': round((approved / total_stations * 100), 2) if total_stations > 0 else 0,
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