from fastapi import (
    APIRouter,
    Body,
    Depends
)
import os,random,re
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
import csv
import io
from bson import ObjectId
from openpyxl import Workbook
from fastapi import BackgroundTasks
from datetime import datetime, timedelta
from email_utils import notify_admin_password_changed,send_reset_otp,notify_admin_password_changed
from jose import jwt

from collections import defaultdict

from database import (
    invoice_collection,
    company_collection,
    chat_sessions_collection,
    chat_messages_collection,
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

import json
from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException
)
from groq import Groq
import faiss
from sentence_transformers import SentenceTransformer
from pydantic import BaseModel

company_router = APIRouter(tags=["Companies"])

@company_router.post("/company/login")
def company_login(data: dict = Body(...)):
    print(data)
    company = company_collection.find_one({
        "companyName": data["companyName"],
        "email": data["email"]
        
    })
    print(company)
    if not company:
        raise HTTPException(
            status_code=401,
            detail="Invaild company or email"
        )

    
    if not pwd_context.verify(
    data["password"],
    company["password"]
):
         raise HTTPException(
        status_code=401,
        detail="Invalid password"
    )
    expire = datetime.utcnow() + timedelta(days=7)
    token = jwt.encode(
    {
        "sub": company["email"],
        "role": "company",
        "company_name": company["companyName"],
        "exp": expire
    },
    SECRET_KEY,
    algorithm=ALGORITHM
)

    print(company)
    return { 
        "success": True,
        "company_name": company["companyName"],
        "email": company["email"],
        "token": token,
        "must_change_password":
        company.get(
            "must_change_password",
            False
        ) 
    }

@company_router.get("/company/invoices/{company_name}")
def get_company_invoices(company_name: str):

    invoices = list(
        invoice_collection.find(
            {
                "company": {
                    "$regex": f"^{company_name}$",
                    "$options": "i"
                }
            }
        )
    )

    for invoice in invoices:
        invoice["_id"] = str(invoice["_id"])

    return invoices

@company_router.get("/company/dashboard/{company_name}")
def company_dashboard(company_name: str):

    invoices = list(
        invoice_collection.find(
            {
                "company": {
                    "$regex": f"^{company_name}$",
                    "$options": "i"
                }
            }
        )
    )

    total_invoices = len(invoices)

    total_revenue = sum(
        float(inv.get("amount", 0))
        for inv in invoices
    )

    paid = sum(
        1 for inv in invoices
        if inv.get("status", "").lower() == "paid"
    )

    pending = sum(
        1 for inv in invoices
        if inv.get("status", "").lower() == "pending"
    )

    overdue = sum(
        1 for inv in invoices
        if inv.get("status", "").lower() == "overdue"
    )

    return {
        "total_invoices": total_invoices,
        "total_revenue": total_revenue,
        "paid": paid,
        "pending": pending,
        "overdue": overdue
    }
@company_router.get("/company/profile/{company_name}")
def get_company_profile(company_name: str):

    company = company_collection.find_one(
        {
            "companyName": {
                "$regex": f"^{company_name}$",
                "$options": "i"
            }
        }
    )

    if not company:
        return {"message": "Company not found"}

    company["_id"] = str(company["_id"])

    return company
@company_router.get("/company/analytics/{company_name}")
def company_analytics(company_name: str):

    invoices = list(
        invoice_collection.find(
            {
                "company": {
                    "$regex": f"^{company_name}$",
                    "$options": "i"
                }
            }
        )
    )

    paid = 0
    pending = 0
    overdue = 0

    for inv in invoices:

        status = inv.get(
            "status",
            ""
        ).lower()

        if status == "paid":
            paid += 1

        elif status == "pending":
            pending += 1

        elif status == "overdue":
            overdue += 1

    return {
        "paid": paid,
        "pending": pending,
        "overdue": overdue
    }

