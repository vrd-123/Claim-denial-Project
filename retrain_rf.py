"""
retrain_rf.py — Retrain RandomForest on current sklearn using exact Gold feature schema.

Severity in raw data: High / Low  (maps to 3 / 1; unknown → 2)
Categories in raw data: Bone, Cold, Diabetes, Fever, Heart, Skin
  → sorted alpha → {Bone:0, Cold:1, Diabetes:2, Fever:3, Heart:4, Skin:5}
Specialties: Cardiology, General, Neurology, Orthopedic
  → sorted alpha → {Cardiology:0, General:1, Neurology:2, Orthopedic:3}
denial_flag: 0=DENIED, 1=APPROVED  (same as training notebook)
"""
import warnings; warnings.filterwarnings('ignore')
import pickle, numpy as np, pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, RandomizedSearchCV, StratifiedKFold
from sklearn.metrics import roc_auc_score, f1_score, classification_report, make_scorer
from datetime import date as dt_date

RANDOM_SEED = 42
np.random.seed(RANDOM_SEED)

FEATURE_COLS = [
    "billing_ratio", "cost_diff", "high_cost_flag",
    "provider_claim_count", "provider_specialty_enc",
    "severity_score", "diag_claim_count", "diag_category_enc",
    "is_billed_missing", "is_proc_missing", "is_diag_missing", "claim_age_days",
]

# ── Sorted-alpha encoders (matches Databricks label-encoder output) ────────────
SEVERITY_MAP  = {"HIGH": 3, "LOW": 1}   # unknown → 2
CATEGORY_MAP  = {c: i for i, c in enumerate(sorted(["Bone","Cold","Diabetes","Fever","Heart","Skin"]))}
SPECIALTY_MAP = {s: i for i, s in enumerate(sorted(["Cardiology","General","Neurology","Orthopedic"]))}
print("Category map:  ", CATEGORY_MAP)
print("Specialty map: ", SPECIALTY_MAP)

# ── Load raw data ─────────────────────────────────────────────────────────────
claims    = pd.read_csv('data/raw/claims_1000.csv')
providers = pd.read_csv('data/raw/providers_1000.csv')
cost_df   = pd.read_csv('data/raw/cost.csv')
diag_df   = pd.read_csv('data/raw/diagnosis.csv')

# ── Merge reference tables ────────────────────────────────────────────────────
df = claims.copy()
df = df.merge(providers[['provider_id','specialty']],         on='provider_id',    how='left')
df = df.merge(cost_df[['procedure_code','expected_cost']],    on='procedure_code', how='left')
df = df.merge(diag_df[['diagnosis_code','category','severity']], on='diagnosis_code', how='left')

print(f"\nMerged shape: {df.shape}")

# ── Missing flags (before filling) ───────────────────────────────────────────
df['is_billed_missing'] = df['billed_amount'].isna().astype(int)
df['is_proc_missing']   = df['procedure_code'].isna().astype(int)
df['is_diag_missing']   = df['diagnosis_code'].isna().astype(int)

# ── Cost features ─────────────────────────────────────────────────────────────
df['billed_safe']    = df['billed_amount'].fillna(0.0)
df['expected_safe']  = df['expected_cost'].fillna(df['billed_safe'].mean())  # neutral fill
df['billing_ratio']  = (df['billed_safe'] / df['expected_safe'].clip(lower=1)).round(4)
df['cost_diff']      = (df['billed_safe'] - df['expected_safe']).round(4)
df['high_cost_flag'] = (df['billing_ratio'] > 1.5).astype(int)             # threshold from notebook

# ── Provider features ─────────────────────────────────────────────────────────
prov_counts = df.groupby('provider_id')['claim_id'].transform('count')
df['provider_claim_count']   = prov_counts.astype(float)
df['provider_specialty_enc'] = df['specialty'].map(SPECIALTY_MAP).fillna(1).astype(float)

# ── Diagnosis features ────────────────────────────────────────────────────────
df['severity_score']   = df['severity'].str.upper().map(SEVERITY_MAP).fillna(2).astype(float)
df['diag_category_enc'] = df['category'].map(CATEGORY_MAP).fillna(0).astype(float)

diag_counts = df.groupby('diagnosis_code')['claim_id'].transform('count')
df['diag_claim_count'] = diag_counts.fillna(1).astype(float)

# ── Claim age ─────────────────────────────────────────────────────────────────
df['claim_date'] = pd.to_datetime(df['date'], errors='coerce')
max_date = df['claim_date'].max()
df['claim_age_days'] = (max_date - df['claim_date']).dt.days.fillna(0).clip(lower=0).astype(float)

