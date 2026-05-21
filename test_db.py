from auth import get_supabase_client
sb = get_supabase_client()
try:
    res = sb.table('claim_history').select('*').limit(1).execute()
    print("Table claim_history exists:", res)
except Exception as e:
    print("Error querying claim_history:", e)
