from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    Body,
    Depends,
    HTTPException
)
import math

from fastapi.responses import (
    FileResponse,
    StreamingResponse
)


from bson import ObjectId

from datetime import datetime

from io import BytesIO

import shutil
import json
import os

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    Image,
    TableStyle
)
from vector_store import (
    embedding_model,
    faiss_index,
    faiss_metadata,
    build_faiss_index
)

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

from database import (
    invoice_collection,
    company_collection,
    reminder_collection,
    user_collection
)

from ocr import extract_text
from extract_invoice_data import extract_invoice_data

from utils import (
    serialize,
    nof,verify_token
)

from email_utils import (
    send_due_soon_reminder,
    send_due_today_reminder,
    send_overdue_reminder,send_generic_payment_reminder
)
import faiss
from sentence_transformers import SentenceTransformer


invoice_router = APIRouter(tags=["Invoices"])
UPLOAD_FOLDER = "uploads"
# ═══════════════════════════════════════════════════════════════════════════
# INVOICES
# ═══════════════════════════════════════════════════════════════════════════
@invoice_router.get("/invoices")
def get_invoices( page: int = 1,limit: int = 10,status:str="all",company:str="all"):
    query={}
    if status != "all":
        query["status"] = {
             "$regex": f"^{status}$",
        "$options": "i"
        }

    if company != "all":
        query["company"] = company

    skip = (page - 1) * limit

    invoices = list(
        invoice_collection
        .find(query)
        .sort("_id", -1)
        .skip(skip)
        .limit(limit)
    )

    total = invoice_collection.count_documents(query)

    return {
        "data": [serialize(inv) for inv in invoices],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }
@invoice_router.post("/upload-invoice")
async def upload_invoice(
    company: str = Form(...),
    file: UploadFile = File(...)
):
    try:
        print("UPLOAD HIT")

        file_path = f"{UPLOAD_FOLDER}/{file.filename}"

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        

        extracted_text = extract_text(file_path)
        

        extracted_data = extract_invoice_data(extracted_text)
        
        # Auto-increment invoice ID
        last = invoice_collection.find_one(sort=[("invoice_id", -1)])

        try:
            num = int(last["invoice_id"].replace("INV", "")) + 1 if last and "invoice_id" in last else 1
        except (ValueError, KeyError):
            num = invoice_collection.count_documents({}) + 1

        invoice_data = {
            "invoice_id": f"INV{num:03}",
            "company": company,
            "file_name": file.filename,
            "file_path": file_path,
            "status":extracted_data.get("status") or "Unknown",
            "uploaded_at": datetime.utcnow().isoformat(),
            "vendor_name": extracted_data.get("vendor_name") or "Not Found",
            "gstin": extracted_data.get("gstin") or "Not Found",
            "amount": extracted_data.get("amount") or "Not Found",
            "invoice_number": extracted_data.get("invoice_number") or "Not Found",
            "invoice_date": extracted_data.get("invoice_date") or "Not Found",
            "due_date": extracted_data.get("due_date") or "Not Found",
            "days_remaining":extracted_data.get("days_remaining"),
            "days_overdue":extracted_data.get("days_overdue"),
            "address": extracted_data.get("address") or "Not Found",
            "taxable_amount": extracted_data.get("taxable_amount") or "Not Found",
            "cgst_rate": extracted_data.get("cgst_rate") or "Not Found",
            "cgst_amount": extracted_data.get("cgst_amount") or "Not Found",
            "sgst_rate": extracted_data.get("sgst_rate") or "Not Found",
            "sgst_amount": extracted_data.get("sgst_amount") or "Not Found",
            "igst_rate": extracted_data.get("igst_rate") or "Not Found",
            "igst_amount": extracted_data.get("igst_amount") or "Not Found",
            "total_tax": extracted_data.get("total_tax") or "Not Found",
            "line_items": extracted_data.get("line_items") or [],
        }
        duplicate_invoice = invoice_collection.find_one({
        "company": invoice_data.get("company"),
        "invoice_number": invoice_data.get("invoice_number"),
        "invoice_date": invoice_data.get("invoice_date"),
        "vendor_name": invoice_data.get("vendor_name")
})

        if duplicate_invoice:

           raise HTTPException(
        status_code=400,
        detail=(
            f"Duplicate invoice detected. "
            f"Invoice {duplicate_invoice['invoice_id']} already exists."
        )
    )
        
        result = invoice_collection.insert_one(invoice_data)
        print("STEP 4: Mongo insert done", result.inserted_id)

        invoice_data["_id"] = result.inserted_id

        text = f"{invoice_data.get('vendor_name','')} {invoice_data.get('company','')}"

        embedding = embedding_model.encode([text], convert_to_numpy=True)
        print("STEP 5: Embedding generated")

        faiss_index.add(embedding)
        print("STEP 6: Added to FAISS")

        faiss_metadata.append(str(invoice_data["_id"]))

        faiss.write_index(faiss_index, "faiss_index.bin")

        with open("faiss_meta.json", "w") as f:
            json.dump(faiss_metadata, f)

        invoice_collection.update_one(
            {"invoice_id": invoice_data["invoice_id"]},
            {"$set": {"embedding": embedding[0].tolist()}}
        )

        return {
            "message": "Invoice uploaded and processed",
            "invoice_id": invoice_data["invoice_id"]
        }

    except Exception as e:
        raise
    except Exception as e:

        print("UPLOAD ERROR:", repr(e))
        raise HTTPException(
        status_code=500,
        detail=str(e)
    )
        