@company_router.get("/company/revenue-trend/{company_name}")
def revenue_trend(company_name: str):

    invoices = list(
        invoice_collection.find(
            {
                "company": {
                    "$regex": f"^{company_name}$",
                    "$options": "i"
                }
            }
        )
    )

    revenue_by_month = defaultdict(float)

    for inv in invoices:

        try:

            amount = float(
                str(inv.get("amount", 0))
                .replace("₹", "")
                .replace(",", "")
            )

            

            invoice_date = datetime.fromisoformat(
               inv["uploaded_at"]
            )

            month = invoice_date.strftime("%b")

            revenue_by_month[month] += amount

        except:
            pass

    result = []

    month_order = [
        "Jan", "Feb", "Mar", "Apr",
        "May", "Jun", "Jul", "Aug",
        "Sep", "Oct", "Nov", "Dec"
    ]

    for month in month_order:

        if month in revenue_by_month:

            result.append(
                {
                    "month": month,
                    "revenue": round(
                        revenue_by_month[month],
                        2
                    )
                }
            )

    return result



@company_router.get("/download-invoice/{invoice_id}")
def download_invoice(invoice_id: str):

    invoice = invoice_collection.find_one(
        {"_id": ObjectId(invoice_id)}
    )

    if not invoice:
        return {"message": "Invoice not found"}

    return FileResponse(
        invoice["file_path"],
        filename=invoice["file_name"]
    )
@company_router.get("/company/search-invoices")
def search_company_invoices(
    company_name: str,
    q: str = ""
):  
    print("SEARCH")
    print("Company:",company_name)
    print("Search:",q)

    invoices = list(
        invoice_collection.find(
            {
                "company": {
                    "$regex": f"^{company_name}$",
                    "$options": "i"
                }
            }
        )
    )
    print("Invoices found:",len(invoices))

    if q:

        q = q.lower()

        invoices = [
            inv for inv in invoices
            if (
                q in str(
                    inv.get(
                        "invoice_number",
                        ""
                    )
                ).lower()
                or
                q in str(
                    inv.get(
                        "vendor_name",
                        ""
                    )
                ).lower()
                or
                q in str(
                    inv.get(
                        "gstin",
                        ""
                    )
                ).lower()
            )
        ]

    for inv in invoices:
        inv["_id"] = str(inv["_id"])
    print("Returning:", len(invoices))
    return invoices


@company_router.get("/company/invoice/{invoice_id}")
def get_invoice_details(invoice_id: str):

    invoice = invoice_collection.find_one(
        {"_id": ObjectId(invoice_id)}
    )

    if not invoice:
        return {
            "success": False,
            "message": "Invoice not found"
        }




    invoice["_id"] = str(invoice["_id"])
    return invoice



# change password

@company_router.put("/company/change-password")
def change_company_password(
    data: dict,
    background_tasks:BackgroundTasks,
    token_data: dict = Depends(
        verify_company_token
    )
):
    print("TOKEN DATA:",token_data)
    print("TOKEN TYPE",type(token_data))  
    email = token_data["email"]
    company_name=token_data["company_name"]

    company = company_collection.find_one({
        "email": email,
        "companyName":company_name
    })
    print("COMPANY FOUND:", company)

    print("Entered Password:",
          data["current_password"])

    print("Stored Hash:",
          company["password"])

    if not company:
        raise HTTPException(
            status_code=404,
            detail="Company not found"
        )

    if not pwd_context.verify(
        data["current_password"],
        company["password"]
    ):
        raise HTTPException(
            status_code=400,
            detail="Current password is incorrect"
        )
    error = validate_password(
    data["new_password"]
)

    if error:    
        raise HTTPException(
        status_code=400,
        detail=error
    )
    new_hash = pwd_context.hash(
        data["new_password"]
    )

    company_collection.update_one(
        {"_id": company["_id"]},
        {
            "$set": {
                "password": new_hash,
                "must_change_password":False,
                "password_changed_at":datetime.utcnow().isoformat()
            }
        }
    )
    background_tasks.add_task(
    notify_admin_password_changed,
    company["companyName"],
    company["email"]
)
    

    return {
        "message": "Password changed successfully"
    }

