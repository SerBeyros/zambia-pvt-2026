#!/usr/bin/env python3
"""
Zambia PVT 2026 - Admin User Creation Script
Run this script to create a new admin user with a secure password
"""

import sqlite3
import bcrypt
import getpass
import re
import sys

DB_NAME = 'zambia_pvt_2026.db'

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

def create_admin():
    """Create a new admin user"""
    print("=" * 70)
    print("🗳️  ZAMBIA PVT 2026 - ADMIN USER CREATION")
    print("=" * 70)
    print()

    # Get username
    while True:
        username = input("Enter admin username (min 3 characters): ").strip()
        if len(username) < 3:
            print("❌ Username must be at least 3 characters long")
            continue
        break

    # Check if username exists
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    if c.fetchone():
        conn.close()
        print(f"❌ Username '{username}' already exists")
        sys.exit(1)

    # Get password
    while True:
        password = getpass.getpass("Enter admin password: ")
        valid, error_msg = validate_password_strength(password)
        if not valid:
            print(f"❌ {error_msg}")
            continue

        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            print("❌ Passwords do not match")
            continue
        break

    # Get other details
    full_name = input("Enter full name: ").strip()
    if not full_name:
        print("❌ Full name is required")
        sys.exit(1)

    phone = input("Enter phone number: ").strip()
    if not phone:
        print("❌ Phone number is required")
        sys.exit(1)

    email = input("Enter email (optional): ").strip() or None
    national_id = input("Enter national ID (optional): ").strip() or None
    organization = input("Enter organization (optional): ").strip() or None

    # Create admin user
    try:
        password_hash = hash_password(password)

        c.execute("""INSERT INTO users
                    (username, password_hash, full_name, phone, email, national_id, organization, role, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'admin', 1)""",
                 (username, password_hash, full_name, phone, email, national_id, organization))

        conn.commit()
        conn.close()

        print()
        print("=" * 70)
        print("✅ ADMIN USER CREATED SUCCESSFULLY")
        print("=" * 70)
        print(f"Username: {username}")
        print(f"Full Name: {full_name}")
        print(f"Phone: {phone}")
        if email:
            print(f"Email: {email}")
        print()
        print("⚠️  IMPORTANT: Store these credentials securely!")
        print("=" * 70)

    except Exception as e:
        print(f"❌ Error creating admin user: {e}")
        conn.rollback()
        conn.close()
        sys.exit(1)

if __name__ == '__main__':
    try:
        create_admin()
    except KeyboardInterrupt:
        print("\n\n❌ Operation cancelled by user")
        sys.exit(1)
