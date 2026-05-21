from api.models.request_models import ClaimRequest
from api.services import ml_service
ml_service.load_models()
req = ClaimRequest(claim_id="1", provider_id="PR100", diagnosis_code="D10", procedure_code="PROC1", billed_amount=5000.0, service_date="2026-05-17")
res = ml_service.predict(req)
print(f"Good claim: {res['denial_prob']} ({res['predicted_status']})")

req2 = ClaimRequest(claim_id="2", provider_id="PR100", diagnosis_code="D10", procedure_code="PROC1", billed_amount=20000.0, service_date="2026-05-17")
res2 = ml_service.predict(req2)
print(f"Bad claim: {res2['denial_prob']} ({res2['predicted_status']})")