@invoice_router.put("/invoices/{invoice_id}")
def update_invoice(invoice_id: str, updated: dict = Body(...)):
    result = invoice_collection.update_one(
        {"_id": ObjectId(invoice_id)},
        {"$set": updated}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Rebuild FAISS index so chatbot sees updated status immediately
    build_faiss_index()
    print(f"[FAISS] Index rebuilt after update of invoice {invoice_id}")

    return {"message": "Invoice updated successfully"}

@invoice_router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: str):
    inv = invoice_collection.find_one({"_id": ObjectId(invoice_id)})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    fp = inv.get("file_path", "")
    if fp and os.path.exists(fp):
        os.remove(fp)
    invoice_collection.delete_one({"_id": ObjectId(invoice_id)})
 
    # Rebuild FAISS so chatbot sees deletion immediately
    build_faiss_index()
    print(f"[FAISS] Index rebuilt after deletion of invoice {invoice_id}")
 
    return {"message": "Invoice deleted successfully"}

@invoice_router.get("/invoices/{invoice_id}/download")
def download_invoice(invoice_id: str):
    inv = invoice_collection.find_one({"_id": ObjectId(invoice_id)})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    fp = inv.get("file_path", "")
    if not fp or not os.path.exists(fp):
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(path=fp, filename=inv.get("file_name", "invoice"), media_type="application/octet-stream")


