from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from bson import ObjectId

from database import reminder_collection
from email_utils import (
    send_due_soon_reminder,
    send_due_today_reminder,
    send_overdue_reminder,send_generic_payment_reminder
)

def check_scheduled_reminders():

    print("Checking scheduled reminders...")

    reminders = reminder_collection.find({
        "status": "Scheduled"
    })

    now = datetime.now()

    for reminder in reminders:

        try:

            scheduled_datetime = datetime.strptime(

                f"{reminder['schedule_date']} {reminder['schedule_time']}",

                "%Y-%m-%d %H:%M"

            )

            if scheduled_datetime > now:
                continue

            print(
                "Sending:",
                reminder["invoice_id"]
            )

            due_date_str = reminder.get("due_date")

            # -----------------------------
            # Generic reminder
            # -----------------------------
            if (
                not due_date_str or
                due_date_str == "Not Found"
            ):

                send_generic_payment_reminder(

                    reminder["vendor_email"],

                    reminder["invoice_id"],

                    reminder["company"],

                    reminder["vendor_name"],

                    reminder["invoice_amount"]

                )

            # -----------------------------
            # Upcoming Due
            # -----------------------------
            elif reminder["reminder_type"] == "Upcoming Due":

                due_date = datetime.strptime(
                    due_date_str,
                    "%d %b %Y"
                )

                days_left = (
                    due_date - now
                ).days

                send_due_soon_reminder(

                    reminder["vendor_email"],

                    reminder["invoice_id"],

                    reminder["vendor_name"],

                    reminder["invoice_amount"],

                    reminder["company"],

                    reminder["due_date"],

                    days_left

                )

            # -----------------------------
            # Due Today
            # -----------------------------
            elif reminder["reminder_type"] == "Due Today":

                send_due_today_reminder(

                    reminder["vendor_email"],

                    reminder["invoice_id"],

                    reminder["company"],

                    reminder["vendor_name"],

                    reminder["invoice_amount"]

                )

            # -----------------------------
            # Overdue
            # -----------------------------
            elif reminder["reminder_type"] == "Overdue":

                due_date = datetime.strptime(
                    due_date_str,
                    "%d %b %Y"
                )

                days_overdue = (
                    now - due_date
                ).days

                send_overdue_reminder(

                    reminder["vendor_email"],

                    reminder["invoice_id"],

                    reminder["invoice_amount"],

                    reminder["company"],

                    reminder["vendor_name"],

                    days_overdue

                )

            # -----------------------------
            # Update Reminder Status
            # -----------------------------
            reminder_collection.update_one(

                {
                    "_id": reminder["_id"]
                },

                {
                    "$set": {

                        "status": "Sent",

                        "sent_at": datetime.now(),

                        "updated_at": datetime.now()

                    }

                }

            )

            print(
                "Reminder Sent:",
                reminder["invoice_id"]
            )

        except Exception as e:

            print(
                "Reminder Error:",
                reminder["invoice_id"],
                str(e)
            )

            reminder_collection.update_one(

                {
                    "_id": reminder["_id"]
                },

                {
                    "$set": {

                        "status": "Failed",

                        "updated_at": datetime.now()

                    }

                }

            )
scheduler = BackgroundScheduler()

def start_scheduler():

    scheduler.add_job(

        check_scheduled_reminders,

        "interval",

        minutes=1,

        id="invoice_scheduler",

        replace_existing=True

    )

    scheduler.start()

    print("Reminder Scheduler Started")