# company chatbot

@company_router.post("/company-chat")
async def company_chat(
    data: dict = Body(...),
    token_data: dict = Depends(verify_company_token)
):
    company_email = token_data["email"]

    company = company_collection.find_one({
        "email": company_email
    })

    if not company:
        return {
            "response": "Company not found"
        }

    invoices = list(
    invoice_collection.find({
        "company": company["companyName"]
    })
    .sort("_id", -1)
    .limit(15)
)

    for inv in invoices:
        inv["_id"] = str(inv["_id"])

    total_amount = 0

    for inv in invoices:
        try:
            total_amount += float(
                str(inv.get("amount", 0))
                .replace("₹", "")
                .replace(",", "")
            )
        except:
            pass
    invoice_text=""
    for inv in invoices[:10]:
        invoice_text+=(
         f"invoice_id: {inv.get('invoice_id')}|"
         f"amount: {inv.get('amount')}|"
         f"status: {inv.get('status')}|"
         f"vendor: {inv.get('vendor_name')}|"
         f"invoice_date: {inv.get('invoice_date')}\n"
    )
    prompt = f"""
    COMPANY: {company['companyName']}

    TOTAL INVOICES: {len(invoices)}

    TOTAL AMOUNT: ₹{round(total_amount,2)}
    
       

    INVOICES:{invoice_text}

    QUESTION:{data['message']}"""

    client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)

    response = client.chat.completions.create(
    model="llama-3.1-8b-instant",
    messages=[
        {
            "role": "system",
            "content":
            """
            You are InvoiceIQ Company Assistant.

            Answer only using the company's invoices.

            You can answer:
            - invoice counts
            - paid invoices
            - pending invoices
            - overdue invoices
            - invoice amounts
            - latest invoices
            - highest and lowest invoices

            Never show invoices belonging to other companies.
            """
        },
        {
            "role": "user",
            "content": prompt
        }
    ],
    temperature=0.1
)

    return {
    "response":
    response.choices[0].message.content
}

# ── Company chat sessions (own history, search, rename, delete) ──────────

def _get_owned_session(session_id: str, company_name: str):
    """
    Fetch a chat session and make sure it actually belongs to the
    requesting company. Raises 404 if missing, 403 if owned by someone else.
    """
    session = chat_sessions_collection.find_one(
        {"_id": ObjectId(session_id)}
    )

    if not session:
        raise HTTPException(
            status_code=404,
            detail="Chat not found"
        )

    if session.get("company_name", "").lower() != company_name.lower():
        raise HTTPException(
            status_code=403,
            detail="Not authorized to access this chat"
        )

    return session


@company_router.post("/company/chat/new")
def create_company_chat(
    token_data: dict = Depends(verify_company_token)
):
    company_name = token_data["company_name"]

    chat = {
        "title": "New Chat",
        "company_name": company_name,
        "created_at": datetime.utcnow().isoformat()
    }

    result = chat_sessions_collection.insert_one(chat)

    return {
        "session_id": str(result.inserted_id)
    }


@company_router.get("/company/chat/sessions")
def get_company_chat_sessions(
    token_data: dict = Depends(verify_company_token)
):
    company_name = token_data["company_name"]

    chats = list(
        chat_sessions_collection.find({
            "company_name": {
                "$regex": f"^{company_name}$",
                "$options": "i"
            },
            "title": {"$ne": "New Chat"}
        }).sort("_id", -1)
    )

    return [serialize(chat) for chat in chats]


