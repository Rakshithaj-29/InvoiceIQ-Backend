
from dotenv import load_dotenv
load_dotenv()
from scheduler import start_scheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from invoice_routes import invoice_router
from company_routes import company_router
from chatbot_routes import chatbot_router
from admin_routes import admin_router
from payment_router import payment_router
import os



app = FastAPI(title="InvoiceIQ API")


app.include_router(admin_router)
app.include_router(invoice_router)
app.include_router(chatbot_router)
app.include_router(company_router)
app.include_router(payment_router)
#Start APScheduler
start_scheduler()


# ── Config ──────────────────────────────────────────────────────────────────

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ── Helpers ─────────────────────────────────────────────────────────────────
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# security    = HTTPBearer()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/files", StaticFiles(directory=UPLOAD_FOLDER), name="files")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print("GLOBAL ERROR:", repr(exc))
    return JSONResponse(status_code=500, content={"error": str(exc)})


# ═══════════════════════════════════════════════════════════════════════════
# ROOT
# ═══════════════════════════════════════════════════════════════════════════
@app.get("/")
def home():
    return {"message": "InvoiceIQ Backend is running ✅"}


