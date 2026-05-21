import os

docs_dir = "/Users/varad.naik/Desktop/Claim-denial-Project/data/policy_docs"

doc1 = """INSURANCE CLAIM ADJUDICATION POLICY MANUAL
==========================================
Document: ICAP-001 | Version: 3.2 | Effective: 2024-01-01
Issuing Authority: Claims Adjudication & Compliance Division
==========================================

SECTION 1: BILLING AMOUNT THRESHOLDS & OVERBILLING RULES
---------------------------------------------------------
POLICY 1.1 — MAXIMUM BILLABLE AMOUNT PER PROCEDURE
Any claim where the Claim billed amount is significantly higher than the benchmark expected cost. shall be flagged for mandatory secondary review. Claims exceeding 2.0 times (200%) the benchmark are automatically denied. 
Conversely, if the Claim billed amount is within the accepted benchmark cost range., the claim can be processed without automated denial on this criterion.

POLICY 1.2 — HIGH-COST OUTLIER PROTOCOL
A Claim has been flagged as an extreme high-cost outlier by the cost model. when billing_ratio > 1.5 or high_cost_flag = 1. Such claims must be accompanied by a signed letter of medical necessity. 
If No high-cost outlier flag detected; billing appears standard., the claim bypasses the outlier review queue.

POLICY 1.3 — COST DIFFERENCE TOLERANCE
When The absolute cost gap between billed and expected amounts is excessively large., it requires prior authorization before the claim is processed. 
If The cost gap between billed and expected amounts is within acceptable limits., it satisfies the cost difference tolerance rule.

SECTION 5: CLAIM SUBMISSION TIMELINESS
---------------------------------------
POLICY 5.1 — TIMELY FILING REQUIREMENT
If The claim was submitted significantly late relative to the service date. (e.g., beyond 90 days), it will be denied for late filing unless a documented exception applies.
If The claim was submitted promptly relative to the service date., it satisfies the timely filing requirements.
"""

doc2 = """MEDICAL NECESSITY & CLINICAL CODING GUIDELINES
===============================================
Document: MCG-002 | Version: 2.1 | Effective: 2024-01-01
Reference: CMS ICD-10-CM, AMA CPT Guidelines 2024
Issuing Authority: Clinical Quality & Utilization Management
===============================================

SECTION 1: ICD-10-CM DIAGNOSIS CODE REQUIREMENTS
-------------------------------------------------
GUIDELINE 1.1 — MANDATORY DIAGNOSIS CODE
If The medical diagnosis code is missing or invalid in the claim submission., the claim is administratively incomplete.
If The medical diagnosis code is present and valid., it satisfies the basic coding requirements for the diagnosis field.

GUIDELINE 1.5 — SEVERITY CLASSIFICATION
When The clinical severity level is inconsistent with the standard billing profile for this claim., it triggers a Medical Necessity Review.
When The clinical severity level aligns with the expected billing profile., it proceeds without severity-based flagging.

GUIDELINE 1.6 — DIAGNOSIS FREQUENCY
If This diagnosis code has an unusually low historical claim frequency, indicating potential miscoding., the claim is subject to enhanced review.
If This diagnosis code has a strong historical claim frequency, indicating a reliable submission., it reduces the likelihood of manual audit.

GUIDELINE 1.7 — DIAGNOSIS CATEGORY ALIGNMENT
If The diagnosis category is inconsistent with the procedure and billing pattern submitted., it implies a potential upcoding or miscoding error.
If The diagnosis category is consistent with the procedure and billing pattern., it fulfills clinical alignment checks.

SECTION 2: CPT PROCEDURE CODE GUIDELINES
-----------------------------------------
GUIDELINE 2.1 — MANDATORY CPT CODE SUBMISSION
If The medical procedure code is missing or invalid in the claim submission., it is returned for correction.
If The medical procedure code is present and valid., the claim line satisfies the procedural coding requirements.
"""

doc3 = """PROVIDER PARTICIPATION AGREEMENT & BILLING COMPLIANCE STANDARDS
================================================================
Document: PPA-003 | Version: 1.8 | Effective: 2024-01-01
Issuing Authority: Provider Relations & Network Management Division
================================================================

SECTION 1: PROVIDER ELIGIBILITY & CREDENTIALING
------------------------------------------------
STANDARD 1.2 — SPECIALTY SCOPE OF PRACTICE
If The billing pattern is inconsistent with the provider's recorded medical specialty., the claim will be flagged for specialty mismatch review.
If The billing pattern is consistent with the provider's medical specialty., the claim proceeds through standard credentialing checks.

STANDARD 1.3 — MINIMUM CLAIM VOLUME STANDARDS
When The provider's low historical claim volume indicates a higher operational risk profile., claims are subject to enhanced pre-payment review.
When The provider has a high historical claim volume, suggesting a reliable submission pattern., they are placed in the standard processing tier.

SECTION 6: BILLING AMOUNT INTEGRITY
--------------------------------------
POLICY 6.1 — MISSING BILLED AMOUNT
If The claim billed amount was missing from the original source submission., it is considered administratively incomplete.
If The claim billed amount is present and valid in the original submission., the billing integrity validation is successful.
"""

with open(os.path.join(docs_dir, "policy_claim_adjudication.txt"), "w") as f:
    f.write(doc1)
with open(os.path.join(docs_dir, "policy_medical_necessity_coding.txt"), "w") as f:
    f.write(doc2)
with open(os.path.join(docs_dir, "policy_provider_compliance.txt"), "w") as f:
    f.write(doc3)

print("Policy docs rewritten successfully.")
