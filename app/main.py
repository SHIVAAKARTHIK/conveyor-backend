import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.models import User, UserRole
from app.routers import alerts, auth, consultations, conveyor, deliveries, patients, prescriptions, reports, users, websockets
from app.security import hash_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

settings = get_settings()

app = FastAPI(title="MediDispense API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(patients.router)
app.include_router(prescriptions.router)
app.include_router(deliveries.router)
app.include_router(conveyor.router)
app.include_router(alerts.router)
app.include_router(reports.router)
app.include_router(consultations.router)
app.include_router(websockets.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.on_event("startup")
def on_startup():
    # For local/SQLite dev, just create tables directly. For MySQL, run
    # `alembic upgrade head` instead (see backend/README.md) and this
    # create_all becomes a harmless no-op on top of the migrated schema.
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            admin = User(
                name="Default Admin",
                email="admin@medidispense.com",
                hashed_password=hash_password("admin123"),
                role=UserRole.admin,
            )
            db.add(admin)
            db.commit()
            logger.warning(
                "No users existed - created default admin login: "
                "admin@medidispense.com / admin123  (CHANGE THIS PASSWORD)"
            )
    finally:
        db.close()
