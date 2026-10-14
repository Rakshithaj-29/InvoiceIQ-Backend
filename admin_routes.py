from fastapi import APIRouter, Body, HTTPException,Depends
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
import os
import re
import random
from bson import ObjectId
from email_utils import send_admin_credentials, send_company_credentials,send_due_soon_reminder,send_due_today_reminder,send_overdue_reminder,send_admin_credentials,send_password_reset_otp,send_admin_password_reset_email
from database import (
    user_collection,
    company_collection,
    invoice_collection
)

from utils import (
    serialize,
    pwd_context,
    SECRET_KEY,
    ALGORITHM,
    verify_token,
    verify_company_token,
    nof,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
admin_router = APIRouter(tags=["Admin "])
otp_store={}

@admin_router.post("/auth/login")
async def login(data: dict):
    user = user_collection.find_one({"email": data.get("email")})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email")
    if not pwd_context.verify(data.get("password", ""), user["password"]):
        raise HTTPException(status_code=401, detail="Invalid password")
    expire     = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token      = jwt.encode({"sub": data["email"], "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)
    return {
        "message": "Login successful",
          "access_token": token,
           "token_type": "bearer",
            "role": user.get("role", "admin"),
            "name":user.get("name",""),
            "email":user.get("email","")
            }
# ═══════════════════════════════════════════════════════════════════════════
# COMPANIES
# ═══════════════════════════════════════════════════════════════════════════
@admin_router.get("/companies")
def get_companies():
    return [serialize(c) for c in company_collection.find()]

@admin_router.get("/companies/{company_id}")
def get_company_detail(company_id: str):
    company = company_collection.find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company = serialize(company)
    invoices = list(invoice_collection.find({"company": company["companyName"]}))
    invoices = [serialize(inv) for inv in invoices]

    total = 0
    for inv in invoices:
        try:
            total += float(inv.get("amount") or 0)
        except (ValueError, TypeError):
            pass

    company["invoices"] = invoices
    company["total_invoice_amount"] = round(total, 2)
    return company


@admin_router.post("/companies")
def add_company(company: dict = Body(...)):
    name = company.get("companyName", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Company name is required")

    # Duplicate check (case-insensitive)
    if company_collection.find_one({"companyName": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}):
        raise HTTPException(status_code=409, detail=f"A company named '{name}' already exists")

    gst = company.get("gst_number", "").strip()
    if gst and len(gst) != 15:
        raise HTTPException(status_code=400,
         detail="GST Number must be exactly 15 characters")
    password = company.get("password", "").strip()
    
    if not password:
       raise HTTPException(
       status_code=400,
       detail="Password is required"
    )
    plain_password = password

    count = company_collection.count_documents({})
    company["company_id"]   = f"COMP{count + 1:03}"
    company["created_date"] = datetime.utcnow().isoformat()
    company["must_change_password"] = True
    company["password"] = pwd_context.hash(
    company["password"])
    company_collection.insert_one(company)

    try:

       send_company_credentials(
        company["companyName"],
        company["email"],
        plain_password
    )

    except Exception as e:

       print("EMAIL ERROR:", e)

    return {
    "message": "Company added successfully",
    "company_id": company["company_id"]
}


@admin_router.put("/companies/{company_id}")
def update_company(company_id: str, updated: dict = Body(...)):
    name = updated.get("companyName", "").strip()
    if name:
        existing = company_collection.find_one({
            "companyName": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
            "_id": {"$ne": ObjectId(company_id)}
        })
        if existing:
            raise HTTPException(status_code=409, detail=f"A company named '{name}' already exists")
    result = company_collection.update_one({"_id": ObjectId(company_id)}, {"$set": updated})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"message": "Company updated successfully"}


@admin_router.delete("/companies/{company_id}")
def delete_company(company_id: str):
    # Find the company first to get its name
    company = company_collection.find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company_name = company.get("companyName", "")

    # Delete all invoices belonging to this company
    invoice_collection.delete_many({"company": company_name})

    # Now delete the company
    company_collection.delete_one({"_id": ObjectId(company_id)})

    return {"message": "Company and its invoices deleted successfully"}

@admin_router.get("/company-search")
def company_search(search: str = ""):
    
    if not search.strip():
        companies = company_collection.find().sort("_id", -1)
        return [serialize(company) for company in companies]

    query = {
        "$or": [
            {"companyName": {"$regex": search, "$options": "i"}},
            {"company_id": {"$regex": search, "$options": "i"}},
            {"gst_number": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"contact_information": {"$regex": search, "$options": "i"}}
        ]
    }

    companies = company_collection.find(query).sort("_id", -1)

    return [serialize(company) for company in companies]
# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD STATS
# ═══════════════════════════════════════════════════════════════════════════
@admin_router.get("/dashboard/stats")
def get_dashboard_stats():
    total_companies = company_collection.count_documents({})
    total_invoices  = invoice_collection.count_documents({})
    paid    = invoice_collection.count_documents({"status": "Paid"})
    pending = invoice_collection.count_documents({"status": "Pending"})
    overdue = invoice_collection.count_documents({"status": "Overdue"})
    total_amount = 0

    for inv in invoice_collection.find():
        try:
            total_amount += float(inv.get("amount", 0))
        except:
            pass
    recent = []
    for inv in invoice_collection.find().sort("_id", -1).limit(5):
        recent.append({
            "invoice_id": inv.get("invoice_id", ""),
            "company":    inv.get("company", ""),
            "amount":     inv.get("amount", ""),
            "status":     inv.get("status", ""),
            "uploaded_at":inv.get("uploaded_at", ""),
        })

    monthly = {}
    for inv in invoice_collection.find({"uploaded_at": {"$exists": True}}):
        try:
            key = datetime.fromisoformat(inv["uploaded_at"]).strftime("%b")
            monthly[key] = monthly.get(key, 0) + 1
        except Exception:
            pass

    months_order = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    monthly_chart = [{"month": m, "invoices": monthly[m]} for m in months_order if m in monthly]

    return {
        "total_companies":  total_companies,
        "total_invoices":   total_invoices,
        "total_amount":round(total_amount, 2),
        "status_breakdown": {"paid": paid, "pending": pending, "overdue": overdue},
        "recent_invoices":  recent,
        "monthly_chart":    monthly_chart,
    }
# ======================================================
# Analytics
# ======================================================
@admin_router.get("/analytics")
def get_analytics():

    invoices = list(invoice_collection.find())

    total_invoices = len(invoices)

    total_revenue = 0
    paid = 0
    overdue = 0
    pending=0
    outstanding_amount=0
    due_this_week=0
    company_revenue = {}

    for inv in invoices:
        try:
            amount = float(inv.get("amount", 0))
        except:
            amount = 0

        total_revenue += amount

        company = inv.get("company", "Unknown")
        company_revenue[company] = (
            company_revenue.get(company, 0) + amount
        )

        status = inv.get("status", "")

        if status == "Paid":
            paid += 1

        elif status == "Overdue":
            overdue += 1

        elif status =="Pending":
            pending+=1
        
        if status in ["Pending", "Overdue"]:

            outstanding_amount += amount
        
        days_remaining = inv.get("days_remaining",None)

        if (status == "Pending"and days_remaining is not None and days_remaining <= 7):
            due_this_week += 1
    avg_invoice_value = (
        round(total_revenue / total_invoices, 2)
        if total_invoices > 0
        else 0
    )

    collection_rate = (
        round((paid / total_invoices) * 100, 2)
        if total_invoices > 0
        else 0
    )

    overdue_rate = (
        round((overdue / total_invoices) * 100, 2)
        if total_invoices > 0
        else 0
    )

    return {
    "total_revenue": round(total_revenue, 2),
    "avg_invoice_value": avg_invoice_value,
    "collection_rate": collection_rate,
    "overdue_rate": overdue_rate,

    "paid": paid,
    "pending": pending,
    "overdue": overdue,

    "outstanding_amount": round(
        outstanding_amount,
        2
    ),

    "due_this_week": due_this_week,

    "company_revenue": company_revenue
}
@admin_router.post("/admins")
def create_admin(data: dict):

    # Name validation
    if not data.get("name", "").strip():
        raise HTTPException(
            status_code=400,
            detail="Administrator name is required"
        )

    # Email validation
    if not data.get("email", "").strip():
        raise HTTPException(
            status_code=400,
            detail="Email is required"
        )

    email_pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"

    if not re.match(email_pattern, data["email"]):
        raise HTTPException(
            status_code=400,
            detail="Invalid email address"
        )

    # Password validation
    if not data.get("password", "").strip():
       raise HTTPException(
        status_code=400,
        detail="Password is required"
    )

    password_pattern = (
    r"^(?=.*[a-z])"      # at least one lowercase
    r"(?=.*[A-Z])"       # at least one uppercase
    r"(?=.*\d)"          # at least one digit
    r"(?=.*[@$!%*?&])"   # at least one special character
    r"[A-Za-z\d@$!%*?&]{8,}$"  # minimum 8 characters
)

    if not re.match(password_pattern, data["password"]):
        raise HTTPException(
        status_code=400,
        detail=(
            "Password must contain at least 8 characters, "
            "one uppercase letter, one lowercase letter, "
            "one number and one special character."
        )
    )

    # Duplicate email check
    existing = user_collection.find_one({
        "email": data["email"]
    })

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Email already exists"
        )
    original_password=data["password"]
    hashed_password = pwd_context.hash(
        original_password
    )

    user_collection.insert_one({
        "name": data["name"],
        "email": data["email"],
        
        "password": hashed_password,
        "role": "admin",
        "created_at": datetime.utcnow().isoformat()
    })
    try:
        send_admin_credentials(
        data["name"],
        data["email"],
        original_password)
    except Exception as e:
        print("EMAIL ERROR:",e)
        user_collection.delete_one({
        "email": data["email"]
    })

        raise HTTPException(
        status_code=500,
        detail="Failed to send credentials email."
    )
    return {
        "message": "Admin created successfully.Credentials sent to the registered email."
    }
@admin_router.get("/admins")
def get_admins():

    admins = list(
        user_collection.find({
            "role": "admin"
        })
    )

    return [
        serialize(admin)
        for admin in admins
    ]


# Search admins
@admin_router.get("/admins/search")
def search_admins(q: str = ""):

    query = {
        "role": "admin"
    }

    if q:

        query["$or"] = [

            {
                "name": {
                    "$regex": q,
                    "$options": "i"
                }
            },

            {
                "email": {
                    "$regex": q,
                    "$options": "i"
                }
            }

        ]

    admins = list(
        user_collection.find(query)
    )

    return [
        serialize(admin)
        for admin in admins
    ]


@admin_router.get("/admins/{admin_id}")
def get_admin(admin_id: str):

    admin = user_collection.find_one(
        {"_id": ObjectId(admin_id)}
    )

    if not admin:
        raise HTTPException(
            status_code=404,
            detail="Admin not found"
        )

    return serialize(admin)

@admin_router.delete("/admins/{admin_id}")
def delete_admin(admin_id: str):

    admin = user_collection.find_one(
        {"_id": ObjectId(admin_id)}
    )

    if not admin:
        raise HTTPException(
            status_code=404,
            detail="Admin not found"
        )

    if admin.get("role") == "super_admin":
        raise HTTPException(
            status_code=400,
            detail="Super Admin cannot be deleted"
        )

    user_collection.delete_one(
        {"_id": ObjectId(admin_id)}
    )

    return {
        "message": "Admin deleted successfully"
    }


@admin_router.put("/admins/{admin_id}")
def update_admin(admin_id: str, data: dict):

    admin = user_collection.find_one(
        {"_id": ObjectId(admin_id)}
    )

    if not admin:
        raise HTTPException(
            status_code=404,
            detail="Administrator not found"
        )

    if admin.get("role") == "super_admin":
        raise HTTPException(
            status_code=400,
            detail="Super Administrator cannot be edited"
        )

    # Validate name
    if not data.get("name", "").strip():
        raise HTTPException(
            status_code=400,
            detail="Administrator name is required"
        )

    # Validate email
    if not data.get("email", "").strip():
        raise HTTPException(
            status_code=400,
            detail="Email is required"
        )

    existing = user_collection.find_one({
        "email": data["email"],
        "_id": {"$ne": ObjectId(admin_id)}
    })

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Email already exists"
        )

    user_collection.update_one(
        {"_id": ObjectId(admin_id)},
        {
            "$set": {
                "name": data["name"],
                "email": data["email"]
            }
        }
    )

    return {
        "message": "Administrator updated successfully"
    }

@admin_router.put("/change-password")
def change_password(
    data: dict,
    token_data: dict = Depends(verify_token)
):

    email = token_data["sub"]

    user = user_collection.find_one({
        "email": email
    })

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if not pwd_context.verify(
        data["current_password"],
        user["password"]
    ):
        raise HTTPException(
            status_code=400,
            detail="Current password is incorrect"
        )

    new_hash = pwd_context.hash(
        data["new_password"]
    )

    user_collection.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "password": new_hash
            }
        }
    )

    return {
        "message": "Password changed successfully"
    }