# ── Denial labels (rule-based, same logic as Silver layer generate_labels) ─────
# denial_flag: 0=DENIED, 1=APPROVED
deny_mask = (
    (df['billing_ratio'] > 2.5)          |  # severe overbilling
    (df['high_cost_flag'] == 1) & (df['severity_score'] == 1)  |  # high cost + low severity
    (df['is_billed_missing'] == 1)        |
    (df['is_diag_missing']   == 1)        |
    (df['is_proc_missing']   == 1)        |
    (df['claim_age_days']    > 180)       |
    (df['provider_claim_count'] <= 3)     # very new provider
)
df['denial_flag'] = (~deny_mask).astype(int)

denied   = (df['denial_flag'] == 0).sum()
approved = (df['denial_flag'] == 1).sum()
total    = len(df)
print(f"\nLabel dist → Denied(0): {denied} ({denied/total*100:.1f}%)  "
      f"Approved(1): {approved} ({approved/total*100:.1f}%)")

if denied == 0 or approved == 0:
    raise RuntimeError("Degenerate labels — adjust denial rule thresholds")

# ── Feature matrix ────────────────────────────────────────────────────────────
X = df[FEATURE_COLS].fillna(0).copy()
y = df['denial_flag'].copy()

print(f"\nX shape: {X.shape}")
print(X.describe().round(2))

# ── Train / test split ────────────────────────────────────────────────────────
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.20, stratify=y, random_state=RANDOM_SEED
)
print(f"\nTrain: {len(X_train)} | Test: {len(X_test)}")

# ── RandomizedSearchCV (same grid as training notebook) ───────────────────────
rf_param_grid = {
    "n_estimators"     : [200, 300, 400],
    "max_depth"        : [None, 10, 15, 20],
    "min_samples_split": [2, 5, 10],
    "min_samples_leaf" : [1, 2, 4],
    "max_features"     : ["sqrt", "log2"],
    "class_weight"     : ["balanced", "balanced_subsample"],
}

cv      = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_SEED)
scorer  = make_scorer(f1_score, zero_division=0, pos_label=0)
search  = RandomizedSearchCV(
    RandomForestClassifier(random_state=RANDOM_SEED, n_jobs=-1),
    rf_param_grid, n_iter=15, scoring=scorer, cv=cv,
    random_state=RANDOM_SEED, verbose=1, n_jobs=1,
)
print("\nRunning RandomizedSearchCV...")
search.fit(X_train, y_train)

best_rf = search.best_estimator_
print(f"Best params: {search.best_params_}")
print(f"Best CV F1:  {search.best_score_:.4f}")

# ── Evaluate ──────────────────────────────────────────────────────────────────
y_pred   = best_rf.predict(X_test)
# proba[:,1] = P(Approved) — matches training notebook line 406
y_prob   = best_rf.predict_proba(X_test)[:, 1]
deny_prob = 1 - y_prob

auc = roc_auc_score(y_test, y_prob)
print(f"\nTest ROC-AUC:  {auc:.4f}")
print(f"Denial prob range: min={deny_prob.min():.3f}  max={deny_prob.max():.3f}  mean={deny_prob.mean():.3f}")
print("\nClassification Report:")
print(classification_report(y_test, y_pred, target_names=["Denied(0)","Approved(1)"], zero_division=0))

# ── Validate on 3 sample claims from training notebook ────────────────────────
samples = pd.DataFrame([
    {"billing_ratio":1.1,"cost_diff":500,"high_cost_flag":0,"provider_claim_count":45,
     "provider_specialty_enc":2,"severity_score":2,"diag_claim_count":150,
     "diag_category_enc":4,"is_billed_missing":0,"is_proc_missing":0,"is_diag_missing":0,"claim_age_days":10},
    {"billing_ratio":3.5,"cost_diff":15000,"high_cost_flag":1,"provider_claim_count":5,
     "provider_specialty_enc":0,"severity_score":1,"diag_claim_count":20,
     "diag_category_enc":0,"is_billed_missing":1,"is_proc_missing":1,"is_diag_missing":0,"claim_age_days":45},
    {"billing_ratio":0.9,"cost_diff":-100,"high_cost_flag":0,"provider_claim_count":200,
     "provider_specialty_enc":1,"severity_score":2,"diag_claim_count":500,
     "diag_category_enc":2,"is_billed_missing":0,"is_proc_missing":0,"is_diag_missing":0,"claim_age_days":2},
])
print("\n── Sample Predictions ──")
sp = best_rf.predict_proba(samples[FEATURE_COLS])[:, 1]
for i, p_app in enumerate(sp):
    d = 1 - p_app
    lbl = ["Low-risk","High-risk","Approved"][i]
    print(f"  {lbl:<12} denial_prob={d:.3f}  → {'DENIED ❌' if d>=0.5 else 'APPROVED ✅'}")

# ── Save ──────────────────────────────────────────────────────────────────────
import sklearn
with open('models/model.pkl', 'wb') as f:
    pickle.dump(best_rf, f, protocol=4)
print(f"\n✅ Saved to models/model.pkl  (sklearn {sklearn.__version__})")
