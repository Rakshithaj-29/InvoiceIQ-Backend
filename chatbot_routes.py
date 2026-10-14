from fastapi import APIRouter

chatbot_router = APIRouter(tags=["Chatbot"])
from fastapi import (
    APIRouter,
    Body
)
from vector_store import (
    embedding_model,
    faiss_index,
    faiss_metadata,
    build_faiss_index
)

from fastapi.responses import JSONResponse

from pydantic import BaseModel

from bson import ObjectId

from datetime import datetime

from groq import Groq

import json
import os
import faiss
from sentence_transformers import SentenceTransformer
from database import (
    invoice_collection,
    company_collection,
    chat_sessions_collection,
    chat_messages_collection
)

from utils import serialize

import faiss
from sentence_transformers import SentenceTransformer

# Keywords that mean the user wants ALL data — skip FAISS, use full DB
AGGREGATE_KEYWORDS = [
    "total", "all", "count", "how many", "list all", "show all",
    "sum", "every", "each", "entire", "complete", "full", "overall",
    "number of", "how much", "grand total", "invoice amount",
]

def is_aggregate_query(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in AGGREGATE_KEYWORDS)


def extract_company_from_query(question: str, companies: list) -> str | None:
    """
    Check if the question mentions a known company name.
    Returns the exact company name from DB if found, else None.
    """
    q = question.lower()
    for co in companies:
        name = co.get("companyName", "")
        if name and name.lower() in q:
            return name
    return None

STATUS_KEYWORDS = {
    "pending":   "Pending",
    "paid":      "Paid",
    "overdue":   "Overdue",
    "unpaid":    "Pending",
    "completed": "Paid",
    "due":       "Overdue",
    "cleared":   "Paid",
}
 
def extract_status_from_query(question: str):
    """Check if the question is asking about a specific invoice status."""
    q = question.lower()
    for keyword, status in STATUS_KEYWORDS.items():
        if keyword in q:
            return status
    return None

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    question: str
    history: list[ChatMessage] = []

@chatbot_router.post("/chat")
async def chat(req: ChatRequest):
    print("CHAT:", req.question)

    try:
        # ── Always fetch fresh counts from DB (never trust FAISS for totals) ──
        all_invoices_cursor = list(invoice_collection.find())
        for inv in all_invoices_cursor:
            inv.pop("embedding", None)
            inv["_id"] = str(inv["_id"])

        companies = [serialize(c) for c in company_collection.find()]
        total_invoice_count = len(all_invoices_cursor)
        total_company_count = len(companies)

        # Calculate total amount first
        total_amount = 0

        for inv in all_invoices_cursor:
            try:
                total_amount += float(inv.get("amount") or 0)
            except (ValueError, TypeError):
                pass

        question = req.question.lower()

