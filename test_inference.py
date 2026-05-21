import os
import sys
# add parent dir so we can import api
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from api.models.request_models import ClaimRequest
from api.services import ml_service
ml_service.cfg.model_xgb_path = 'models/model.xgb'
ml_service.cfg.model_lr_path = 'models/model.pkl'

ml_service.load_models()

req1 = ClaimRequest(claim_id="T1", billed_amount=15000.0, provider_id="PRV", diagnosis_code="I21.0", procedure_code="93010", service_date="2026-05-16")
res1 = ml_service.predict(req1)
print("T1 (Good):", res1["predicted_status"], res1["denial_prob"], res1["feature_vector"])

req2 = ClaimRequest(claim_id="T2", billed_amount=None, provider_id="PRV", diagnosis_code=None, procedure_code=None, service_date="2026-05-16")
res2 = ml_service.predict(req2)
print("T2 (Bad):", res2["predicted_status"], res2["denial_prob"], res2["feature_vector"])

req3 = ClaimRequest(claim_id="T3", billed_amount=100000.0, provider_id="PRV", diagnosis_code="A00", procedure_code="10000", service_date="2026-05-16")
res3 = ml_service.predict(req3)
print("T3 (Outlier):", res3["predicted_status"], res3["denial_prob"], res3["feature_vector"])
