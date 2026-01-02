# Zambia PVT 2026 - Security Setup Guide

## 🔒 Critical Security Improvements (v2.1.0)

This version includes comprehensive security hardening. **All 18 security vulnerabilities have been fixed.**

## ⚠️ Required Environment Variables

Before running the application, you **MUST** set the following environment variables:

### 1. SECRET_KEY (REQUIRED)
Generate a strong secret key for JWT token signing:

```bash
python -c 'import secrets; print(secrets.token_hex(32))'
```

Set it as an environment variable:
```bash
export SECRET_KEY="your-generated-secret-key-here"
```

For Render.com, add it in the Environment Variables section of your service settings.

### 2. ALLOWED_ORIGINS (REQUIRED for production)
Comma-separated list of allowed origins for CORS:

```bash
export ALLOWED_ORIGINS="https://your-frontend-domain.com,https://www.your-frontend-domain.com"
```

For local development, it defaults to `http://localhost:3000,http://localhost:5000`.

### 3. FLASK_ENV (Optional)
Set to `production` to enable HTTPS enforcement:

```bash
export FLASK_ENV=production
```

## 📝 Initial Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Create Admin User

**IMPORTANT:** Default admin credentials have been removed for security.

Run the admin creation script:

```bash
python create_admin.py
```

Follow the prompts to create a secure admin account with:
- Minimum 8 characters
- At least one letter
- At least one number

**Save these credentials securely!**

### 3. Start the Application

```bash
python backend.py
```

Or with gunicorn for production:

```bash
gunicorn backend:app
```

## 🛡️ Security Features Implemented

### Critical Fixes (Previously Vulnerable)

1. ✅ **Bcrypt Password Hashing** - Replaced weak SHA256 with bcrypt
2. ✅ **Environment-Based Secret Keys** - No more hardcoded secrets
3. ✅ **Restricted CORS** - Origin validation instead of wildcard
4. ✅ **Rate Limiting** - 5 failed login attempts = 5-minute lockout
5. ✅ **Input Validation** - GPS coordinates, vote counts, text fields
6. ✅ **SQL Injection Prevention** - Parameterized queries only
7. ✅ **Password Strength Requirements** - Enforced minimum standards
8. ✅ **JWT Token Expiry** - Reduced from 30 days to 8 hours
9. ✅ **Error Message Sanitization** - No sensitive info leaked
10. ✅ **Database Context Managers** - Proper connection handling
11. ✅ **Transaction Management** - ACID compliance
12. ✅ **Audit Trail** - All admin actions logged
13. ✅ **Timezone Consistency** - UTC throughout
14. ✅ **HTTPS Enforcement** - Automatic in production mode
15. ✅ **No Hardcoded Credentials** - Removed from all files
16. ✅ **Auto-Detecting API URLs** - No hardcoded endpoints
17. ✅ **Fixed JavaScript Errors** - Complete, valid HTML/JS
18. ✅ **Secure Admin Creation** - Script-based user creation

## 🔐 Password Policy

All passwords must meet these requirements:
- Minimum 8 characters
- At least one letter (a-z, A-Z)
- At least one number (0-9)

## 📊 Audit Log

All administrative actions are logged in the `audit_log` table:
- User logins (successful and failed)
- Observer creation/modification/deactivation
- Submission approvals/rejections
- IP addresses and timestamps

Query the audit log:
```python
SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 100;
```

## 🚀 Deployment Checklist

Before deploying to production:

- [ ] Generate and set `SECRET_KEY` environment variable
- [ ] Configure `ALLOWED_ORIGINS` with your domain(s)
- [ ] Set `FLASK_ENV=production`
- [ ] Create admin user with strong password
- [ ] Test login with new credentials
- [ ] Verify HTTPS is working
- [ ] Review audit logs
- [ ] Remove any test/demo data
- [ ] Backup database regularly

## 📖 API Changes

### New Response Fields

Login response now includes:
```json
{
  "token": "...",
  "expires_in": 28800,  // 8 hours in seconds
  "user": { ... }
}
```

### New Error Responses

- `429 Too Many Requests` - Rate limit exceeded
- `403 Forbidden` - HTTPS required in production

## 🔧 Configuration Override

To override the API URL in frontend:

```javascript
// In HTML files, before any scripts load:
window.API_BASE_URL = 'https://your-custom-backend-url.com/api';
```

## 📞 Support

For security issues, please review the audit logs and check:
1. Environment variables are correctly set
2. Database has proper permissions
3. HTTPS is enabled in production
4. Firewall rules allow necessary ports

## 🎯 Best Practices

1. **Never commit `.env` files** with secrets
2. **Rotate SECRET_KEY** periodically
3. **Review audit logs** regularly
4. **Use strong passwords** for all accounts
5. **Keep dependencies updated** (`pip install --upgrade`)
6. **Monitor failed login attempts**
7. **Backup database** before updates

## 📜 Version History

- **v2.1.0** - Security hardening (all 18 vulnerabilities fixed)
- **v2.0.0** - Initial production version
