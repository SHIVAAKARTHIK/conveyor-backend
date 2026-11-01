# MediDispense backend (FastAPI)

REST + WebSocket API for the MediDispense medicine-delivery system: patients,
consultations, prescriptions, deliveries, conveyor status and alerts, with JWT
login and role-based access (admin, doctor, nurse, technician, patient).

The rest of the project: [conveyor-admin-web](https://github.com/SHIVAAKARTHIK/conveyor-admin-web)
(web app), [conveyor-firmware-](https://github.com/SHIVAAKARTHIK/conveyor-firmware-)
(ESP32), and [conveyor-docs](https://github.com/SHIVAAKARTHIK/conveyor-docs)
(full setup guide, report, wiring).

## Quickstart (SQLite, no database server needed)

Needs Python 3.11 or newer (developed on 3.13).

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
python seed_demo.py             # creates dev.db with the demo staff accounts
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000/docs for the interactive API page.

**Use `--host 0.0.0.0`.** Without it the server only listens on your own
computer and the ESP32 conveyor cannot reach it. On Windows you must also allow
inbound TCP port 8000 through the firewall (see the setup guide in conveyor-docs).

### Demo accounts

`seed_demo.py` adds an admin, eight doctors (two each in Cardiology,
Gastroenterology, Nephrology and Pulmonology), two nurses, a technician and the
conveyor station's own login. It never changes an account that already exists,
so it is safe to run again. The logins and passwords are listed in the setup
guide in conveyor-docs. They are weak demo passwords: change them before real use.

Prefer no script? `demo.db` is the same data, ready made. Copy it over the
database before the first start:

```bash
copy demo.db dev.db
```

There are no patients in it. Patients register themselves on the web app, and a
nurse then assigns their bed.

## Roles

| Role | Does |
|---|---|
| patient | Signs up, finds a doctor, sees their deliveries, confirms receipt |
| nurse | Assigns Bed 1 or 2, confirms a delivery at the bedside with the wristband code |
| doctor | Accepts consultation requests and prescribes (this creates the delivery job) |
| technician | Runs the conveyor; the conveyor itself logs in as a technician account |
| admin | Creates staff, sees everything, can control the conveyor |

## Delivery life cycle

`preparing` (prescription written) → `in_transit` (button pressed, `dispatch`) →
`arrived` (box pushed into the chute, `mark-arrived`) → `confirmed` (nurse
`confirm`, or the patient `receive`). A delivery that cannot finish becomes
`failed` (`fail`).

## Key endpoints

- `POST /auth/login`, `POST /auth/signup/patient`
- `POST /users` (admin creates staff), `GET /doctors`
- `POST /consultations`, `POST /consultations/{id}/accept`
- `PATCH /patients/{id}/bed` (nurse or admin), `GET /patients`
- `POST /prescriptions` (doctor; refused until the patient has a bed)
- `GET /conveyor/next-job`, `POST /deliveries/{id}/dispatch`, `.../mark-arrived`, `.../fail`
- `POST /deliveries/{id}/confirm` (nurse), `.../receive` (patient)
- `GET /conveyor/status`, `POST /conveyor/simulate`
- `GET /alerts`, `GET /reports/summary`
- `WS /ws/{channel}`: live updates (`conveyor`, `alerts`, `prescriptions`)

## Settings (`.env`)

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | default `sqlite:///./dev.db`; or `mysql+pymysql://USER:PASSWORD@localhost:3306/medidispense` |
| `JWT_SECRET_KEY` | change it to a long random string for anything beyond a demo |
| `CORS_ORIGINS` | web addresses allowed to call the API; add `http://<your-ip>:3000` if you open the web app from another device |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | optional; leave blank (push notifications are only logged) |

`.env`, `dev.db` and any Firebase key are ignored by Git and never committed.

## Using MySQL instead

1. `CREATE DATABASE medidispense;`
2. Set `DATABASE_URL` in `.env` to the MySQL URL above.
3. `alembic revision --autogenerate -m "init"` then `alembic upgrade head`.
4. Run `python seed_demo.py` for the demo accounts.

## Tests

```bash
pytest
```

Nine end-to-end tests cover the full dispensing workflow, patient sign-up,
consultations, the conveyor job queue, receipt and failure handling, bed
assignment, and the demo seed. They use a throwaway database (`tests/test.db`).