@invoice_router.get("/invoice-search")
def invoice_search(
    
    search: str = "",
    page: int = 1,
    limit: int = 10,
    status: str = "all",
    company: str = "all"
):
    print("INVOICE SEARCH:", search)

    query = {}
    if status != "all":
        query["status"] = {
        "$regex": f"^{status}$",
        "$options": "i"
    }
    if company != "all":
        query["company"] = company

    if search.strip():
        query["$or"] = [
        {"invoice_id": {"$regex": search, "$options": "i"}},
        {"company": {"$regex": search, "$options": "i"}},
        {"vendor_name": {"$regex": search, "$options": "i"}},
        {"invoice_number": {"$regex": search, "$options": "i"}},
        {"status": {"$regex": search, "$options": "i"}}
    ]
        

    total = invoice_collection.count_documents(query)

    invoices = list(
        invoice_collection
        .find(query)
        .sort("_id", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )

    return {
        "data": [serialize(inv) for inv in invoices],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }
@invoice_router.get("/invoices/{invoice_id}/report")
def download_invoice_report(invoice_id: str):
    print("REPORT REQUEST:",invoice_id)
     
    invoice = invoice_collection.find_one(
        {"_id": ObjectId(invoice_id)}
    )

    if not invoice:
        raise HTTPException(404, "Invoice not found")

    buffer = BytesIO()

    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()

    elements = []
    logo = Image(
    "static/logo.png",
    width=100,
    height=80
)

    elements.append(logo)
    elements.append(Spacer(1, 10))


  

    elements.append(
    Paragraph(
        "AI Extracted Invoice Report",
        styles["Title"]
    )
)

    elements.append(Spacer(1, 15))

    elements.append(
    Paragraph(
        f"Generated On: {datetime.now().strftime('%d-%b-%Y %I:%M %p')}",
        styles["BodyText"]
    )
)

    elements.append(Spacer(1, 15))
    elements.append(
    Paragraph("Company Details", styles["Heading3"])
)

    company_data = [
    ["Company", invoice.get("company", "")],
    ["Vendor Name", invoice.get("vendor_name", "")],
    ["GSTIN", invoice.get("gstin", "")],
    ["Address", Paragraph(invoice.get("address", ""),styles["BodyText"])]
]

    company_table = Table(company_data, colWidths=[140, 380])

    company_table.setStyle(
    TableStyle([
        ("GRID", (0,0), (-1,-1), 1, colors.black),
        ("BACKGROUND", (0,0), (0,-1), colors.lightgrey),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
    ])
)

    elements.append(company_table)
    elements.append(Spacer(1, 20))
    elements.append(
    Paragraph("Invoice Details", styles["Heading3"])
)

    invoice_data = [
    ["Invoice ID", invoice.get("invoice_id", "")],
    ["Invoice Number", invoice.get("invoice_number", "")],
    ["Invoice Date", invoice.get("invoice_date", "")],
    ["Status", invoice.get("status", "")]
]

    invoice_table = Table(invoice_data, colWidths=[140, 380])

    invoice_table.setStyle(
    TableStyle([
        ("GRID", (0,0), (-1,-1), 1, colors.black),
        ("BACKGROUND", (0,0), (0,-1), colors.lightgrey),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
    ])
)

    elements.append(invoice_table)
    elements.append(Spacer(1, 20))
    amount_table = Table(
    [
        ["Total Amount", f"₹ {invoice.get('amount','0')}"]
    ],
    colWidths=[140, 280]
)

    amount_table.setStyle(
    TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#E8F4FD")),
        ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor("#003366")),

        ("FONTNAME", (0,0), (-1,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 18),

        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),

        ("BOX", (0,0), (-1,-1), 2, colors.HexColor("#003366")),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("TOPPADDING", (0,0), (-1,-1), 12),
    ])
)

    elements.append(amount_table)
    elements.append(Spacer(1, 25))
    elements.append(
    Paragraph(
        "Generated by Invoice Intelligence",
        styles["Italic"]
    )
)

    doc.build(elements)

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition":f"attachment;filename={invoice['invoice_id']}_report.pdf"}
    )

@invoice_router.get("/notifications")
def get_notifications():

    overdue = list(
        invoice_collection.find({
            "status": "Overdue"
        })
    )

    return [
        {
            "invoice_id": inv.get("invoice_id"),
            "vendor_name": inv.get("vendor_name"),
            "amount": inv.get("amount")
        }
        for inv in overdue
    ]

