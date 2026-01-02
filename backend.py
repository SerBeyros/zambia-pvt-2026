"""
Zambia PVT 2026 - Complete Production Backend
SECURITY HARDENED VERSION
Deploy to Render.com
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
from functools import wraps
import json
import os
import traceback
import re
from collections import defaultdict
import time

app = Flask(__name__, static_folder='.')

# SECURITY: CORS configuration - restrict to specific origins
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '').split(',')
if not ALLOWED_ORIGINS or ALLOWED_ORIGINS == ['']:
    # Default for development - MUST be overridden in production
    ALLOWED_ORIGINS = ['http://localhost:3000', 'http://localhost:5000']

CORS(app, origins=ALLOWED_ORIGINS)

@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin in ALLOWED_ORIGINS:
        response.headers.add('Access-Control-Allow-Origin', origin)
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

# SECURITY: Enforce strong secret key from environment
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError("CRITICAL: SECRET_KEY environment variable must be set. Generate with: python -c 'import secrets; print(secrets.token_hex(32))'")

DB_NAME = 'zambia_pvt_2026.db'

# Rate limiting storage (in production, use Redis)
login_attempts = defaultdict(list)
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = 300  # 5 minutes

# JWT Configuration
JWT_EXPIRY_HOURS = 8  # Reduced from 30 days to 8 hours
JWT_ALGORITHM = 'HS256'

def get_db():
    """Get database connection with row factory"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Initialize database with all tables"""
    try:
        with get_db() as conn:
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

            # Polling stations table (kept for future use)
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

            # Audit log table
            c.execute('''CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT NOT NULL,
                resource_type TEXT,
                resource_id INTEGER,
                details TEXT,
                ip_address TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')

            c.execute('CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)')

            conn.commit()

            # Check if admin user exists
            c.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
            if c.fetchone()[0] == 0:
                print("=" * 70)
                print("⚠️  NO ADMIN USER FOUND")
                print("=" * 70)
                print("Create admin user by running:")
                print("python create_admin.py")
                print("=" * 70)

        return True
    except Exception as e:
        print(f"❌ Database init error: {e}")
        traceback.print_exc()
        return False

def validate_password_strength(password):
    """Validate password meets minimum security requirements"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r'[A-Za-z]', password):
        return False, "Password must contain at least one letter"
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    return True, ""

def hash_password(password):
    """Hash password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, password_hash):
    """Verify password against bcrypt hash"""
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

def validate_gps_coordinates(lat, lon):
    """Validate GPS coordinates are within valid ranges"""
    try:
        lat = float(lat)
        lon = float(lon)
        if lat < -90 or lat > 90:
            return False, "Latitude must be between -90 and 90"
        if lon < -180 or lon > 180:
            return False, "Longitude must be between -180 and 180"
        return True, (lat, lon)
    except (ValueError, TypeError):
        return False, "Invalid GPS coordinates"

def validate_votes(votes):
    """Validate vote count is a non-negative integer"""
    try:
        votes = int(votes)
        if votes < 0:
            return False, "Vote count cannot be negative"
        if votes > 100000:
            return False, "Vote count seems unreasonably high"
        return True, votes
    except (ValueError, TypeError):
        return False, "Invalid vote count"

def validate_text_field(text, field_name, max_length=200):
    """Validate text field length and content"""
    if not text or not text.strip():
        return False, f"{field_name} cannot be empty"
    if len(text) > max_length:
        return False, f"{field_name} is too long (max {max_length} characters)"
    return True, text.strip()

def log_audit(user_id, action, resource_type=None, resource_id=None, details=None):
    """Log admin action to audit trail"""
    try:
        with get_db() as conn:
            c = conn.cursor()
            ip_address = request.remote_addr if request else None
            c.execute("""INSERT INTO audit_log
                        (user_id, action, resource_type, resource_id, details, ip_address)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                     (user_id, action, resource_type, resource_id, details, ip_address))
            conn.commit()
    except Exception as e:
        print(f"Audit log error: {e}")

def check_rate_limit(identifier):
    """Check if identifier is rate limited"""
    now = time.time()
    # Clean old attempts
    login_attempts[identifier] = [
        attempt_time for attempt_time in login_attempts[identifier]
        if now - attempt_time < LOCKOUT_DURATION
    ]

    if len(login_attempts[identifier]) >= MAX_LOGIN_ATTEMPTS:
        return False, LOCKOUT_DURATION - (now - login_attempts[identifier][0])

    return True, 0

def record_login_attempt(identifier):
    """Record a failed login attempt"""
    login_attempts[identifier].append(time.time())

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Allow OPTIONS requests without authentication
        if request.method == 'OPTIONS':
            return '', 200

        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'error': 'Authentication required'}), 401

        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])

            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE id = ? AND is_active = 1", (data['user_id'],))
                user = c.fetchone()

            if not user:
                return jsonify({'error': 'Invalid authentication'}), 401

            return f(dict(user), *args, **kwargs)
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        except Exception:
            return jsonify({'error': 'Authentication failed'}), 401

    return decorated

# HTTPS enforcement middleware
@app.before_request
def enforce_https():
    """Enforce HTTPS in production"""
    if os.environ.get('FLASK_ENV') == 'production':
        if request.headers.get('X-Forwarded-Proto', 'http') != 'https':
            return jsonify({'error': 'HTTPS required'}), 403

# ==================== INITIALIZE ON STARTUP ====================
print("=" * 70)
print("🗳️  ZAMBIA PVT 2026 - INITIALIZING (SECURITY HARDENED)...")
print("=" * 70)

init_success = init_database()

if init_success:
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE role = 'observer'")
        observer_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users")
        user_count = c.fetchone()[0]

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
        'version': '2.1.0',
        'security': 'hardened',
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
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM users WHERE role = 'observer'")
            observers = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM submissions")
            submissions = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users")
            users = c.fetchone()[0]

        return jsonify({
            'name': 'Zambia PVT 2026',
            'status': 'operational',
            'version': '2.1.0',
            'observers': observers,
            'submissions': submissions,
            'users': users
        })
    except Exception:
        return jsonify({'status': 'error'}), 500

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

        # Rate limiting by IP address
        client_ip = request.remote_addr
        allowed, wait_time = check_rate_limit(client_ip)
        if not allowed:
            return jsonify({'error': f'Too many login attempts. Try again in {int(wait_time)} seconds'}), 429

        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE username = ? AND is_active = 1", (username,))
            user = c.fetchone()

        if not user or not verify_password(password, user['password_hash']):
            record_login_attempt(client_ip)
            log_audit(None, 'failed_login', details=f"Username: {username}, IP: {client_ip}")
            return jsonify({'error': 'Invalid credentials'}), 401

        # Clear rate limit on successful login
        if client_ip in login_attempts:
            del login_attempts[client_ip]

        token = jwt.encode({
            'user_id': user['id'],
            'exp': datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)
        }, SECRET_KEY, algorithm=JWT_ALGORITHM)

        log_audit(user['id'], 'login', details=f"IP: {client_ip}")

        return jsonify({
            'token': token,
            'expires_in': JWT_EXPIRY_HOURS * 3600,
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
        print(f"Login error: {e}")
        return jsonify({'error': 'Login failed'}), 500

# ==================== OBSERVER MANAGEMENT ====================

@app.route('/api/observers', methods=['GET', 'OPTIONS'])
@token_required
def get_observers(current_user):
    if request.method == 'OPTIONS':
        return '', 200

    if current_user['role'] != 'admin':
        return jsonify({'error': 'Access denied'}), 403

    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""SELECT id, username, full_name, phone, email, national_id, organization,
                                is_active, created_at FROM users WHERE role = 'observer' ORDER BY created_at DESC""")
            observers = [dict(row) for row in c.fetchall()]
        return jsonify({'observers': observers})
    except Exception:
        return jsonify({'error': 'Failed to load observers'}), 500

@app.route('/api/observers', methods=['POST'])
@token_required
def create_observer(current_user):
    if current_user['role'] != 'admin':
        return jsonify({'error': 'Access denied'}), 403

    try:
        data = request.get_json()

        required = ['username', 'password', 'full_name', 'phone']
        if not all(field in data for field in required):
            return jsonify({'error': 'Missing required fields'}), 400

        # Validate username
        username = data['username'].strip()
        if not username or len(username) < 3:
            return jsonify({'error': 'Username must be at least 3 characters'}), 400

        # Validate password strength
        valid, error_msg = validate_password_strength(data['password'])
        if not valid:
            return jsonify({'error': error_msg}), 400

        # Validate fields
        valid, full_name = validate_text_field(data['full_name'], 'Full name', 100)
        if not valid:
            return jsonify({'error': full_name}), 400

        valid, phone = validate_text_field(data['phone'], 'Phone', 20)
        if not valid:
            return jsonify({'error': phone}), 400

        password_hash = hash_password(data['password'])

        with get_db() as conn:
            c = conn.cursor()

            # Check if username exists
            c.execute("SELECT id FROM users WHERE username = ?", (username,))
            if c.fetchone():
                return jsonify({'error': 'Username already exists'}), 400

            c.execute("""INSERT INTO users
                        (username, password_hash, full_name, phone, email, national_id, organization, role, created_by, is_active)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'observer', ?, 1)""",
                     (username, password_hash, full_name, phone,
                      data.get('email'), data.get('national_id'), data.get('organization'), current_user['id']))

            observer_id = c.lastrowid
            conn.commit()

            log_audit(current_user['id'], 'create_observer', 'user', observer_id,
                     f"Created observer: {username}")

        return jsonify({
            'success': True,
            'message': 'Observer created successfully',
            'observer_id': observer_id
        }), 201
    except Exception as e:
        print(f"Create observer error: {e}")
        return jsonify({'error': 'Failed to create observer'}), 500

@app.route('/api/observers/<int:id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_observer(current_user, id):
    if request.method == 'OPTIONS':
        return '', 200

    if current_user['role'] != 'admin':
        return jsonify({'error': 'Access denied'}), 403

    try:
        data = request.get_json()

        # Allowed fields for update
        allowed_fields = {
            'full_name': 'full_name',
            'phone': 'phone',
            'email': 'email',
            'national_id': 'national_id',
            'organization': 'organization',
            'is_active': 'is_active'
        }

        updates = []
        params = []

        for field, db_column in allowed_fields.items():
            if field in data:
                if field == 'is_active':
                    updates.append('is_active = ?')
                    params.append(1 if data[field] else 0)
                elif field == 'full_name' or field == 'phone':
                    valid, value = validate_text_field(data[field], field.replace('_', ' ').title(), 200)
                    if not valid:
                        return jsonify({'error': value}), 400
                    updates.append(f'{db_column} = ?')
                    params.append(value)
                else:
                    updates.append(f'{db_column} = ?')
                    params.append(data[field])

        if 'password' in data:
            valid, error_msg = validate_password_strength(data['password'])
            if not valid:
                return jsonify({'error': error_msg}), 400
            updates.append('password_hash = ?')
            params.append(hash_password(data['password']))

        if not updates:
            return jsonify({'error': 'No fields to update'}), 400

        params.append(id)
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = ? AND role = 'observer'"

        with get_db() as conn:
            c = conn.cursor()
            c.execute(query, params)
            conn.commit()

            log_audit(current_user['id'], 'update_observer', 'user', id,
                     f"Updated fields: {', '.join(data.keys())}")

        return jsonify({'success': True, 'message': 'Observer updated successfully'})
    except Exception as e:
        print(f"Update observer error: {e}")
        return jsonify({'error': 'Failed to update observer'}), 500

@app.route('/api/observers/<int:id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_observer(current_user, id):
    if request.method == 'OPTIONS':
        return '', 200

    if current_user['role'] != 'admin':
        return jsonify({'error': 'Access denied'}), 403

    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET is_active = 0 WHERE id = ? AND role = 'observer'", (id,))
            conn.commit()

            log_audit(current_user['id'], 'deactivate_observer', 'user', id)

        return jsonify({'success': True, 'message': 'Observer deactivated successfully'})
    except Exception:
        return jsonify({'error': 'Failed to deactivate observer'}), 500

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

        # Validate text fields
        for field in ['province', 'district', 'constituency', 'ward', 'polling_station']:
            valid, value = validate_text_field(data[field], field.replace('_', ' ').title(), 200)
            if not valid:
                return jsonify({'error': value}), 400
            data[field] = value

        # Validate GPS coordinates
        valid, coords = validate_gps_coordinates(data['gps_lat'], data['gps_lon'])
        if not valid:
            return jsonify({'error': coords}), 400
        gps_lat, gps_lon = coords

        # Validate candidate data
        for election_type in ['presidential', 'parliamentary', 'council']:
            candidates = data[election_type]
            if not isinstance(candidates, list) or len(candidates) == 0:
                return jsonify({'error': f'Invalid {election_type} data'}), 400

            for candidate in candidates:
                if not candidate.get('candidate') or not candidate.get('party'):
                    return jsonify({'error': f'Missing candidate or party in {election_type}'}), 400

                valid, votes = validate_votes(candidate.get('votes', 0))
                if not valid:
                    return jsonify({'error': f'{election_type}: {votes}'}), 400
                candidate['votes'] = votes

        with get_db() as conn:
            c = conn.cursor()

            # Check for duplicate submission
            c.execute("""SELECT id FROM submissions
                        WHERE observer_id = ? AND province = ? AND district = ?
                        AND constituency = ? AND ward = ? AND polling_station = ?""",
                     (current_user['id'], data['province'], data['district'],
                      data['constituency'], data['ward'], data['polling_station']))
            if c.fetchone():
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
                      gps_lat, gps_lon,
                      json.dumps(data['presidential']), json.dumps(data['parliamentary']),
                      json.dumps(data['council']), json.dumps(data.get('photos', []))))

            submission_id = c.lastrowid
            conn.commit()

            log_audit(current_user['id'], 'submit_results', 'submission', submission_id,
                     f"Station: {data['polling_station']}")

        return jsonify({
            'success': True,
            'message': 'Results submitted successfully',
            'submission_id': submission_id
        }), 201
    except Exception as e:
        print(f"Submit error: {e}")
        return jsonify({'error': 'Submission failed'}), 500

@app.route('/api/submissions', methods=['GET', 'OPTIONS'])
@token_required
def get_submissions(current_user):
    if request.method == 'OPTIONS':
        return '', 200

    try:
        status = request.args.get('status', 'all')

        with get_db() as conn:
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

        return jsonify({'submissions': submissions})
    except Exception:
        return jsonify({'error': 'Failed to load submissions'}), 500

@app.route('/api/submissions/<int:id>', methods=['GET', 'OPTIONS'])
@token_required
def get_submission_detail(current_user, id):
    if request.method == 'OPTIONS':
        return '', 200

    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM submissions WHERE id = ?", (id,))
            submission = c.fetchone()

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
    except Exception:
        return jsonify({'error': 'Failed to load submission'}), 500

@app.route('/api/submissions/<int:id>/approve', methods=['POST', 'OPTIONS'])
@token_required
def approve_submission(current_user, id):
    if request.method == 'OPTIONS':
        return '', 200

    if current_user['role'] != 'admin':
        return jsonify({'error': 'Access denied'}), 403

    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("UPDATE submissions SET status = 'approved', approved_at = CURRENT_TIMESTAMP, approved_by = ? WHERE id = ?",
                      (current_user['id'], id))
            conn.commit()

            log_audit(current_user['id'], 'approve_submission', 'submission', id)

        return jsonify({'message': 'Approved successfully'})
    except Exception:
        return jsonify({'error': 'Failed to approve submission'}), 500

@app.route('/api/submissions/<int:id>/reject', methods=['POST', 'OPTIONS'])
@token_required
def reject_submission(current_user, id):
    if request.method == 'OPTIONS':
        return '', 200

    if current_user['role'] != 'admin':
        return jsonify({'error': 'Access denied'}), 403

    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("UPDATE submissions SET status = 'rejected', approved_at = CURRENT_TIMESTAMP, approved_by = ? WHERE id = ?",
                      (current_user['id'], id))
            conn.commit()

            log_audit(current_user['id'], 'reject_submission', 'submission', id)

        return jsonify({'message': 'Rejected successfully'})
    except Exception:
        return jsonify({'error': 'Failed to reject submission'}), 500

# ==================== RESULTS & STATS ====================

@app.route('/api/results', methods=['GET', 'OPTIONS'])
@token_required
def get_results(current_user):
    if request.method == 'OPTIONS':
        return '', 200

    try:
        election_type = request.args.get('type', 'presidential')
        province = request.args.get('province')

        with get_db() as conn:
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

        formatted = []
        for key, votes in sorted(results.items(), key=lambda x: x[1], reverse=True):
            candidate, party = key.split('|')
            percentage = (votes / total_votes * 100) if total_votes > 0 else 0
            formatted.append({'candidate': candidate, 'party': party, 'votes': votes, 'percentage': round(percentage, 2)})

        return jsonify({'election_type': election_type, 'results': formatted, 'total_votes': total_votes})
    except Exception:
        return jsonify({'error': 'Failed to load results'}), 500

@app.route('/api/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_stats(current_user):
    if request.method == 'OPTIONS':
        return '', 200

    try:
        with get_db() as conn:
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

        return jsonify({
            'total_observers': total_observers,
            'total_submissions': total_submissions,
            'pending': pending,
            'approved': approved,
            'rejected': rejected,
            'provinces': provinces
        })
    except Exception:
        return jsonify({'error': 'Failed to load statistics'}), 500

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
