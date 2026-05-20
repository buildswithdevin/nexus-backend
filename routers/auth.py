import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_db
from database.models import User
from lib.auth import hash_password, verify_password, create_access_token, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Request / response schemas ────────────────────────────────────────────────

class SignupRequest(BaseModel):
    display_name: str
    username:     str
    email:        EmailStr
    password:     str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("username")
    @classmethod
    def username_format(cls, v: str) -> str:
        v = v.strip().lower()
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        if not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError("Username may only contain letters, numbers, hyphens, and underscores")
        return v


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class UpdateMeRequest(BaseModel):
    display_name: str | None = None
    username:     str | None = None
    email:        EmailStr | None = None


class AuthResponse(BaseModel):
    token:        str
    token_type:   str = "bearer"
    user:         dict


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):
    # Check email uniqueness
    existing_email = await db.execute(select(User).where(User.email == body.email))
    if existing_email.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    # Check username uniqueness
    existing_uname = await db.execute(select(User).where(User.username == body.username))
    if existing_uname.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username is already taken")

    user = User(
        display_name    = body.display_name.strip(),
        username        = body.username,
        email           = str(body.email).lower(),
        hashed_password = hash_password(body.password),
    )
    db.add(user)
    await db.flush()

    token = create_access_token(user)
    logger.info(f"New user signed up: {user.email}")
    return AuthResponse(token=token, user=user.to_dict())


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == str(body.email).lower()))
    user   = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    token = create_access_token(user)
    logger.info(f"User logged in: {user.email}")
    return AuthResponse(token=token, user=user.to_dict())


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user.to_dict()


@router.put("/me")
async def update_me(
    body: UpdateMeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
):
    if body.email and str(body.email).lower() != current_user.email:
        existing = await db.execute(select(User).where(User.email == str(body.email).lower()))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already in use")

    if body.username and body.username != current_user.username:
        existing = await db.execute(select(User).where(User.username == body.username))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Username already taken")

    if body.display_name:
        current_user.display_name = body.display_name.strip()
    if body.username:
        current_user.username = body.username.strip().lower()
    if body.email:
        current_user.email = str(body.email).lower()

    await db.flush()
    token = create_access_token(current_user)  # re-issue with updated claims
    logger.info(f"User updated profile: {current_user.email}")
    return {"token": token, "user": current_user.to_dict()}
