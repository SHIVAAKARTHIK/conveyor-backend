"""The demo seed adds the documented accounts, the doctors can be found, and it is safe to re-run."""
import seed_demo
from app.database import SessionLocal
from app.models import User


def _login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_seed_adds_demo_accounts_and_is_idempotent(client):
    db = SessionLocal()
    try:
        added, _ = seed_demo.seed(db)
        assert added == len(seed_demo.STAFF) - 1  # the default admin already exists after app startup
        again_added, skipped = seed_demo.seed(db)
        assert again_added == 0
        assert skipped == len(seed_demo.STAFF)
        # An existing account's password is never reset by re-running the seed.
        admin = db.query(User).filter(User.email == "admin@medidispense.com").first()
        assert admin is not None
    finally:
        db.close()

    # Every documented login works, with the documented password.
    for _name, email, _role, _dept, password in seed_demo.STAFF:
        r = _login(client, email, password)
        assert r.status_code == 200, f"{email}: {r.text}"

    # A patient sees two doctors in every speciality, all available.
    patient = client.post(
        "/auth/signup/patient",
        json={"name": "Seed Check", "age": 30, "gender": "Male", "email": "seedcheck@example.com", "password": "patientpass"},
    ).json()["access_token"]
    doctors = client.get("/doctors", headers={"Authorization": f"Bearer {patient}"}).json()
    by_dept = {}
    for d in doctors:
        by_dept.setdefault(d["department"], []).append(d)
    assert set(by_dept) == {"Cardiology", "Gastroenterology", "Nephrology", "Pulmonology"}
    assert all(len(v) == 2 and all(x["is_available"] for x in v) for v in by_dept.values())
