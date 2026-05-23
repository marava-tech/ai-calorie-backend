from fastapi import APIRouter, HTTPException
from database import get_db
from auth import hash_password, verify_password, create_access_token
from models.user import UserCreate, UserLogin, Token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", response_model=Token, status_code=201)
async def signup(body: UserCreate):
    db = await get_db()
    if await db.users.find_one({"username": body.username}):
        raise HTTPException(status_code=400, detail="Username already taken")
    result = await db.users.insert_one({
        "username": body.username,
        "password_hash": hash_password(body.password),
    })
    return Token(access_token=create_access_token(str(result.inserted_id)))


@router.post("/login", response_model=Token)
async def login(body: UserLogin):
    db = await get_db()
    user = await db.users.find_one({"username": body.username})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return Token(access_token=create_access_token(str(user["_id"])))
