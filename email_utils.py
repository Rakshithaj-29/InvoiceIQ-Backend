import smtplib
import os

from email.mime.text import MIMEText
from dotenv import load_dotenv
import random
from datetime import datetime, timedelta
load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
# ===========send_mail function================
def send_mail(to_email, subject, body):

    msg = MIMEText(body)

    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = to_email

    try:

        server = smtplib.SMTP(
            "smtp.gmail.com",
            587
        )

        server.starttls()

        server.login(
            EMAIL_USER,
            EMAIL_PASSWORD
        )

        server.send_message(msg)

        server.quit()

    except Exception as e:

        print(f"Email sending failed: {e}")
        raise

def send_test_email(receiver_email):

    body="""
Hello,

This is a test email from InvoiceIQ.

Email integration is working successfully.

Regards,
InvoiceIQ Team
        """
    

    send_mail(
        receiver_email,
        "InvoiceIQ test email",
        body
    )

def send_company_credentials(
    company_name,
    email,
    password
):

    body = f"""
Welcome to InvoiceIQ

Your company account has been created successfully.

Company Name:
{company_name}

Login Email:
{email}

Temporary Password:
{password}


Please login using the credentials above and change your password after first login.


Regards,
InvoiceIQ Team
"""

    send_mail(
        email,
        "InvoiceIQ Company Account created",
        body
    )
def notify_admin_password_changed(
    company_name,
    company_email
):

    body = f"""
Company Password Updated

A company has successfully changed its password.

Company Name:
{company_name}

Company Email:
{company_email}

The company account is now secured with a new password.

Regards,
InvoiceIQ System
"""
    send_mail(
    EMAIL_USER,
    "InvoiceIQ Password Update Notification",
    body
)
    
def send_reset_otp(email, otp):

    body = f"""
InvoiceIQ Password Reset

Your OTP is:

{otp}

This OTP is valid for 10 minutes.

If you did not request a password reset, please ignore this email.

Regards,
InvoiceIQ Team
"""

    send_mail(
        email,
        "InvoiceIQ Password Reset OTP",
        body
    )

def notify_admin_password_reset(
    company_name,
    company_email
):

    body = f"""
Company Password Reset via Forgot Password

A company has successfully reset its password using the Forgot Password process.

Company Name:
{company_name}

Company Email:
{company_email}

This action was completed after OTP verification.

Regards,
InvoiceIQ Security System
"""

    send_mail(
    EMAIL_USER,
    "Company Password Reset via Forgot Password",
    body
)

# email reminder

def send_due_soon_reminder(
    company_email,
    invoice_id,
    vendor_name,
    amount,
    company,
    due_date,
    days_left
):

    body = f"""
Invoice Due Soon

Invoice ID:
{invoice_id}

Vendor Name:
{vendor_name}

Amount:
₹{amount}

Due Date:
{due_date}

Days Remaining:
{days_left}

Please ensure payment is completed before the due date.

Regards,
InvoiceIQ Team
"""

    send_mail(
    company_email,
    f"Invoice Due Soon - {invoice_id}",
    body
)

# due today reminder
def send_due_today_reminder(
    company_email,
    invoice_id,
    company,
    vendor_name,
    amount
):

    body = f"""
Invoice Due Today

Invoice ID:
{invoice_id}

Vendor Name:
{vendor_name}

Amount:
₹{amount}

This invoice is due today.

Regards,
InvoiceIQ Team
"""

    send_mail(
    company_email,
    f"Invoice Due Today - {invoice_id}",
    body
)
# overdue reminder
def send_overdue_reminder(
    company_email,
    invoice_id,
    amount,
    company,
    vendor_name,
    days_overdue
):

    body = f"""
Overdue Invoice Reminder

Invoice ID:
{invoice_id}

Vendor Name:
{vendor_name}

Amount:
₹{amount}

This invoice is overdue by
{days_overdue} days.

Please clear the outstanding payment as soon as possible.

Regards,
InvoiceIQ Team
"""

    send_mail(
    company_email,
    f"Overdue Invoice Reminder - {invoice_id}",
    body
)

def send_generic_payment_reminder(

    to_email,
    invoice_id,
    company,
    vendor_name,
    amount

):

    

    body = f"""
Dear {company},

This is a friendly reminder regarding the payment for the following invoice.

Invoice ID : {invoice_id}
Vendor name:{vendor_name}
Invoiec Amount : ₹{amount}

The due date for this invoice is currently unavailable in our records.

Kindly review the invoice and complete the payment at your earliest convenience.

Regards,
InvoiceIQ Team
"""

    send_mail(
    to_email,
    f"Payment Reminder - {invoice_id}",
    body
)
# forgot password otp email
def send_admin_credentials(
    admin_name,
    admin_email,
    password
):

    body = f"""
Welcome to InvoiceIQ

Hello {admin_name},

Your administrator account has been created successfully.

====================================

Name:
{admin_name}

Role:
Administrator

Email:
{admin_email}

Password:
{password}

====================================

You can now log in using the above credentials.

Regards,
InvoiceIQ Team
"""

    send_mail(
    admin_email,
    "InvoiceIQ Administrator Account",
    body
)

def send_password_reset_otp(email, otp):

    body = f"""
Dear Super Administrator,

You requested to reset your InvoiceIQ password.

Your OTP is:

{otp}

This OTP is valid for 5 minutes.

If you did not request this password reset, please ignore this email.

Regards,
InvoiceIQ Team
"""

    send_mail(
    email,
    "InvoiceIQ Password Reset OTP",
    body
)

# ===========admin reset password email==========
def send_admin_password_reset_email(
    admin_name,
    admin_email,
    new_password
):

    body = f"""
Hello {admin_name},

Your InvoiceIQ administrator password has been reset by the Super Administrator.

====================================

Email:
{admin_email}

 Password:
{new_password}

====================================

For security reasons, please log in using   password .

Regards,
InvoiceIQ Team
"""

    send_mail(
        admin_email,
        "InvoiceIQ Administrator Password Reset",
        body
    )
