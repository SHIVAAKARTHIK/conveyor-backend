# MediDispense backend (FastAPI)

REST + WebSocket API for the IoT-Based Automated Medicine Dispensing Conveyor
System project: patients, prescriptions, deliveries, conveyor status, and
alerts, with JWT auth and role-based access (admin/doctor/nurse/pharmacist/technician).

## Quickstart (SQLite, no MySQL server needed)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs for interactive Swagger UI.

On first run, if the `users` table is empty, a default admin is created:
`admin@medidispense.com` / `admin123` — **change this password** once you've
logged in and created real accounts via `POST /users` (or add a "change
password" endpoint before any real deployment).

## Switching to MySQL

1. Create a database, e.g. `CREATE DATABASE medidispense;`
2. In `.env`, set:
   `DATABASE_URL=mysql+pymysql://USER:PASSWORD@localhost:3306/medidispense`
3. Run migrations instead of relying on auto-create:
   ```bash
   alembic revision --autogenerate -m "init"
   alembic upgrade head
   ```

## Enabling real push notifications

By default, FCM sends are logged to the console instead of actually sent
(so you can build/test with zero Firebase setup). To enable real push:

1. Create a free Firebase project at https://console.firebase.google.com
2. Project settings → Service accounts → "Generate new private key" → save
   the JSON file somewhere safe (do not commit it).
3. In `.env`, set `FIREBASE_SERVICE_ACCOUNT_PATH=C:\path\to\key.json`

This only uses Firebase Cloud Messaging (free, unlimited) — no Firestore,
no Cloud Functions, no billing plan required.

## Key endpoints

- `POST /auth/login` — get a JWT
- `POST /auth/me/fcm-token` — Android app registers its push token
- `POST /patients`, `GET /patients/{id}/qr` — register patient + get QR image
- `POST /prescriptions` — doctor creates a prescription (auto-creates a `Delivery`)
- `POST /deliveries/{id}/mark-prepared` — pharmacist
- `POST /deliveries/{id}/verify-medicine` — nurse scans medicine+patient QR
- `POST /deliveries/{id}/mark-arrived` — conveyor reached the ward
- `POST /deliveries/{id}/confirm` — bedside re-scan, final confirmation
- `GET /conveyor/status`, `POST /conveyor/simulate` — mock hardware for now
- `GET /alerts`, `POST /alerts/{id}/resolve`
- `GET /reports/summary` — admin dashboard charts
- `WS /ws/alerts`, `WS /ws/conveyor` — live updates for the Next.js dashboard

## Tests

```bash
pytest
```