@invoice_router.post("/invoices/{invoice_id}/send-reminder")
def send_invoice_reminder(
    invoice_id: str,
    current_user: dict = Depends(verify_token)
):

    invoice = invoice_collection.find_one({
        "invoice_id": invoice_id
    })

    if not invoice:
        raise HTTPException(
            status_code=404,
            detail="Invoice not found"
        )

    # Don't send reminder for paid invoices
    if invoice.get("status") == "Paid":
        raise HTTPException(
            status_code=400,
            detail="Invoice is already paid."
        )

    company = company_collection.find_one({
        "companyName": invoice["company"]
    })

    if not company:
        raise HTTPException(
            status_code=404,
            detail="Company not found"
        )

    company_email = company.get("email")

    if not company_email:
        raise HTTPException(
            status_code=400,
            detail="Company email not found."
        )

    try:

        due_date_str = invoice.get("due_date")

        if (
        not due_date_str or
        due_date_str == "Not Found"
    ):
           send_generic_payment_reminder(
               company_email,
               invoice["invoice_id"],
               company.get("companyName"),
               invoice["vendor_name"],
               invoice["amount"],
               
           )
           return{
               "message":"Generic payment reminder sent successfully"
           }

        due_date = datetime.strptime(
        due_date_str,
        "%d %b %Y"
          )

        today = datetime.today()

        days_left = (due_date - today).days

        if days_left > 0:

            send_due_soon_reminder(
                company_email,
                invoice["invoice_id"],
                invoice["vendor_name"],
                invoice["amount"],
                company.get("companyName"),
                invoice["due_date"],
                days_left
            )

            reminder_type = "Upcoming Due"

        elif days_left == 0:

            send_due_today_reminder(
                company_email,
                invoice["invoice_id"],
                company.get("companyName"),
                invoice["vendor_name"],
                invoice["amount"],
                
            )
            

            reminder_type = "Due Today"

        else:

            send_overdue_reminder(
                company_email,
                invoice["invoice_id"],
                invoice["amount"],
                company.get("companyName"),
                invoice["vendor_name"],
                abs(days_left)
            )

            reminder_type = "Overdue"

        return {

            "message": "Reminder sent successfully",

            "reminder_type": reminder_type

        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
################## Schedule Reminder #############
@invoice_router.post("/reminders")
def schedule_reminder(
    data: dict,
    current_user: dict = Depends(verify_token)
):

    required = [
        "invoice_id",
        "reminder_type",
        "schedule_date",
        "schedule_time"
    ]

    # Validate fields
    for field in required:

        if not data.get(field):

            raise HTTPException(
                status_code=400,
                detail=f"{field} is required"

            )
    

    selected_date = datetime.strptime(
    data["schedule_date"],
    "%Y-%m-%d").date()

    if selected_date < datetime.today().date():
       raise HTTPException(
        status_code=400,
        detail="Reminder date cannot be in the past."
    )  
    selected_datetime = datetime.strptime(
    f"{data['schedule_date']} {data['schedule_time']}",
    "%Y-%m-%d %H:%M"
)

    if selected_datetime < datetime.now():
        raise HTTPException(
        status_code=400,
        detail="Reminder date and time cannot be in the past."
    ) 
    email=current_user["sub"]
    user = user_collection.find_one({
        "email": email
    })

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )
    # Find invoice
    invoice = invoice_collection.find_one({
        "invoice_id": data["invoice_id"]
    })

    if not invoice:

        raise HTTPException(
            status_code=404,
            detail="Invoice not found"
        )

    # Find company
    company = company_collection.find_one({
        "companyName":invoice["company"]
    })

    if not company:

        raise HTTPException(
            status_code=404,
            detail="Company not found"
        )
    # Check if an active reminder already exists for this invoice
    existing_reminder = reminder_collection.find_one({
    "invoice_id": invoice["invoice_id"],
    "status": "Scheduled"
})

    if existing_reminder:
        raise HTTPException(
        status_code=400,
        detail="A reminder is already scheduled for this invoice."
    )
    # Create reminder
    reminder = {

        "invoice_id": invoice["invoice_id"],

        "company": invoice["company"],

        "vendor_name": invoice["vendor_name"],

        "vendor_email": company.get("email"),

        "invoice_amount": invoice["amount"],

        "due_date": invoice.get("due_date"),

        "reminder_type": data["reminder_type"],

        "schedule_date": data["schedule_date"],

        "schedule_time": data["schedule_time"],

        "message": data.get("message", ""),

        "status": "Scheduled",

        "created_by": {

            "name": user["name"],

            "email": user["email"],

            "role": user["role"]

        },

        "created_at": datetime.now(),

        "sent_at": None

    }

    result = reminder_collection.insert_one(reminder)

    return {

        "message": "Reminder scheduled successfully",

        "id": str(result.inserted_id)

    }

