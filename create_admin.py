"""
Run this ONCE to create the admin user.
  python create_admin.py
Credentials: admin@gmail.com / admin123
"""
from passlib.context import CryptContext
from database import user_collection

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

email = "invoiceiqweb@gmail.com"
password="Invoiceiq@2026"
if user_collection.find_one({"email": email}):
    print(f"Admin '{email}' already exists.")
else:
    user_collection.insert_one({
        "email":    email,
        "password": pwd_context.hash(password),
        "role":"super_admin"
    })
    print(f"✅ Admin created — email: {email}  password:{password}")
