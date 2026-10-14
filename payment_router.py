import os
import razorpay
from fastapi import APIRouter, HTTPException
from bson import ObjectId
from dotenv import load_dotenv
from datetime import datetime
from fastapi import HTTPException
from database import invoice_collection,reminder_collection,payments_collection
load_dotenv()
payment_router=APIRouter(tags=["Payments"])
client = razorpay.Client(
    auth=(
        os.getenv("RAZORPAY_KEY_ID"),
        os.getenv("RAZORPAY_KEY_SECRET")
    )
)
from pydantic import BaseModel

class PaymentRequest(BaseModel):
    invoice_id: str



class VerifyPaymentRequest(BaseModel):

    invoice_id: str

    razorpay_payment_id: str

    razorpay_order_id: str

    razorpay_signature: str
# =====Order Endpoint=======
@payment_router.post("/payment/create-order")
def create_payment_order(data: PaymentRequest):

    invoice = invoice_collection.find_one({
        "_id": ObjectId(data.invoice_id)
    })

    if not invoice:
        raise HTTPException(
            status_code=404,
            detail="Invoice not found"
        )

    if invoice["status"] == "Paid":
        raise HTTPException(
            status_code=400,
            detail="Invoice already paid"
        )

    amount = int(float(invoice["amount"]) * 100)

    razorpay_order = client.order.create({

        "amount": amount,

        "currency": "INR",

        "payment_capture": 1

    })

    return {

        "success": True,

        "key": os.getenv("RAZORPAY_KEY_ID"),

        "order_id": razorpay_order["id"],

        "amount": amount,

        "currency": "INR",

        "invoice": {

            "invoice_id": invoice["invoice_id"],

            "vendor_name": invoice["vendor_name"],

            "amount": invoice["amount"]

        }

    }

#=========== payment verification===========

@payment_router.post("/payment/verify")
def verify_payment(data: VerifyPaymentRequest):

    try:

        client.utility.verify_payment_signature({

            "razorpay_order_id": data.razorpay_order_id,

            "razorpay_payment_id": data.razorpay_payment_id,

            "razorpay_signature": data.razorpay_signature

        })

    except Exception:

        raise HTTPException(
            status_code=400,
            detail="Payment verification failed."
        )

    invoice = invoice_collection.find_one({
        "_id": ObjectId(data.invoice_id)
    })

    if not invoice:

        raise HTTPException(
            status_code=404,
            detail="Invoice not found"
        )

    payments_collection.insert_one({

    "invoice_object_id": ObjectId(data.invoice_id),

    "invoice_id": invoice["invoice_id"],

    "invoice_number": invoice["invoice_number"],

    "company": invoice["company"],

    "vendor_name": invoice["vendor_name"],

    

    "amount": invoice["amount"],

    "currency": "INR",

    "payment_id": data.razorpay_payment_id,

    "order_id": data.razorpay_order_id,

    "payment_status": "Success",

    "payment_method": "NetBanking",

    "paid_at": datetime.now(),

    "created_at": datetime.now()

})  
    invoice_collection.update_one(

    {
        "_id": ObjectId(data.invoice_id)
    },

    {
        "$set": {

            "status": "Paid",

            "updated_at": datetime.now()

        }

    }

)
    
    reminder_collection.update_many(

        {

            "invoice_id": invoice["invoice_id"],

            "status": "Scheduled"

        },

        {

            "$set": {

                "status": "Cancelled",

                "cancelled_at": datetime.now(),

                "reason": "Invoice Paid"

            }

        }

    )

    return {

        "message": "Payment verified successfully."

    }

