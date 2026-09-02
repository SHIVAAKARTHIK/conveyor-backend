"""End-to-end regression test covering the same flow verified manually via
curl: login -> create staff -> register patient -> prescribe -> pharmacist
scans to verify+dispatch (mismatch + happy path + bed override) -> arrive ->
confirm -> conveyor jam alert -> role enforcement -> reports summary."""


def login(client, email, password="pass123"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def create_staff(client, admin_token, role):
    r = client.post(
        "/users",
        headers=auth_headers(admin_token),
        json={
            "name": f"Test {role}",
            "email": f"{role}@medidispense.com",
            "password": "pass123",
            "role": role,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_full_dispensing_workflow(client):
    admin_token = login(client, "admin@medidispense.com", "admin123")

    for role in ["doctor", "nurse", "pharmacist", "technician"]:
        create_staff(client, admin_token, role)

    doctor = login(client, "doctor@medidispense.com")
    nurse = login(client, "nurse@medidispense.com")
    pharmacist = login(client, "pharmacist@medidispense.com")
    technician = login(client, "technician@medidispense.com")

    # --- Patient registration ---
    r = client.post(
        "/patients",
        headers=auth_headers(doctor),
        json={"name": "Ramesh Kumar", "age": 54, "gender": "Male", "bed_no": "301"},
    )
    assert r.status_code == 201, r.text
    patient = r.json()
    patient_qr = patient["qr_code"]

    # Nurse (wrong role) cannot register a patient.
    r = client.post(
        "/patients",
        headers=auth_headers(nurse),
        json={"name": "Should Fail", "age": 1, "gender": "Male", "bed_no": "1"},
    )
    assert r.status_code == 403

    # --- Prescription (auto-creates a Delivery) ---
    r = client.post(
        "/prescriptions",
        headers=auth_headers(doctor),
        json={
            "patient_id": patient["id"],
            "notes": "Post-lunch dose",
            "medicines": [{"name": "Metformin", "dosage": "500mg", "form": "tablet", "qty": 1}],
        },
    )
    assert r.status_code == 201, r.text
    prescription = r.json()
    correct_med_code = prescription["medicines"][0]["medicine_code"]

    deliveries = client.get("/deliveries", headers=auth_headers(doctor)).json()
    delivery = next(d for d in deliveries if d["prescription_id"] == prescription["id"])
    assert delivery["status"] == "preparing"

    # Nurse (wrong role now - dispatch is the pharmacist's job) cannot verify-medicine.
    r = client.post(
        f"/deliveries/{delivery['id']}/verify-medicine",
        headers=auth_headers(nurse),
        json={"delivery_id": delivery["id"], "scanned_medicine_code": "irrelevant"},
    )
    assert r.status_code == 403

    # --- Pharmacist scans a WRONG medicine QR -> mismatch alert, delivery fails ---
    # (No mark-prepared step anymore - the scan itself is the verification.)
    r = client.post(
        f"/deliveries/{delivery['id']}/verify-medicine",
        headers=auth_headers(pharmacist),
        json={
            "delivery_id": delivery["id"],
            "scanned_medicine_code": "not-the-real-code",
        },
    )
    assert r.status_code == 409

    alerts = client.get("/alerts", headers=auth_headers(admin_token)).json()
    mismatch_alerts = [a for a in alerts if a["type"] == "medicine_mismatch"]
    assert len(mismatch_alerts) == 1
    assert mismatch_alerts[0]["status"] == "open"

    # --- Second prescription: full happy path through to confirmation ---
    r = client.post(
        "/prescriptions",
        headers=auth_headers(doctor),
        json={
            "patient_id": patient["id"],
            "notes": "Evening dose",
            "medicines": [{"name": "Paracetamol", "dosage": "650mg", "form": "tablet", "qty": 2}],
        },
    )
    prescription2 = r.json()
    med_code_2 = prescription2["medicines"][0]["medicine_code"]
    deliveries = client.get("/deliveries", headers=auth_headers(doctor)).json()
    delivery2 = next(d for d in deliveries if d["prescription_id"] == prescription2["id"])

    r = client.post(
        f"/deliveries/{delivery2['id']}/verify-medicine",
        headers=auth_headers(pharmacist),
        json={
            "delivery_id": delivery2["id"],
            "scanned_medicine_code": med_code_2,
        },
    )
    assert r.status_code == 200
    dispatched = r.json()
    assert dispatched["status"] == "in_transit"
    # Bed auto-filled from the patient record - the pharmacist never typed it.
    assert dispatched["bed_no"] == "301"
    assert dispatched["patient_name"] == "Ramesh Kumar"
    assert dispatched["patient_bed_no"] == "301"
    assert len(dispatched["medicines"]) == 1

    # A pharmacist can override a stale bed before dispatch.
    r = client.post(
        "/prescriptions",
        headers=auth_headers(doctor),
        json={
            "patient_id": patient["id"],
            "notes": "Moved beds",
            "medicines": [{"name": "Ibuprofen", "dosage": "400mg", "form": "tablet", "qty": 1}],
        },
    )
    prescription3 = r.json()
    med_code_3 = prescription3["medicines"][0]["medicine_code"]
    deliveries = client.get("/deliveries", headers=auth_headers(doctor)).json()
    delivery3 = next(d for d in deliveries if d["prescription_id"] == prescription3["id"])
    r = client.post(
        f"/deliveries/{delivery3['id']}/verify-medicine",
        headers=auth_headers(pharmacist),
        json={"delivery_id": delivery3["id"], "scanned_medicine_code": med_code_3, "bed_no": "305"},
    )
    assert r.status_code == 200
    assert r.json()["bed_no"] == "305"
    assert r.json()["patient_bed_no"] == "301"  # patient record itself is untouched

    r = client.post(f"/deliveries/{delivery3['id']}/mark-arrived", headers=auth_headers(nurse))
    assert r.status_code == 200

    r = client.post(f"/deliveries/{delivery2['id']}/mark-arrived", headers=auth_headers(nurse))
    assert r.status_code == 200
    assert r.json()["status"] == "arrived"

    r = client.post(
        f"/deliveries/{delivery2['id']}/confirm",
        headers=auth_headers(nurse),
        json={"delivery_id": delivery2["id"], "scanned_patient_qr": patient_qr},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"

    # --- Conveyor jam simulation raises a technician-targeted alert ---
    r = client.post(
        "/conveyor/simulate",
        headers=auth_headers(technician),
        json={"motor_status": "jammed", "position": "corridor-2", "speed": 0},
    )
    assert r.status_code == 200
    assert r.json()["motor_status"] == "jammed"

    # Doctor is not allowed to drive the conveyor simulator.
    r = client.post("/conveyor/simulate", headers=auth_headers(doctor), json={"motor_status": "idle"})
    assert r.status_code == 403

    alerts = client.get("/alerts", headers=auth_headers(admin_token)).json()
    assert any(a["type"] == "conveyor_jam" for a in alerts)

    # --- Reports summary aggregates everything above ---
    r = client.get("/reports/summary?days=7", headers=auth_headers(admin_token))
    assert r.status_code == 200
    summary = r.json()
    assert summary["total_deliveries"] == 3
    assert summary["open_alerts"] == 2
    assert summary["alert_counts_by_type"]["medicine_mismatch"] == 1
    assert summary["alert_counts_by_type"]["conveyor_jam"] == 1

    # --- QR image endpoint ---
    r = client.get(f"/patients/{patient['id']}/qr", headers=auth_headers(doctor))
    assert r.status_code == 200
    assert r.json()["qr_image_base64"].startswith("data:image/png;base64,")


def test_patient_signup_and_own_data_access(client):
    admin_token = login(client, "admin@medidispense.com", "admin123")
    doctor = create_staff(client, admin_token, "doctor")
    doctor_token = login(client, "doctor@medidispense.com")

    # --- self signup: creates a login + a linked Patient record in one call ---
    r = client.post(
        "/auth/signup/patient",
        json={
            "name": "Sita Rao",
            "age": 41,
            "gender": "Female",
            "bed_no": "101",
            "email": "sita@medidispense.com",
            "password": "patientpass",
        },
    )
    assert r.status_code == 201, r.text
    token_data = r.json()
    assert token_data["role"] == "patient"
    patient_token = token_data["access_token"]

    # Duplicate email is rejected.
    r = client.post(
        "/auth/signup/patient",
        json={
            "name": "Sita Rao",
            "age": 41,
            "gender": "Female",
            "bed_no": "101",
            "email": "sita@medidispense.com",
            "password": "patientpass",
        },
    )
    assert r.status_code == 409

    # --- the patient can see their own record and their own QR ---
    r = client.get("/patients/me", headers=auth_headers(patient_token))
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["name"] == "Sita Rao"
    assert me["bed_no"] == "101"

    r = client.get("/patients/me/qr", headers=auth_headers(patient_token))
    assert r.status_code == 200
    assert r.json()["qr_code"] == me["qr_code"]
    assert r.json()["qr_image_base64"].startswith("data:image/png;base64,")

    # --- but a patient cannot browse the general patient list or another record ---
    assert client.get("/patients", headers=auth_headers(patient_token)).status_code == 403
    assert client.get(f"/patients/{me['id']}", headers=auth_headers(patient_token)).status_code == 403

    # --- a patient's delivery tracker only ever shows their own deliveries ---
    r = client.post(
        "/prescriptions",
        headers=auth_headers(doctor_token),
        json={
            "patient_id": me["id"],
            "notes": "Tracker test",
            "medicines": [{"name": "Amoxicillin", "dosage": "250mg", "form": "capsule", "qty": 1}],
        },
    )
    assert r.status_code == 201, r.text

    # A second, unrelated patient's delivery must stay invisible to Sita.
    r = client.post(
        "/patients",
        headers=auth_headers(doctor_token),
        json={"name": "Other Patient", "age": 30, "gender": "Male", "bed_no": "202"},
    )
    other_patient = r.json()
    r = client.post(
        "/prescriptions",
        headers=auth_headers(doctor_token),
        json={
            "patient_id": other_patient["id"],
            "notes": "Not Sita's",
            "medicines": [{"name": "Loratadine", "dosage": "10mg", "form": "tablet", "qty": 1}],
        },
    )
    other_prescription = r.json()
    all_deliveries = client.get("/deliveries", headers=auth_headers(doctor_token)).json()
    other_delivery = next(d for d in all_deliveries if d["prescription_id"] == other_prescription["id"])

    r = client.get("/deliveries", headers=auth_headers(patient_token))
    assert r.status_code == 200
    mine = r.json()
    assert len(mine) == 1
    assert mine[0]["patient_name"] == "Sita Rao"
    assert all(d["prescription_id"] != other_prescription["id"] for d in mine)

    assert client.get(f"/deliveries/{mine[0]['id']}", headers=auth_headers(patient_token)).status_code == 200
    assert client.get(f"/deliveries/{other_delivery['id']}", headers=auth_headers(patient_token)).status_code == 404

    # --- staff (doctor) can still list/see patients as before, including this one ---
    r = client.get("/patients", headers=auth_headers(doctor_token))
    assert r.status_code == 200
    assert any(p["id"] == me["id"] for p in r.json())

    # --- doctor can still create a prescription against the self-signed-up patient ---
    r = client.post(
        "/prescriptions",
        headers=auth_headers(doctor_token),
        json={
            "patient_id": me["id"],
            "notes": "Check-up",
            "medicines": [{"name": "ORS", "dosage": "1 sachet", "form": "sachet", "qty": 3}],
        },
    )
    assert r.status_code == 201, r.text


def test_consultation_flow(client):
    admin_token = login(client, "admin@medidispense.com", "admin123")
    create_staff(client, admin_token, "doctor")

    # Set the doctor's speciality (mirrors what the admin website would do).
    r = client.post(
        "/users",
        headers=auth_headers(admin_token),
        json={
            "name": "Dr. Menon",
            "email": "menon@medidispense.com",
            "password": "pass123",
            "role": "doctor",
            "department": "Gastroenterology",
        },
    )
    assert r.status_code == 201, r.text
    doctor_id = r.json()["id"]
    doctor_token = login(client, "menon@medidispense.com")

    # --- patient self-signup ---
    r = client.post(
        "/auth/signup/patient",
        json={
            "name": "Asha Nair",
            "age": 33,
            "gender": "Female",
            "bed_no": "102",
            "email": "asha@medidispense.com",
            "password": "patientpass",
        },
    )
    assert r.status_code == 201, r.text
    patient_token = r.json()["access_token"]

    # --- doctor starts Available by default ---
    r = client.get("/users/me", headers=auth_headers(doctor_token))
    assert r.status_code == 200
    assert r.json()["is_available"] is True

    # --- patient finds the doctor by speciality ---
    r = client.get("/doctors?speciality=Gastroenterology", headers=auth_headers(patient_token))
    assert r.status_code == 200, r.text
    doctors = r.json()
    assert any(d["id"] == doctor_id and d["is_available"] for d in doctors)

    # --- patient requests a consultation ---
    r = client.post(
        "/consultations",
        headers=auth_headers(patient_token),
        json={"doctor_id": doctor_id, "complaint": "stomach pain since 2 days"},
    )
    assert r.status_code == 201, r.text
    consultation = r.json()
    assert consultation["status"] == "requested"
    assert consultation["patient_name"] == "Asha Nair"

    # --- patient sees their own request; doctor sees the incoming one ---
    r = client.get("/consultations", headers=auth_headers(patient_token))
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.get("/consultations", headers=auth_headers(doctor_token))
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["id"] == consultation["id"]

    # --- doctor goes Busy, then accepts the request anyway (already queued) ---
    r = client.post("/users/me/availability", headers=auth_headers(doctor_token), json={"is_available": False})
    assert r.status_code == 200
    assert r.json()["is_available"] is False

    r = client.post(f"/consultations/{consultation['id']}/accept", headers=auth_headers(doctor_token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"

    # Accepting twice is rejected.
    r = client.post(f"/consultations/{consultation['id']}/accept", headers=auth_headers(doctor_token))
    assert r.status_code == 409

    # --- doctor writes a prescription against the accepted consultation ---
    r = client.get("/patients", headers=auth_headers(doctor_token))
    patient_id = next(p["id"] for p in r.json() if p["name"] == "Asha Nair")

    r = client.post(
        "/prescriptions",
        headers=auth_headers(doctor_token),
        json={
            "patient_id": patient_id,
            "consultation_id": consultation["id"],
            "notes": "Post-consult",
            "medicines": [{"name": "Omeprazole", "dosage": "20mg", "form": "capsule", "qty": 5}],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["consultation_id"] == consultation["id"]

    # --- consultation is now completed ---
    r = client.get("/consultations", headers=auth_headers(patient_token))
    assert r.json()[0]["status"] == "completed"


def test_minimal_conveyor_flow(client):
    """The Phase-3 minimal build: doctor prescribes, the conveyor station
    pulls the job itself, the button dispatches it with no scan, and the
    station reports arrival. No pharmacist, no nurse, no QR anywhere."""
    admin_token = login(client, "admin@medidispense.com", "admin123")
    create_staff(client, admin_token, "doctor")
    create_staff(client, admin_token, "technician")
    doctor = login(client, "doctor@medidispense.com")
    station = login(client, "technician@medidispense.com")  # the ESP32's account

    # Nothing prescribed yet -> station stays idle.
    r = client.get("/conveyor/next-job", headers=auth_headers(station))
    assert r.status_code == 204

    # --- Doctor registers a patient in Bed 1 and prescribes ---
    r = client.post(
        "/patients",
        headers=auth_headers(doctor),
        json={"name": "Bed One Patient", "age": 44, "gender": "Male", "bed_no": "1"},
    )
    assert r.status_code == 201, r.text
    patient = r.json()

    r = client.post(
        "/prescriptions",
        headers=auth_headers(doctor),
        json={
            "patient_id": patient["id"],
            "medicines": [{"name": "Paracetamol", "dosage": "500mg", "form": "tablet", "qty": 2}],
        },
    )
    assert r.status_code == 201, r.text

    # --- The station polls and picks the job up by itself ---
    r = client.get("/conveyor/next-job", headers=auth_headers(station))
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["bed_no"] == "1"
    assert job["patient_name"] == "Bed One Patient"
    delivery_id = job["delivery_id"]

    # A doctor is not the conveyor and cannot dispatch.
    assert client.post(f"/deliveries/{delivery_id}/dispatch", headers=auth_headers(doctor)).status_code == 403

    # --- Button pressed: dispatch with no payload and no scan ---
    r = client.post(f"/deliveries/{delivery_id}/dispatch", headers=auth_headers(station))
    assert r.status_code == 200, r.text
    dispatched = r.json()
    assert dispatched["status"] == "in_transit"
    assert dispatched["bed_no"] == "1"  # snapshotted from the patient record

    # Pressing again is rejected - guards against a double button press
    # dispatching the same box twice.
    assert client.post(f"/deliveries/{delivery_id}/dispatch", headers=auth_headers(station)).status_code == 409

    # That job is no longer 'preparing', so the queue is empty again.
    assert client.get("/conveyor/next-job", headers=auth_headers(station)).status_code == 204

    # --- Servo has pushed the box into the bed chute ---
    r = client.post(f"/deliveries/{delivery_id}/mark-arrived", headers=auth_headers(station))
    assert r.status_code == 200
    assert r.json()["status"] == "arrived"


def test_conveyor_next_job_is_fifo(client):
    """Two beds prescribed at once: the station must be handed the older job
    first, so the operator is never guessing which box to load."""
    admin_token = login(client, "admin@medidispense.com", "admin123")
    create_staff(client, admin_token, "doctor")
    create_staff(client, admin_token, "technician")
    doctor = login(client, "doctor@medidispense.com")
    station = login(client, "technician@medidispense.com")

    ids = []
    for name, bed in [("First Patient", "1"), ("Second Patient", "2")]:
        p = client.post(
            "/patients",
            headers=auth_headers(doctor),
            json={"name": name, "age": 30, "gender": "Male", "bed_no": bed},
        ).json()
        client.post(
            "/prescriptions",
            headers=auth_headers(doctor),
            json={
                "patient_id": p["id"],
                "medicines": [{"name": "Vitamin C", "dosage": "500mg", "form": "tablet", "qty": 1}],
            },
        )
        ids.append(p["id"])

    # Oldest first.
    job = client.get("/conveyor/next-job", headers=auth_headers(station)).json()
    assert job["bed_no"] == "1"
    client.post(f"/deliveries/{job['delivery_id']}/dispatch", headers=auth_headers(station))

    # Then the second one.
    job2 = client.get("/conveyor/next-job", headers=auth_headers(station)).json()
    assert job2["bed_no"] == "2"
    assert job2["patient_name"] == "Second Patient"
