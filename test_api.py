import json
import urllib.request

# 1. Read the public sample cases file
with open('BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 2. Extract the first case's input
first_case = data['cases'][0]
payload = first_case['input']

print(f"Testing Scenario: {payload['scenario_id']}")
print(f"Operator Notes: {payload['operator_notes']}")
print("-" * 50)

# 3. Send a POST request to our local FastAPI server
url = 'http://localhost:8000/optimize-energy'
req = urllib.request.Request(url, method='POST')
req.add_header('Content-Type', 'application/json')
json_data = json.dumps(payload).encode('utf-8')

try:
    with urllib.request.urlopen(req, data=json_data) as response:
        result = json.loads(response.read().decode('utf-8'))
        
        print("✅ SUCCESS! Server responded with:")
        print(f"Total Cost (BDT): {result['total_cost_bdt']}")
        print(f"Peak Grid (kWh): {result['peak_grid_kwh']}")
        print(f"Plan Summary: {result['plan_summary']}")
        
        print("\n--- LLM Directives Extracted ---")
        for directive in result['directive_interpretation']:
            print(f"- Type: {directive['directive_type']} | Applies: {directive['applies']}")
            if directive['structured_adjustment']:
                print(f"  Adjustment: {directive['structured_adjustment']}")
                
except Exception as e:
    print(f"❌ ERROR: Failed to connect or received error from server. Details:\n{e}")
    print("Make sure your server is running (uvicorn main:app --port 8000)")