# Direct responses (skip Groq completely)

        if "how many invoices" in question:
            return JSONResponse(
            content={
            "response":
            f"There are {total_invoice_count} invoices in the system."
        }
    )

        if "total invoices" in question:
           return JSONResponse(
           content={
            "response":
            f"There are {total_invoice_count} invoices in the system."
        }
    )

        if "total amount" in question:
            return JSONResponse(
            content={
            "response":
            f"Total invoice amount is ₹{round(total_amount, 2)}"
        }
    )

        if "total revenue" in question:
            return JSONResponse(
            content={
            "response":
            f"Total revenue is ₹{round(total_amount, 2)}"
        }
    )

        co_json = (
        json.dumps(companies, indent=2)
        if companies
    else "No companies yet."
)
        # ── Decide which invoices to send to LLM ──────────────────────────────

        # Case 1: Company-specific query — query MongoDB directly by company name
        matched_company = extract_company_from_query(req.question, companies)
        if matched_company:
            company_invoices = [
                inv for inv in all_invoices_cursor
                if inv.get("company", "").lower() == matched_company.lower()
            ]
            inv_json = json.dumps(company_invoices, indent=2) if company_invoices else f"No invoices found for {matched_company}."
            search_note = f"[Company filter: '{matched_company}' → {len(company_invoices)} invoices from DB]"
            print(f"[CHAT] Company query → '{matched_company}' → {len(company_invoices)} invoices")

        # Case 2: Status-specific query — query MongoDB directly by status
        elif extract_status_from_query(req.question):

            matched_status = extract_status_from_query(req.question)
            print("Matched status:",matched_status)
            print("----------Status values in DB-------")
            for inv in invoice_collection.find({}, {"status": 1}):
                print(repr(inv.get("status")))
            status_invoices = [
                serialize(inv)
                for inv in invoice_collection.find(
                    {"status": matched_status},
                     {
            "invoice_number": 1,
            "company": 1,
            "vendor_name": 1,
            "amount": 1,
            "status": 1,
            "invoice_date": 1
        }
                )
            ]
            for inv in status_invoices:
                for k, v in inv.items():
                    if isinstance(v, datetime):
                       print(k, v)
            inv_json = json.dumps(status_invoices, indent=2) if status_invoices else f"No {matched_status} invoices found."
            search_note = f"[Status filter: '{matched_status}' → {len(status_invoices)} invoices from DB]"
            print(f"[CHAT] Status query → '{matched_status}' → {len(status_invoices)} invoices")

        # Case 3: Aggregate query — send ALL invoices
        elif is_aggregate_query(req.question):

           invoice_summary = []

           for inv in all_invoices_cursor[:10]:

               invoice_summary.append({
               "invoice_id": inv.get("invoice_id"),
               "amount": inv.get("amount"),
               "status": inv.get("status"),
               "company": inv.get("company")
        })

           inv_json = json.dumps(invoice_summary, indent=2)

           search_note = (
        f"[Aggregate query → summary of "
        f"{total_invoice_count} invoices]"
    )

           print(
        f"[CHAT] Aggregate query → "
        f"sending summary only"
    )

        
        # Case 4: Specific search — use FAISS for semantic matching
        else:
            if faiss_index.ntotal == 0:
                inv_json = json.dumps(all_invoices_cursor, indent=2)
                search_note = f"[No FAISS index → all {total_invoice_count} invoices]"
            else:
                query_embedding = embedding_model.encode([req.question], convert_to_numpy=True)
                k = min(5, faiss_index.ntotal)
                distances, indices = faiss_index.search(query_embedding, k)
                relevant = []
                for idx in indices[0]:
                    if idx == -1:
                        continue
                    inv_id = faiss_metadata[idx]
                    inv = invoice_collection.find_one({"_id": ObjectId(inv_id)})
                    if inv:
                        inv.pop("embedding", None)
                        relevant.append(serialize(inv))
                inv_json = json.dumps(relevant, indent=2) if relevant else "No relevant invoices found."
                search_note = f"[FAISS → {len(relevant)} relevant invoices]"
                print(f"[CHAT] FAISS query → {len(relevant)} invoices")
        
        prompt = f"""DATABASE SUMMARY (from MongoDB — 100% accurate):
- Total invoices: {total_invoice_count}
- Total companies: {total_company_count}
- Total invoice amount: ₹{round(total_amount, 2)}
 
{search_note}
 
INVOICE DATA:
{inv_json}
 
COMPANIES:
{co_json}
 
TODAY: {datetime.now().strftime("%d %B %Y")}
 
Question: {req.question}"""
 
        system_prompt = (
            "You are InvoiceIQ's AI assistant. Your job is to help with invoice and company queries.\n\n"
            "WHAT YOU DO:\n"
            "- Answer questions about invoices, vendors, amounts, GSTIN, dates, statuses, companies\n"
            "- Respond naturally to follow-up messages like 'why', 'explain', 'that is wrong', "
            "'are you sure', 'what do you mean', 'clarify', 'repeat', 'incorrect' — "
            "these are normal conversation, always respond helpfully\n"
            "- Use the invoice and company data provided in the message\n"
            "- Always use DATABASE SUMMARY numbers for totals and counts\n\n"
            "WHAT YOU NEVER DO:\n"
            "- Write code (Python, JavaScript, SQL, etc.)\n"
            "- Answer science, math, history, sports, cooking questions\n"
            "- Make up invoice data that is not in the provided data\n\n"
            "FORMATTING:\n"
            "- Use **bold** for invoice IDs, amounts, company names\n"
            "- Use bullet points when listing multiple invoices\n"
            "- Use ### for section headings\n"
            "- Never write walls of text — use line breaks between sections\n"
            "- Format all amounts with ₹ symbol"
        )
 
        messages = [{"role": "system", "content": system_prompt}]
        for msg in req.history[-10:]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": prompt})
 
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.1,
        )
 
        answer = response.choices[0].message.content
        return JSONResponse(content={"response": answer})
 
    except Exception as e:
        print("CHAT ERROR:", repr(e))
        return JSONResponse(
            status_code=200,
            content={"response": f"Error: {str(e)}"}
        )

