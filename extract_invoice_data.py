"""
Invoice field extraction — InvoiceIQ
1. Clean OCR noise
2. Groq LLM extraction (primary — handles messy scanned text)
3. Regex fallback for any field LLM missed
"""

import re, os, json
from dotenv import load_dotenv
from datetime import datetime,timedelta
load_dotenv()

# ── OCR noise correction ────────────────────────────────────────────────────
OCR_FIXES = {
    "GST1N": "GSTIN", "6STIN": "GSTIN", "GSIN": "GSTIN",
    "GSTN": "GSTIN",  "GSTiN": "GSTIN", "G$TIN": "GSTIN",
    "GSTI N": "GSTIN","lnvoice": "Invoice", "lnv": "Inv",
    "Rs |": "Rs.", "R$": "Rs", "rS": "Rs",
}

def clean_ocr_text(text: str) -> str:
    for wrong, right in OCR_FIXES.items():
        text = text.replace(wrong, right)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [l for l in text.split("\n") if len(l.strip()) > 1]
    return "\n".join(lines)


# ── LLM extraction ──────────────────────────────────────────────────────────
def extract_with_llm(text: str) -> dict:
    try:
        from groq import Groq
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return {}
        client = Groq(api_key=api_key)
        truncated = text[:3000]
        prompt = f"""You are an expert at reading Indian GST invoices, including noisy OCR from scanned documents.

            Extract these fields and return ONLY a valid JSON object (no markdown, no explanation):
            - vendor_name: business/shop name that issued the invoice (usually at top)
            - gstin: 15-char GST Identification Number, or null
            - amount: final total payable as numeric string e.g. "15000.00", or null
            - invoice_number: invoice/bill number, or null
            - invoice_date: date as found in the document, or null
            - due_date: due date if mentioned, or null
            - If invoice contains "Payment due within X days", calculate due date from invoice_date and return it
            - address: vendor address, or null
            - taxable_amount: amount before tax / subtotal as numeric string, or null
            - cgst_rate: CGST percentage as numeric string e.g. "9", or null
            - cgst_amount: CGST tax amount as numeric string e.g. "1350.00", or null
            - sgst_rate: SGST percentage as numeric string e.g. "9", or null
            - sgst_amount: SGST tax amount as numeric string e.g. "1350.00", or null
            - igst_rate: IGST percentage as numeric string e.g. "18", or null
            - igst_amount: IGST tax amount as numeric string e.g. "2700.00", or null
            - total_tax: total tax amount (CGST+SGST or IGST) as numeric string, or null
            - line_items: array of objects with keys: description, quantity, unit_price, amount, hsn_code

            Rules:
            - vendor_name is the SELLER not the buyer
            - Use context clues to handle OCR noise
            - Never make up values — return null if unsure
            - For amount use Grand Total / Total Amount / Net Payable (largest final figure)
            - CGST and SGST are usually equal (both 9% for 18% GST)
            - IGST is used for interstate invoices instead of CGST+SGST
            - line_items: extract each product/service row, return empty array [] if no table found
            - For hsn_code return null if not found

        Invoice text:
        {truncated}"""

        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=1000,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.MULTILINE).strip()
        raw = re.sub(r"```$", "", raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
    
        result = {}
        str_fields = [
            "vendor_name", "gstin", "amount", "invoice_number", "invoice_date","due_date", "address",
            "taxable_amount", "cgst_rate", "cgst_amount", "sgst_rate", "sgst_amount",
            "igst_rate", "igst_amount", "total_tax"
        ]
        for key in str_fields:
            val = parsed.get(key)
            result[key] = str(val).strip() if val and str(val).strip() not in ("", "null", "None") else None

        # line_items is a list, handle separately
        items = parsed.get("line_items", [])
        result["line_items"] = items if isinstance(items, list) else []

        return result
    except Exception as e:
        print(f"[LLM ERROR] {e}")
        return {}
       


# ── Regex fallbacks ─────────────────────────────────────────────────────────
def regex_gstin(text):
    no_sp = text.replace(" ", "")
    m = re.search(r"\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}", no_sp, re.IGNORECASE)
    if m: return m.group().upper()
    m = re.search(r"\d{2}[A-Z0-9]{5}\d{4}[A-Z0-9]{1,4}", no_sp, re.IGNORECASE)
    return m.group().upper() if m else None

def regex_amount(text, lines):
    keywords = ["GRAND TOTAL","ROUND TOTAL","NET PAYABLE","AMOUNT PAYABLE",
                "TOTAL PAYABLE","TOTAL AMOUNT","NET AMOUNT","NET TOTAL",
                "PAYABLE AMOUNT","INVOICE TOTAL","TOTAL"]
    num_pat = r"[\d,]+\.?\d*"
    for kw in keywords:
        for line in lines:
            if kw in line.upper():
                cleaned = re.sub(r"(Rs\.?|INR|₹)", "", line, flags=re.IGNORECASE)
                nums = re.findall(num_pat, cleaned)
                big = [n.replace(",","") for n in nums if float(n.replace(",","") or 0) > 100]
                if big: return big[-1]
    matches = re.findall(r"(?:Rs\.?|₹|INR)\s*([\d,]+\.?\d*)", text, re.IGNORECASE)
    if matches:
        amounts = [m.replace(",","") for m in matches]
        try: return str(max(amounts, key=lambda x: float(x)))
        except: return amounts[-1]
    return None

def regex_date(lines):

    # Priority patterns
    labeled_patterns = [

        r"Invoice\s*Date[:\s]*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
        r"Invoice\s*Date[:\s]*([0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})",

        r"Date[:\s]*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
        r"Date[:\s]*([0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})",

        r"Dated[:\s]*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
        r"Dated[:\s]*([0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})",
    ]

    for line in lines:

        for pattern in labeled_patterns:

            match = re.search(
                pattern,
                line,
                re.IGNORECASE
            )

            if match:
                print(
                    "DATE FOUND:",
                    match.group(1)
                )
                return match.group(1)

    # Generic fallback
    patterns = [
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b",
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2}\b",
        r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b",
        r"\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\b",
        r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
    ]

    for line in lines:

        for pattern in patterns:

            match = re.search(
                pattern,
                line,
                re.IGNORECASE
            )

            if match:
                print(
                    "DATE FOUND:",
                    match.group()
                )
                return match.group()

    return None