@company_router.get("/company/chat/search")
def search_company_chats(
    q: str,
    token_data: dict = Depends(verify_company_token)
):
    company_name = token_data["company_name"]

    # Only look inside sessions owned by this company
    own_session_ids = [
        str(s["_id"]) for s in chat_sessions_collection.find(
            {
                "company_name": {
                    "$regex": f"^{company_name}$",
                    "$options": "i"
                }
            },
            {"_id": 1}
        )
    ]

    messages = list(
        chat_messages_collection.find({
            "session_id": {"$in": own_session_ids},
            "content": {
                "$regex": q,
                "$options": "i"
            }
        })
    )

    results = []

    for msg in messages:

        session = chat_sessions_collection.find_one(
            {"_id": ObjectId(msg["session_id"])}
        )

        results.append({
            "_id": str(msg["_id"]),
            "session_id": msg["session_id"],
            "title": session["title"] if session else "Unknown Chat",
            "message": msg["content"]
        })

    return results


@company_router.get("/company/chat/{session_id}")
def get_company_chat(
    session_id: str,
    token_data: dict = Depends(verify_company_token)
):
    _get_owned_session(session_id, token_data["company_name"])

    messages = list(
        chat_messages_collection.find(
            {"session_id": session_id}
        ).sort("_id", 1)
    )

    return [serialize(msg) for msg in messages]


@company_router.post("/company/chat/{session_id}/message")
def save_company_chat_message(
    session_id: str,
    data: dict,
    token_data: dict = Depends(verify_company_token)
):
    session = _get_owned_session(session_id, token_data["company_name"])

    chat_messages_collection.insert_one({
        "session_id": session_id,
        "role": data["role"],
        "content": data["content"],
        "created_at": datetime.utcnow().isoformat()
    })

    if data["role"] == "user" and session.get("title") == "New Chat":
        chat_sessions_collection.update_one(
            {"_id": ObjectId(session_id)},
            {
                "$set": {
                    "title": data["content"][:30]
                }
            }
        )

    return {"message": "saved"}


@company_router.delete("/company/chat/{session_id}")
def delete_company_chat(
    session_id: str,
    token_data: dict = Depends(verify_company_token)
):
    _get_owned_session(session_id, token_data["company_name"])

    chat_sessions_collection.delete_one(
        {"_id": ObjectId(session_id)}
    )

    chat_messages_collection.delete_many(
        {"session_id": session_id}
    )

    return {"message": "Chat deleted successfully"}


class CompanyRenameChatRequest(BaseModel):
    title: str


@company_router.put("/company/chat/{session_id}/rename")
def rename_company_chat(
    session_id: str,
    data: CompanyRenameChatRequest,
    token_data: dict = Depends(verify_company_token)
):
    _get_owned_session(session_id, token_data["company_name"])

    chat_sessions_collection.update_one(
        {"_id": ObjectId(session_id)},
        {
            "$set": {
                "title": data.title
            }
        }
    )

    return {"message": "Chat renamed successfully"}


@company_router.get("/company/export-csv/{company_name}")
def export_csv(company_name: str):

    invoices = list(
        invoice_collection.find({
            "company": company_name
        })
    )

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow([
        "Invoice ID",
        "Vendor",
        "Invoice Number",
        "Invoice Date",
        "Amount",
        "Status"
    ])

    for inv in invoices:

        writer.writerow([
            inv.get("invoice_id", ""),
            inv.get("vendor_name", ""),
            inv.get("invoice_number", ""),
            inv.get("invoice_date", ""),
            inv.get("amount", ""),
            inv.get("status", "")
        ])

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition":
            f"attachment; filename={company_name}_report.csv"
        }
    )