@invoice_router.get("/company-email/{invoice_id}")
def get_company_email(invoice_id: str):

    invoice = invoice_collection.find_one({
        "invoice_id": invoice_id
    })

    if not invoice:
        raise HTTPException(404, "Invoice not found")

    company = company_collection.find_one({
        "companyName": invoice["company"]
    })

    if not company:
        raise HTTPException(404, "Company not found")

    return {
        "email": company["email"]
    }

# ==========reminder Endpoints==================

@invoice_router.get("/reminders")
def get_reminders(
    status: str = "All",
    reminder_type: str = "All",
    page: int = 1,
    per_page: int = 10,
    current_user: dict = Depends(verify_token)
):
    email = current_user["sub"]

    user = user_collection.find_one({
        "email": email
    })

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    query = {}
    if status != "All":
        query["status"] = status

    if reminder_type != "All":
        query["reminder_type"] = reminder_type

    # Admin -> Only own reminders
    # Super Admin -> All reminders

    

    total = reminder_collection.count_documents(query)

    reminders = list(

        reminder_collection.find(query)

        .sort("created_at", -1)

        .skip((page - 1) * per_page)

        .limit(per_page)

    )

    for reminder in reminders:

        reminder["_id"] = str(reminder["_id"])

        if reminder.get("created_at"):

            reminder["created_at"] = reminder[
                "created_at"
            ].isoformat()

        if reminder.get("updated_at"):

            reminder["updated_at"] = reminder[
                "updated_at"
            ].isoformat()

        if reminder.get("sent_at"):

            reminder["sent_at"] = reminder[
                "sent_at"
            ].isoformat()

        if reminder.get("cancelled_at"):

            reminder["cancelled_at"] = reminder[
                "cancelled_at"
            ].isoformat()

    return {

        "items": reminders,

        "total": total,

        "page": page,

        "per_page": per_page,

        "pages": math.ceil(total / per_page)

    }
import math

@invoice_router.get("/reminders/search")
def search_reminders(
    q: str = "",
    status: str = "All",
    reminder_type: str = "All",
    page: int = 1,
    per_page: int = 10,
    current_user: dict = Depends(verify_token)
):

    email = current_user["sub"]

    user = user_collection.find_one({
        "email": email
    })

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    query = {
    "$or": [
        {
            "invoice_id": {
                "$regex": q,
                "$options": "i"
            }
        },
        {
            "vendor_name": {
                "$regex": q,
                "$options": "i"
            }
        },
        {
            "vendor_email": {
                "$regex": q,
                "$options": "i"
            }
        }
    ]
}

    if status != "All":
       query["status"] = status

    if reminder_type != "All":
        query["reminder_type"] = reminder_type
    # Admin → only own reminders
    
    

    
    total = reminder_collection.count_documents(query)

    reminders = list(

        reminder_collection.find(query)

        .sort("created_at", -1)

        .skip((page - 1) * per_page)

        .limit(per_page)

    )

    for reminder in reminders:

        reminder["_id"] = str(reminder["_id"])

        if reminder.get("created_at"):
            reminder["created_at"] = reminder["created_at"].isoformat()

        if reminder.get("updated_at"):
            reminder["updated_at"] = reminder["updated_at"].isoformat()

        if reminder.get("sent_at"):
            reminder["sent_at"] = reminder["sent_at"].isoformat()

        if reminder.get("cancelled_at"):
            reminder["cancelled_at"] = reminder["cancelled_at"].isoformat()

    return {

        "items": reminders,

        "total": total,

        "page": page,

        "per_page": per_page,

        "pages": math.ceil(total / per_page)

    }
