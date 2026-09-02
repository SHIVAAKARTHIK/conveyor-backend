from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Patient, User, UserRole
from app.schemas import LoginRequest, PatientSignupRequest, RegisterFcmTokenRequest, TokenResponse
from app.security import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token = create_access_token(subject=user.id, role=user.role.value)
    return TokenResponse(access_token=token, role=user.role, user_id=user.id, name=user.name)


@router.post("/signup/patient", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup_patient(payload: PatientSignupRequest, db: Session = Depends(get_db)):
    """Public self-check-in: a patient creates their own login AND their
    Patient record (with bed + QR) in one step, then is logged straight in
    - no staff involvement needed to get a patient into the system."""
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=UserRole.patient,
        phone=payload.phone,
    )
    db.add(user)
    db.flush()  # assign user.id before the Patient row references it

    patient = Patient(
        name=payload.name,
        age=payload.age,
        gender=payload.gender,
        bed_no=payload.bed_no,
        user_id=user.id,
    )
    db.add(patient)
    db.commit()
    db.refresh(user)

    token = create_access_token(subject=user.id, role=user.role.value)
    return TokenResponse(access_token=token, role=user.role, user_id=user.id, name=user.name)


@router.post("/me/fcm-token", status_code=status.HTTP_204_NO_CONTENT)
def register_fcm_token(
    payload: RegisterFcmTokenRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Android app calls this after login (and whenever the FCM token
    refreshes) so the backend knows where to push notifications for this
    user."""
    current_user.fcm_token = payload.fcm_token
    db.add(current_user)
    db.commit()
