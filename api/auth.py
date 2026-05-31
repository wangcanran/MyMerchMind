
import json
from pathlib import Path
import bcrypt

USERS_FILE = Path(__file__).parent / "users.json"

def load_users():
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE, 'r') as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def register_user(username, password):
    users = load_users()
    if username in users:
        raise ValueError("Username already exists")

    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    users[username] = {"password_hash": hashed_password.decode('utf-8')}
    save_users(users)
    return True

def verify_user(username, password):
    users = load_users()
    user = users.get(username)
    if not user:
        return False

    return bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8'))
