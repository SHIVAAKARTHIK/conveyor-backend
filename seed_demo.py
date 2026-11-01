"""Adds the demo staff accounts (admin, doctors, nurses, technicians, the conveyor station)
to the database, so a new setup can sign in straight away.

    python seed_demo.py

Safe to run again: an account whose email already exists is left exactly as it is (its password
is NOT reset), and only missing ones are added. It uses whatever DATABASE_URL the backend uses
(.env, default sqlite:///./dev.db). There are no patients: patients register themselves.

These are weak, publicly documented demo passwords. Change them before real use.
"""
from app import models  # noqa: F401  (registers the tables)
from app.database import Base, SessionLocal, engine
from app.models import User, UserRole
from app.security import hash_password

DEMO_PASSWORD = "pass123"
ADMIN_PASSWORD = "admin123"
STATION_PASSWORD = "station123"

# (name, email, role, department, password)
STAFF = [
    ("Default Admin", "admin@medidispense.com", UserRole.admin, None, ADMIN_PASSWORD),
    # Doctors: two per speciality, so every speciality in the patient's "Find a Doctor" list has someone.
    ("Dr. Arjun Rao", "dr.arjun.rao@medidispense.com", UserRole.doctor, "Cardiology", DEMO_PASSWORD),
    ("Dr. Meera Nair", "dr.meera.nair@medidispense.com", UserRole.doctor, "Cardiology", DEMO_PASSWORD),
    ("Dr. Kavya Shetty", "dr.kavya.shetty@medidispense.com", UserRole.doctor, "Gastroenterology", DEMO_PASSWORD),
    ("Dr. Rohit Verma", "dr.rohit.verma@medidispense.com", UserRole.doctor, "Gastroenterology", DEMO_PASSWORD),
    ("Dr. Anita Desai", "dr.anita.desai@medidispense.com", UserRole.doctor, "Nephrology", DEMO_PASSWORD),
    ("Dr. Sanjay Kulkarni", "dr.sanjay.kulkarni@medidispense.com", UserRole.doctor, "Nephrology", DEMO_PASSWORD),
    ("Dr. Farhan Ali", "dr.farhan.ali@medidispense.com", UserRole.doctor, "Pulmonology", DEMO_PASSWORD),
    ("Dr. Lakshmi Iyer", "dr.lakshmi.iyer@medidispense.com", UserRole.doctor, "Pulmonology", DEMO_PASSWORD),
    # Ward staff
    ("Nurse Priya", "nurse@medidispense.com", UserRole.nurse, None, DEMO_PASSWORD),
    ("Nurse Ramesh", "nurse2@medidispense.com", UserRole.nurse, None, DEMO_PASSWORD),
    ("Technician Suresh", "technician@medidispense.com", UserRole.technician, None, DEMO_PASSWORD),
    # The conveyor's own login. Put this email and password in the firmware's config.h
    # (STATION_EMAIL / STATION_PASSWORD).
    ("Conveyor Station", "conveyor.station@medidispense.com", UserRole.technician, None, STATION_PASSWORD),
]


def seed(db) -> tuple[int, int]:
    """Adds any missing accounts. Returns (added, already_there)."""
    added = skipped = 0
    for name, email, role, department, password in STAFF:
        if db.query(User).filter(User.email == email).first():
            skipped += 1
            continue
        db.add(
            User(
                name=name,
                email=email,
                hashed_password=hash_password(password),
                role=role,
                department=department,
                is_available=True,
            )
        )
        added += 1
    db.commit()
    return added, skipped


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        added, skipped = seed(db)
        print(f"Added {added} account(s); {skipped} already existed and were left unchanged.")
        print(f"Database: {engine.url}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
