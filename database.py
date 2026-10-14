
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL")

if not MONGO_URL:
    raise RuntimeError("MONGO_URL is not configured in environment variables.")

client = MongoClient(
    MONGO_URL,
    serverSelectionTimeoutMS=10000
)

# Verify the database connection
client.admin.command("ping")

db = client["invoiceiq"]

invoice_collection = db["invoices"]
company_collection = db["companies"]
user_collection = db["user"]
chat_collection = db["chat_history"]
chat_sessions_collection = db["chat_sessions"]
chat_messages_collection = db["chat_messages"]
company_user_collection = db["company_user_collection"]
reminder_collection = db["reminders"]
payments_collection = db["payments"]

print("MongoDB connected successfully")