@company_router.get("/company/export-excel/{company_name}")
def export_excel(company_name: str):

    invoices = list(
        invoice_collection.find({
            "company": company_name
        })
    )

    wb = Workbook()

    ws = wb.active
    ws.title = "Invoices"

    ws.append([
        "Invoice ID",
        "Vendor Name",
        "Invoice Number",
        "Invoice Date",
        "Amount",
        "Status"
    ])

    for inv in invoices:

        ws.append([
            inv.get("invoice_id", ""),
            inv.get("vendor_name", ""),
            inv.get("invoice_number", ""),
            inv.get("invoice_date", ""),
            inv.get("amount", ""),
            inv.get("status", "")
        ])

    filename = f"{company_name}_report.xlsx"

    wb.save(filename)

    return FileResponse(
        path=filename,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
@company_router.get("/company/password-info")
def get_password_info(
    token_data: dict = Depends(
        verify_company_token
    )
):

    email = token_data["email"]
    company_name=token_data["company_name"]

    company = company_collection.find_one(
        {"email": email,
         "companyName":company_name}
    )

    if not company:
        raise HTTPException(
            status_code=404,
            detail="Company not found"
        )

    return {
        "password_changed_at":
            company.get(
                "password_changed_at"
            )
    }
@company_router.post("/company/forgot-password")
def forgot_password(
    data: dict,
    background_tasks: BackgroundTasks
):

    company = company_collection.find_one({
        "email": data["email"]
    })

    if not company:
        raise HTTPException(
            status_code=404,
            detail="Company not found"
        )

    otp = str(
        random.randint(
            100000,
            999999
        )
    )

    company_collection.update_one(
        {"_id": company["_id"]},
        {
            "$set": {
                "reset_otp": otp,
                "otp_expiry":
                datetime.utcnow()
                + timedelta(minutes=10)
            }
        }
    )

    background_tasks.add_task(
        send_reset_otp,
        company["email"],
        otp
    )

    return {
        "message":
        "OTP sent successfully"
    }

@company_router.post("/company/verify-reset-otp")
def verify_reset_otp(data: dict):

    company = company_collection.find_one({
        "email": data["email"]
    })

    if not company:
        raise HTTPException(
            status_code=404,
            detail="Company not found"
        )

    if company.get("reset_otp") != data["otp"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid OTP"
        )

    expiry = company.get("otp_expiry")

    if not expiry:
        raise HTTPException(
            status_code=400,
            detail="OTP expired"
        )

    if datetime.utcnow() > expiry:
        raise HTTPException(
            status_code=400,
            detail="OTP expired"
        )

    return {
        "success": True,
        "message": "OTP verified"
    }

@company_router.put("/company/reset-password")
def reset_password(data: dict,background_tasks:BackgroundTasks):

    company = company_collection.find_one({
        "email": data["email"]
    })

    if not company:
        raise HTTPException(
            status_code=404,
            detail="Company not found"
        )
    error = validate_password(
    data["new_password"]
)

    if error:
        raise HTTPException(
        status_code=400,
        detail=error
    )
    new_hash = pwd_context.hash(
        data["new_password"]
    )

    company_collection.update_one(
        {"_id": company["_id"]},
        {
            "$set": {
                "password": new_hash,
                "password_changed_at":
                datetime.utcnow().isoformat()
            },
            "$unset": {
                "reset_otp": "",
                "otp_expiry": ""
            }
        }
    )

    background_tasks.add_task(
    notify_admin_password_changed,
    company["companyName"],
    company["email"]
)
    return {
        "message":
        "Password reset successfully"
    }

@company_router.post("/company/resend-otp")
def resend_otp(
    data: dict,
    background_tasks: BackgroundTasks
):

    company = company_collection.find_one({
        "email": data["email"]
    })

    if not company:
        raise HTTPException(
            status_code=404,
            detail="Company not found"
        )

    otp = str(
        random.randint(
            100000,
            999999
        )
    )

    company_collection.update_one(
        {"_id": company["_id"]},
        {
            "$set": {
                "reset_otp": otp,
                "otp_expiry":
                datetime.utcnow() +
                timedelta(minutes=10)
            }
        }
    )

    background_tasks.add_task(
        send_reset_otp,
        company["email"],
        otp
    )

    return {
        "message":
        "OTP resent successfully"
    }

# password validation

def validate_password(password):

    if len(password) < 8:
        return "Password must be at least 8 characters long"

    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter"

    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter"

    if not re.search(r"\d", password):
        return "Password must contain at least one number"

    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return "Password must contain at least one special character"

    return None