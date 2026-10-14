from fastapi import Depends, HTTPException
from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials
)
from bson import ObjectId
from datetime import datetime
from jose import JWTError, jwt
import os
from passlib.context import CryptContext
# JWT Config
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "invoiceiq_secret_key"
)

ALGORITHM = "HS256"

security = HTTPBearer()
company_scheme = HTTPBearer()
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):  
    print("===================================")
    print("TOKEN RECEIVED:", credentials.credentials)

    try:
        payload = jwt.decode(
            credentials.credentials,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )
        print("payload:",payload)
        return payload

    except JWTError as e:
        print("JWT ERROR:",str(e))
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )


def verify_company_token(
    credentials: HTTPAuthorizationCredentials = Depends(company_scheme)
):
    try:
        print("TOKEN:", credentials.credentials)
        payload = jwt.decode(
            credentials.credentials,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )
        print("PAYLOAD:",payload)
        return {
           "email": payload["sub"],
           "company_name":payload["company_name"]
        }
        

    except Exception as e:
        print("JWT ERROR:",e)
        raise HTTPException(
            status_code=401,
            detail="Invalid company token"
        )




def serialize(obj):
    if isinstance(obj, list):
        return [serialize(item) for item in obj]

    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}

    if isinstance(obj, ObjectId):
        return str(obj)

    if isinstance(obj, datetime):
        return obj.isoformat()

    return obj


def nof(val):
    return (
        None
        if (
            not val
            or str(val).strip()
            in ("", "Not Found", "null", "None")
        )
        else val
    )