def regex_due_date(text, lines, invoice_date=None):

    patterns = [
    r"Due Date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    r"Payment Due[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    r"Due On[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",

    r"Due Date[:\s]*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    r"Payment Due[:\s]*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    r"Due On[:\s]*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
]
    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            return match.group(1)

    credit_match = re.search(
        r"payment due within\s+(\d+)\s+days",
        text,
        re.IGNORECASE
    )

    if credit_match and invoice_date:

        try:

            days = int(
                credit_match.group(1)
            )

            date_formats = [
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y-%m-%d",
            "%d-%b-%Y",
            "%d-%B-%Y"
            ]

            inv_date = None

            for fmt in date_formats:
                try:
                    inv_date = datetime.strptime(
                    invoice_date,
                    fmt
                    )
                    break
                except:
                    continue

            if not inv_date:
               return None

            return (
                inv_date +
                timedelta(days=days)
            ).strftime("%Y-%m-%d")

        except:
            pass

    return None

def regex_invoice_number(text):
    patterns = [
        r"(?:Invoice\s*No\.?|Bill\s*No\.?|Inv\.?\s*No\.?|Bill\s*#)\s*[:\-]?\s*([\w\/\-]+)",
        r"\b(INV[\-\/]?\d+)\b",
        r"\b(BILL[\-\/]?\d+)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m: return m.group(1).strip()
    return None

def regex_vendor_name(lines):
    # ✅ FIXED: removed BILL and INVOICE from skip list + widened to 10 lines
    skip = ["GST","DATE","CASHIER","TOTAL","PHONE","MOB","HTTP",
            "WWW","EMAIL","FAX","PH:","TEL","PAGE","TAX"]
    for line in lines[:10]:
        cl = line.strip()
        if len(cl) >= 4 and not any(w in cl.upper() for w in skip):
            if re.search(r"[A-Za-z]{3,}", cl):
                return cl
    return None

def regex_address(lines, vendor_name):
    keywords = ["road","street","nagar","colony","district","taluk",
                "karnataka","maharashtra","tamil","mumbai","delhi",
                "bangalore","mangalore","pincode","pin"]
    candidates = []
    for line in lines:
        cl = line.strip()
        if not cl or len(cl) < 5: continue
        if vendor_name and cl == vendor_name: continue
        if any(kw in cl.lower() for kw in keywords):
            candidates.append(cl)
        if re.search(r"\b\d{6}\b", cl):
            candidates.append(cl)
    if candidates:
        return " ".join(dict.fromkeys(candidates))[:200]
    if vendor_name:
        for i, line in enumerate(lines):
            if vendor_name in line:
                addr = [l.strip() for l in lines[i+1:i+4] if l.strip()]
                if addr: return " ".join(addr)
    return None

def regex_tax_amount(lines, keyword):
    """Extract CGST, SGST or IGST amount from invoice lines."""
    for line in lines:
        if keyword.upper() in line.upper():
            nums = re.findall(r"[\d,]+\.?\d*", line.replace(",", ""))
            # Filter out small numbers that are likely percentages
            amounts = [n for n in nums if float(n or 0) > 10]
            if amounts:
                return amounts[-1]
    return None

def regex_tax_rate(lines, keyword):
    """Extract tax rate percentage for CGST, SGST or IGST."""
    for line in lines:
        if keyword.upper() in line.upper():
            m = re.search(r"(\d+\.?\d*)\s*%", line)
            if m:
                return m.group(1)
            nums = re.findall(r"\b(\d{1,2}\.?\d*)\b", line)
            rates = [n for n in nums if 0 < float(n) <= 28]
            if rates:
                return rates[0]
    return None

def regex_taxable_amount(lines):
    """Extract taxable amount / subtotal before tax."""
    keywords = ["TAXABLE AMOUNT", "TAXABLE VALUE", "SUB TOTAL",
                "SUBTOTAL", "BASIC AMOUNT", "VALUE OF SUPPLY"]
    for kw in keywords:
        for line in lines:
            if kw in line.upper():
                nums = re.findall(r"[\d,]+\.?\d*", line.replace(",", ""))
                big = [n for n in nums if float(n or 0) > 10]
                if big:
                    return big[-1]
    return None


# ── Main entry point ────────────────────────────────────────────────────────
def extract_invoice_data(raw_text: str) -> dict:
    text  = clean_ocr_text(raw_text)
    lines = text.split("\n")
    print("\n==============OCR TEXT========")
    print(text)
    print("\n=========================")
    print("[OCR CLEANED PREVIEW]\n", text[:500])

    llm = extract_with_llm(text)
    print("[LLM RESULT]", llm)

    vendor = llm.get("vendor_name") or regex_vendor_name(lines)
    invoice_date = (
    llm.get("invoice_date")
    or regex_date(lines)
)

    due_date = (
    llm.get("due_date")
    or regex_due_date(
        text,
        lines,
        invoice_date
    )
)
    status=detect_status(
        text,
        {
            "due_date":due_date
        }
    )
    status=check_overdue(
        status,
        due_date
    )
    days_remaining, days_overdue = (
    calculate_due_metrics(
        due_date
    )
)
    print("STATUS:", status)
    print("DAYS REMAINING:", days_remaining)
    print("DAYS OVERDUE:", days_overdue)
    print("INVOICE DATE:", invoice_date)
    print("DUE DATE:", due_date)

    result = {
        # Basic fields
        "vendor_name":    vendor                              or None,
        "status":status,
        "gstin":          llm.get("gstin")                   or regex_gstin(text)                    or None,
        "amount":         llm.get("amount")                  or regex_amount(text, lines)             or None,
        "invoice_number": llm.get("invoice_number")          or regex_invoice_number(text)            or None,
        "invoice_date":   invoice_date or None,
        "due_date":due_date or None,
        "address":        llm.get("address")                 or regex_address(lines, vendor)          or None,
        "days_remaining":days_remaining,
        "days_overdue":days_overdue,
        # Tax fieldss
        "taxable_amount": llm.get("taxable_amount")          or regex_taxable_amount(lines)           or None,
        "cgst_rate":      llm.get("cgst_rate")               or regex_tax_rate(lines, "CGST")         or None,
        "cgst_amount":    llm.get("cgst_amount")             or regex_tax_amount(lines, "CGST")       or None,
        "sgst_rate":      llm.get("sgst_rate")               or regex_tax_rate(lines, "SGST")         or None,
        "sgst_amount":    llm.get("sgst_amount")             or regex_tax_amount(lines, "SGST")       or None,
        "igst_rate":      llm.get("igst_rate")               or regex_tax_rate(lines, "IGST")         or None,
        "igst_amount":    llm.get("igst_amount")             or regex_tax_amount(lines, "IGST")       or None,
        "total_tax":      llm.get("total_tax")               or None,

        # Line items
        "line_items":     llm.get("line_items")              or [],
    }
    print("[FINAL RESULT]", {k:v for k,v in result.items() if k != "line_items"})
    print("[LINE ITEMS]", len(result["line_items"]), "items found")
    return result

# status detection

def detect_status(text, invoice_data):

    text_upper = text.upper()

    # PAID indicators
    paid_keywords = [
        "PAID",
        "PAD",
        "P A I D",

        "PAYMENT RECEIVED",
        "AMOUNT DUE: 0",
        "AMOUNT DUE 0",
        "RECEIVED"
    ]

    for keyword in paid_keywords:
        if keyword in text_upper:
            return "Paid"

    # Cash invoices
    if "CASH" in text_upper:
        return "Paid"
    
    
    # Credit invoices
    if (
        "CREDIT" in text_upper
        or "PAYMENT DUE" in text_upper
        or invoice_data.get("due_date")
    ):
        return "Pending"

    return "Unknown"

# Overdue detection

def check_overdue(status, due_date):

    if (
        status != "Pending"
        or not due_date
    ):
        return status

    date_formats = [
        "%d %b %Y",
        "%d %B %Y",
        "%d-%m-%Y",
        "%Y-%m-%d"
    ]

    parsed_due = None

    for fmt in date_formats:
        try:
            parsed_due = datetime.strptime(
                due_date,
                fmt
            )
            break
        except:
            continue

    if not parsed_due:
        return status

    if datetime.now() > parsed_due:
        return "Overdue"

    return status



def calculate_due_metrics(due_date):

    if not due_date:
        return None, None

    formats = [
        "%d %b %Y",
        "%d-%m-%Y",
        "%Y-%m-%d"
    ]

    parsed_date = None

    for fmt in formats:
        try:
            parsed_date = datetime.strptime(
                due_date,
                fmt
            )
            break
        except:
            pass

    if not parsed_date:
        return None, None

    diff = (
        parsed_date.date()
        - datetime.now().date()
    ).days

    if diff >= 0:
        return diff, 0

    return 0, abs(diff)