@admin_router.put("/admins/{admin_id}/reset-password")
def reset_admin_password(
    admin_id: str,
    data: dict
):

    admin = user_collection.find_one(
        {"_id": ObjectId(admin_id)}
    )

    if not admin:
        raise HTTPException(
            status_code=404,
            detail="Admin not found"
        )

    if admin.get("role") == "super_admin":
        raise HTTPException(
            status_code=400,
            detail="Cannot reset Super Admin password"
        )
    if not data.get("new_password", "").strip():
        raise HTTPException(
        status_code=400,
        detail="Password cannot be empty"
    )
    
    new_hash = pwd_context.hash(
        data["new_password"]
    )

    user_collection.update_one(
        {"_id": ObjectId(admin_id)},
        {
            "$set": {
                "password": new_hash
            }
        }
    )
    send_admin_password_reset_email(
    admin["name"],
    admin["email"],
    data["new_password"]
)

    return {
        "message": "Admin password reset successfully"
    }




# email route
from email_utils import send_test_email

@admin_router.get("/test-email")
def test_email():

    send_test_email(
        "invoiceiqweb@gmail.com"
    )

    return {
        "message": "Email sent successfully"
    }




# send reminders
@admin_router.post("/send-reminders")
def send_reminders():

    invoices = list(
        invoice_collection.find()
    )

    sent = 0

    for inv in invoices:

        company_name = inv.get(
            "company"
        )

        company = (
            company_collection.find_one(
                {
                    "companyName":
                    company_name
                }
            )
        )

        if not company:
            continue

        email = company.get("email")

        status = inv.get("status")

        if (
            status == "Pending"
            and 0<inv.get(
                "days_remaining",0) <=3):

            send_due_soon_reminder(
                email,
                inv["invoice_id"],

                inv.get("vendor_name", "Unknown Vendor"),
                inv["amount"],
                inv["due_date"],
                inv["days_remaining"]
            )

            sent += 1

        elif (
            status == "Pending"
            and inv.get(
                "days_remaining",0
            ) == 0
        ):

            send_due_today_reminder(
                email,

                inv.get("vendor_name", "Unknown Vendor"),
                inv["invoice_id"],
                inv["amount"]
            )

            sent += 1

        elif (
            status == "Overdue"
        ):
            days_overdue=inv.get("days_overdue",0)
            send_overdue_reminder(
                email,

                inv.get("vendor_name", "Unknown Vendor"),
                inv["invoice_id"],
                inv["amount"],
                days_overdue
            )

            sent += 1

    return {
        "message":
        f"{sent} reminder emails sent"
    }

