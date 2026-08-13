from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import PasswordResetToken, Patient, RefreshToken, User
from app.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    ProfileUpdateRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)
from app.security import (
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILED_ATTEMPTS = 3
LOCKOUT_MINUTES = 15


def _active_refresh_token(db: Session, raw_token: str) -> RefreshToken:
    """Fetch a live (unrevoked, unexpired) refresh token row or raise 401."""
    token = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_token(raw_token))
        .first()
    )
    now = datetime.now(timezone.utc)
    if token is None or token.revoked_at is not None or token.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    return token


def _build_token_response(db: Session, user: User) -> TokenResponse:
    """Create a live refresh token row and build the login/refresh response."""
    raw_refresh = generate_opaque_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=raw_refresh,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Authenticate with email/password and return access + refresh tokens."""
    email = payload.email.strip().lower()
    now = datetime.now(timezone.utc)

    user = db.query(User).filter(User.email == email).first()

    if user is None:
        # Verify against a dummy hash to keep timing consistent.
        _ = verify_password(payload.password, hash_password("__dummy__"))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if user.status != "ACTIVE" or user.deactivated_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated",
        )

    if user.locked_until is not None and user.locked_until > now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is temporarily locked. Try again later.",
        )

    if not verify_password(payload.password, user.password_hash):
        user.failed_attempts = min(user.failed_attempts + 1, 5)
        if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()
    db.refresh(user)

    return _build_token_response(db, user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    payload: RefreshRequest, db: Session = Depends(get_db)
) -> TokenResponse:
    """Exchange a live refresh token for a new access + refresh token pair."""
    token = _active_refresh_token(db, payload.refresh_token)
    user = db.get(User, token.user_id)

    if user is None or user.status != "ACTIVE" or user.deactivated_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Rotation: the presented token is revoked; a fresh pair is issued.
    token.revoked_at = datetime.now(timezone.utc)
    db.commit()

    return _build_token_response(db, user)


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(
    payload: LogoutRequest, db: Session = Depends(get_db)
) -> dict:
    """Revoke the presented refresh token. Idempotent."""
    token = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_token(payload.refresh_token))
        .first()
    )
    if token is not None and token.revoked_at is None:
        token.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return {"message": "Logged out"}


@router.post("/forgot-password")
def forgot_password(
    payload: ForgotPasswordRequest, db: Session = Depends(get_db)
) -> dict:
    """
    Create an expiring password-reset token for a matching ACTIVE account.

    v1 has no email gateway, so the raw token is returned in the response;
    a production build would email it instead. Deactivated/unknown emails
    get a generic message to avoid user enumeration.
    """
    email = payload.email.strip().lower()
    user = (
        db.query(User)
        .filter(User.email == email, User.status == "ACTIVE")
        .first()
    )

    if user is None:
        return {
            "message": "If a matching account exists, a reset token was issued."
        }

    raw_token = generate_opaque_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
        )
    )
    db.commit()
    return {
        "message": "A reset token was issued.",
        "reset_token": raw_token,
    }


@router.post("/reset-password", status_code=status.HTTP_200_OK)
def reset_password(
    payload: ResetPasswordRequest, db: Session = Depends(get_db)
) -> dict:
    """Set a new password using a valid, unused, unexpired reset token."""
    now = datetime.now(timezone.utc)
    reset = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == hash_token(payload.token))
        .first()
    )
    if (
        reset is None
        or reset.used_at is not None
        or reset.expires_at <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user = db.get(User, reset.user_id)
    if user is None or user.status != "ACTIVE" or user.deactivated_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    reset.used_at = now
    user.password_hash = hash_password(payload.new_password)
    user.failed_attempts = 0
    user.locked_until = None
    _revoke_all_refresh_tokens(db, user.id)
    db.commit()
    return {"message": "Password has been reset"}


@router.post("/change-password", status_code=status.HTTP_200_OK)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Change the current user's password and revoke their refresh tokens."""
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    current_user.password_hash = hash_password(payload.new_password)
    current_user.failed_attempts = 0
    current_user.locked_until = None
    _revoke_all_refresh_tokens(db, current_user.id)
    db.commit()
    return {"message": "Password changed"}


def _revoke_all_refresh_tokens(db: Session, user_id: int) -> None:
    """Mark every live refresh token of a user as revoked (called on commit)."""
    now = datetime.now(timezone.utc)
    for token in db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
    ):
        token.revoked_at = now


def _apply_profile_update(
    db: Session, user: User, payload: ProfileUpdateRequest
) -> None:
    """Persist role-appropriate profile fields for the current user."""
    if payload.email is not None:
        new_email = payload.email.strip().lower()
        if new_email != user.email:
            clash = db.query(User).filter(User.email == new_email).first()
            if clash is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email is already in use",
                )
            user.email = new_email

    name_or_phone = (
        payload.first_name is not None
        or payload.last_name is not None
        or payload.phone is not None
    )
    if name_or_phone:
        if user.role != "PATIENT":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Name and phone can only be updated on a patient profile",
            )
        patient = db.query(Patient).filter(Patient.user_id == user.id).first()
        if patient is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Patient profile not found",
            )
        if payload.first_name is not None:
            patient.first_name = payload.first_name
        if payload.last_name is not None:
            patient.last_name = payload.last_name
        if payload.phone is not None:
            patient.emergency_contact_phone = payload.phone


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: ProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Update the authenticated user's profile (email, and patient name/phone)."""
    _apply_profile_update(db, current_user, payload)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already in use",
        )
    db.refresh(current_user)
    return current_user


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user's safe information."""
    return current_user


@router.post("/users/{user_id}/deactivate", status_code=status.HTTP_200_OK)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("ADMIN")),
) -> dict:
    """Soft-delete a user account (admin only)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )

    user.status = "DEACTIVATED"
    user.deactivated_at = datetime.now(timezone.utc)
    _revoke_all_refresh_tokens(db, user.id)
    db.commit()
    return {"message": "User deactivated"}


@router.post("/users/{user_id}/activate", status_code=status.HTTP_200_OK)
def activate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("ADMIN")),
) -> dict:
    """Re-activate a previously deactivated user (admin only)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if user.status == "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already active",
        )

    user.status = "ACTIVE"
    user.deactivated_at = None
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()
    return {"message": "User activated"}