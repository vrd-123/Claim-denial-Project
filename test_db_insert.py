import sqlite3
import datetime
import json

conn = sqlite3.connect("data/claim_history.db")
cur = conn.cursor()
cur.execute("""
    INSERT INTO claim_history 
    (claim_id, submitted_by, submitted_at, predicted_status, risk_level, denial_prob, 
     error_codes, primary_reason, recommendation, ml_called, full_response,
     billing_ratio, billed_amount, procedure_code, diagnosis_code, provider_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", ("TEST-DB", "test@test.com", datetime.datetime.utcnow().isoformat(), "APPROVED", "LOW", 0.15,
      None, "reason", "rec", 1, "{}", 1.0, 500.0, "PROC", "DIAG", "PROV"))
conn.commit()
conn.close()
print("Insert OK")
