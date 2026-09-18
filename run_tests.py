import json
import sys
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def run_all_tests():
    print("=" * 60)
    print("RUNNING GRIDWISE SYSTEM VERIFICATION SUITE")
    print("=" * 60)
    
    # 1. Health Check
    health_resp = client.get("/health")
    assert health_resp.status_code == 200, f"Health check failed: {health_resp.status_code}"
    health_json = health_resp.json()
    assert health_json.get("status") == "ok", f"Health status mismatch: {health_json}"
    print("[PASS] GET /health returns 200 OK with status: 'ok'")
    
    # 2. Public Sample Cases
    with open("BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json", "r", encoding="utf-8") as f:
        pack = json.load(f)
        
    cases = pack["cases"]
    all_passed = True
    
    for case in cases:
        cid = case["id"]
        label = case["label"]
        inp = case["input"]
        exp = case["expected_output"]
        
        resp = client.post("/optimize-energy", json=inp)
        if resp.status_code != 200:
            print(f"[FAIL] {cid} ({label}) - HTTP {resp.status_code}: {resp.text}")
            all_passed = False
            continue
            
        out = resp.json()
        
        # Verify top-level fields
        for field in ["scenario_id", "directive_interpretation", "hourly_plan", "total_grid_kwh", "total_cost_bdt", "peak_grid_kwh", "plan_summary"]:
            assert field in out, f"Missing top-level field {field} in response for {cid}"
            
        assert out["scenario_id"] == inp["scenario_id"], f"scenario_id mismatch in {cid}"
        
        # Check Directives
        out_dirs = out["directive_interpretation"]
        exp_dirs = exp["directive_interpretation"]
        assert len(out_dirs) == len(exp_dirs), f"Directive count mismatch in {cid}"
        
        for i, (od, ed) in enumerate(zip(out_dirs, exp_dirs)):
            assert od["note_index"] == ed["note_index"], f"note_index mismatch in {cid} note {i}"
            assert od["applies"] == ed["applies"], f"applies mismatch in {cid} note {i}: got {od['applies']}, expected {ed['applies']}"
            assert od["directive_type"] == ed["directive_type"], f"directive_type mismatch in {cid} note {i}: got {od['directive_type']}, expected {ed['directive_type']}"
            if ed["structured_adjustment"] is None:
                assert od["structured_adjustment"] is None, f"adjustment should be None for no_op in {cid}"
            else:
                for k, v in ed["structured_adjustment"].items():
                    assert k in od["structured_adjustment"], f"Missing key {k} in adjustment for {cid}"
                    od_val = od["structured_adjustment"][k]
                    if isinstance(v, list):
                        assert od_val == v, f"Adjustment list {k} mismatch in {cid}: {od_val} vs {v}"
                    else:
                        assert abs(od_val - v) < 1e-4, f"Adjustment val {k} mismatch in {cid}: {od_val} vs {v}"

        # Check Hourly Plan Constraints
        plan = out["hourly_plan"]
        assert len(plan) == 24, f"hourly_plan length is {len(plan)} (expected 24) in {cid}"
        
        bat = inp["battery"]
        prev_E = bat["initial_energy_kwh"]
        
        for h_idx, hp in enumerate(plan):
            h_req = inp["hours"][h_idx]
            assert hp["hour"] == h_idx, f"Hour index mismatch at {h_idx} in {cid}"
            assert hp["grid_kwh"] >= 0, f"Negative grid at hour {h_idx} in {cid}"
            assert hp["solar_used_kwh"] >= 0, f"Negative solar at hour {h_idx} in {cid}"
            assert hp["battery_action"] in ["charge", "discharge", "idle"], f"Invalid action {hp['battery_action']} in {cid}"
            
            # Energy balance
            g_k = hp["grid_kwh"]
            s_k = hp["solar_used_kwh"]
            b_act = hp["battery_action"]
            b_k = hp["battery_kwh"]
            e_after = hp["battery_energy_after_kwh"]
            
            c_k = b_k if b_act == "charge" else 0.0
            d_k = b_k if b_act == "discharge" else 0.0
            
            balance_diff = abs((g_k + s_k + d_k) - (h_req["demand_kwh"] + c_k))
            assert balance_diff < 0.05, f"Energy balance violated at hour {h_idx} in {cid}: diff={balance_diff}"
            
            # State evolution
            calc_E = prev_E + c_k - d_k
            assert abs(e_after - calc_E) < 0.05, f"Battery state evolution violated at hour {h_idx} in {cid}"
            prev_E = e_after

        # End of day neutrality
        assert abs(prev_E - bat["initial_energy_kwh"]) < 0.05, f"End-of-day battery neutrality violated in {cid}: final={prev_E}, initial={bat['initial_energy_kwh']}"

        # Cost quality check
        comp_cost = out["total_cost_bdt"]
        exp_cost = exp["total_cost_bdt"]
        cost_diff = abs(comp_cost - exp_cost)
        assert cost_diff < 0.05, f"Cost mismatch in {cid}: got {comp_cost}, expected {exp_cost}"
        
        print(f"[PASS] {cid}: {label} | Cost: {comp_cost:.2f} BDT (Expected: {exp_cost:.2f} BDT)")

    print("=" * 60)
    if all_passed:
        print("ALL TESTS PASSED WITH 100% ACCURACY & FULL COMPLIANCE!")
    print("=" * 60)

if __name__ == "__main__":
    run_all_tests()