@invoice_router.put("/reminders/{reminder_id}")
def update_reminder(
    reminder_id: str,
    data: dict,
    current_user: dict = Depends(verify_token)
):

    reminder = reminder_collection.find_one({
        "_id": ObjectId(reminder_id)
    })

    if not reminder:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found"
        )

    update_data = {

        "reminder_type": data["reminder_type"],

        "schedule_date": data["schedule_date"],

        "schedule_time": data["schedule_time"],

        "message": data.get("message", ""),

        "updated_at": datetime.now(),
        "updated_by": {
            "name": current_user.get("name"),
            "email": current_user["sub"]
        }
    }

    reminder_collection.update_one(
        {"_id": ObjectId(reminder_id)},
        {
            "$set": update_data
        }
    )

    return {
        "message": "Reminder updated successfully"
    }

@invoice_router.put("/reminders/{reminder_id}/cancel")
def cancel_reminder(
    reminder_id: str,
    current_user: dict = Depends(verify_token)
):

    reminder = reminder_collection.find_one({
        "_id": ObjectId(reminder_id)
    })

    if not reminder:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found"
        )

    reminder_collection.update_one(

        {"_id": ObjectId(reminder_id)},

        {
            "$set": {
                "status": "Cancelled",
                "cancelled_at": datetime.now()
            }
        }

    )

    return {
        "message": "Reminder cancelled successfully"
    }

@invoice_router.delete("/reminders/{reminder_id}")
def delete_reminder(
    reminder_id: str,
    current_user: dict = Depends(verify_token)
):

    reminder = reminder_collection.find_one({
        "_id": ObjectId(reminder_id)
    })

    if not reminder:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found"
        )

    reminder_collection.delete_one({
        "_id": ObjectId(reminder_id)
    })

    return {
        "message": "Reminder deleted successfully"
    }

@invoice_router.post("/reminders/{reminder_id}/send")
def send_reminder_now(
    reminder_id: str,
    current_user: dict = Depends(verify_token)
):

    reminder = reminder_collection.find_one({
        "_id": ObjectId(reminder_id)
    })

    if not reminder:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found"
        )

    try:

        if reminder["reminder_type"] == "Upcoming Due":

            due_date = datetime.strptime(
                reminder["due_date"],
                "%d %b %Y"
            )

            days_left = (due_date - datetime.today()).days

            send_due_soon_reminder(
                reminder["vendor_email"],
                reminder["invoice_id"],
                reminder["vendor_name"],
                reminder["invoice_amount"],
                reminder["due_date"],
                days_left
            )

        elif reminder["reminder_type"] == "Due Today":

            send_due_today_reminder(
                reminder["vendor_email"],
                reminder["invoice_id"],
                reminder["vendor_name"],
                reminder["invoice_amount"]
            )

        elif reminder["reminder_type"] == "Overdue":

            due_date = datetime.strptime(
                reminder["due_date"],
                "%d %b %Y"
            )

            days_overdue = (
                datetime.today() - due_date
            ).days

            send_overdue_reminder(
                reminder["vendor_email"],
                reminder["invoice_id"],
                reminder["invoice_amount"],
                reminder["vendor_name"],
                days_overdue
            )

        reminder_collection.update_one(
            {"_id": ObjectId(reminder_id)},
            {
                "$set": {
                    "status": "Sent",
                    "sent_at": datetime.now(),
                    "updated_at": datetime.now()
                }
            }
        )

        return {
            "message": "Reminder sent successfully"
        }

    except Exception as e:

        reminder_collection.update_one(
            {"_id": ObjectId(reminder_id)},
            {
                "$set": {
                    "status": "Failed",
                    "updated_at": datetime.now()
                }
            }
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
    