# forgot password
@admin_router.post("/forgot-password")
def forgot_password(data: dict):

    email = data.get("email", "").strip()

    if not email:
        raise HTTPException(
            status_code=400,
            detail="Email is required"
        )

    user = user_collection.find_one({
        "email": email
    })

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Email not found"
        )

    if user["role"] != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="Only Super Administrator can use this feature."
        )

    otp = str(random.randint(100000, 999999))

    otp_store[email] = {
        "otp": otp,
        "expires": datetime.utcnow() + timedelta(minutes=5)
    }

    send_password_reset_otp(email, otp)

    return {
        "message": "OTP sent successfully."
    }

# verify OTP
@admin_router.post("/verify-otp")
def verify_otp(data: dict):

    email = data.get("email")
    otp = data.get("otp")

    if email not in otp_store:
        raise HTTPException(
            status_code=400,
            detail="OTP not found"
        )

    record = otp_store[email]

    if datetime.utcnow() > record["expires"]:
        otp_store.pop(email)
        raise HTTPException(
            status_code=400,
            detail="OTP expired"
        )

    if record["otp"] != otp:
        raise HTTPException(
            status_code=400,
            detail="Invalid OTP"
        )
    record["verified"]=True

    return {
        "message": "OTP verified successfully"
    }
# reset password
@admin_router.post("/reset-password")
def reset_password(data: dict):

    email = data.get("email", "").strip()
    new_password = data.get("new_password", "").strip()

    if not email or not new_password:
        raise HTTPException(
            status_code=400,
            detail="Email and new password are required."
        )

    user = user_collection.find_one({
        "email": email
    })

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found."
        )

    if user["role"] != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="Only Super Administrator can reset password."
        )

    record = otp_store.get(email)

    if not record:
        raise HTTPException(
            status_code=400,
            detail="Please request an OTP first."
        )

    if not record.get("verified"):
        raise HTTPException(
            status_code=400,
            detail="Please verify OTP first."
        )

    hashed_password = pwd_context.hash(new_password)

    user_collection.update_one(
        {"email": email},
        {
            "$set": {
                "password": hashed_password
            }
        }
    )

    otp_store.pop(email, None)

    return {
        "message": "Password reset successfully."
    }