# @chatbot_router.get("/chat-history")
# def get_chat_history():

#     history = list(
#         chat_collection.find().sort("_id", 1)
#     )

#     return [serialize(msg) for msg in history]
# @chatbot_router.post("/chat-history")
# def save_chat_message(data: dict):

#     chat_collection.insert_one({
#         "role": data["role"],
#         "content": data["content"],
#         "created_at": datetime.utcnow().isoformat()
#     })

#     return {"message": "saved"}
# @chatbot_router.delete("/chat-history")
# def clear_chat():

#     chat_collection.delete_many({})

#     return {"message": "chat cleared"}   

@chatbot_router.post("/chat/new")
def create_chat():

    chat = {
        "title": "New Chat",
        "created_at": datetime.utcnow().isoformat()
    }

    result = chat_sessions_collection.insert_one(chat)

    return {
        "session_id": str(result.inserted_id)
    }

@chatbot_router.get("/chat/search")
async def search_chats(q: str):

    messages = list(
        chat_messages_collection.find(
            {
                "content": {
                    "$regex": q,
                    "$options": "i"
                }
            }
        )
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


@chatbot_router.get("/chat/sessions")
def get_chat_sessions():

    chats = list(
        chat_sessions_collection.find({"title": {"$ne": "New Chat"}})
        .sort("_id", -1)
    )

    return [serialize(chat) for chat in chats]
@chatbot_router.post("/chat/{session_id}/message")
def save_message(session_id: str, data: dict):

    chat_messages_collection.insert_one({
        "session_id": session_id,
        "role": data["role"],
        "content": data["content"],
        "created_at": datetime.utcnow().isoformat()
    })
    session = chat_sessions_collection.find_one(
    {"_id": ObjectId(session_id)}
)
    if data["role"]=="user" and session and session.get("title")=="New Chat":
        chat_sessions_collection.update_one(
            {"_id": ObjectId(session_id)},
            {
                "$set": {
                    "title": data["content"][:30]
                }
            }
        )
    return {"message": "saved"}
@chatbot_router.get("/chat/{session_id}")
def get_chat(session_id: str):

    messages = list(
        chat_messages_collection.find(
            {"session_id": session_id}
        ).sort("_id", 1)
    )

    return [serialize(msg) for msg in messages]
@chatbot_router.delete("/chat/{session_id}")
async def delete_chat(session_id: str):

    chat_sessions_collection.delete_one(
        {"_id": ObjectId(session_id)}
    )

    chat_messages_collection.delete_many(
        {"session_id": session_id}
    )

    return {"message": "Chat deleted successfully"}


class RenameChatRequest(BaseModel):
    title: str

@chatbot_router.put("/chat/{session_id}/rename")
async def rename_chat(
    session_id: str,
    data: RenameChatRequest
):
    chat_sessions_collection.update_one(
        {"_id": ObjectId(session_id)},
        {
            "$set": {
                "title": data.title
            }
        }
    )

    return {"message": "Chat renamed successfully"}
