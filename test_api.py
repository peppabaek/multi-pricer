import requests

base_url = 'http://127.0.0.1:8000'

# 1. USD SOFR Standard vs Advanced on 5Y (pillar)
req_std_5y = {'currency': 'USD', 'tenor': '5Y', 'fixed_coupon_pct': 4.0610, 'curve_type': 'Standard'}
req_adv_5y = {'currency': 'USD', 'tenor': '5Y', 'fixed_coupon_pct': 4.0610, 'curve_type': 'Advanced'}

r1 = requests.post(f'{base_url}/api/price', json=req_std_5y).json()
r2 = requests.post(f'{base_url}/api/price', json=req_adv_5y).json()

par_std_5y = r1['data']['pricing_results']['par_swap_rate_pct']
par_adv_5y = r2['data']['pricing_results']['par_swap_rate_pct']
print(f'5Y Pillar: Std Par={par_std_5y:.4f}%, Adv Par={par_adv_5y:.4f}%, Diff={(par_adv_5y - par_std_5y)*100:.4f}bp')

# 2. USD SOFR Standard vs Advanced on Odd Tenor (15M)
req_std_odd = {'currency': 'USD', 'tenor': '15M', 'fixed_coupon_pct': 4.0, 'curve_type': 'Standard'}
req_adv_odd = {'currency': 'USD', 'tenor': '15M', 'fixed_coupon_pct': 4.0, 'curve_type': 'Advanced'}

r3 = requests.post(f'{base_url}/api/price', json=req_std_odd).json()
r4 = requests.post(f'{base_url}/api/price', json=req_adv_odd).json()

par_std_odd = r3['data']['pricing_results']['par_swap_rate_pct']
par_adv_odd = r4['data']['pricing_results']['par_swap_rate_pct']
print(f'15M Odd: Std Par={par_std_odd:.4f}%, Adv Par={par_adv_odd:.4f}%, Diff={(par_adv_odd - par_std_odd)*100:.4f}bp')

# 3. CRS Vanilla vs Fixed-Fixed
req_crs_vanilla = {
    'currency': 'KRW_CRS',
    'tenor': '5Y',
    'fixed_coupon_pct': 3.55,
    'crs_swap_type': 'Vanilla',
    'curve_type': 'Standard'
}
req_crs_ff = {
    'currency': 'KRW_CRS',
    'tenor': '5Y',
    'fixed_coupon_pct': 3.55,
    'crs_swap_type': 'Fixed-Fixed',
    'usd_fixed_coupon_pct': 3.50,
    'curve_type': 'Standard'
}
req_crs_ff_adv = {
    'currency': 'KRW_CRS',
    'tenor': '5Y',
    'fixed_coupon_pct': 3.55,
    'crs_swap_type': 'Fixed-Fixed',
    'usd_fixed_coupon_pct': 3.50,
    'curve_type': 'Advanced'
}

r_crs1 = requests.post(f'{base_url}/api/crs/price', json=req_crs_vanilla).json()
r_crs2 = requests.post(f'{base_url}/api/crs/price', json=req_crs_ff).json()
r_crs3 = requests.post(f'{base_url}/api/crs/price', json=req_crs_ff_adv).json()

print('CRS Vanilla Par:', r_crs1['data']['pricing_results']['par_crs_rate_pct'])
print('CRS FF Std -> KRW Par:', r_crs2['data']['pricing_results']['par_krw_rate_pct'], 'USD Par:', r_crs2['data']['pricing_results']['par_usd_rate_pct'])
print('CRS FF Adv -> KRW Par:', r_crs3['data']['pricing_results']['par_krw_rate_pct'], 'USD Par:', r_crs3['data']['pricing_results']['par_usd_rate_pct'])

# 4. Test all 4 Stub Rules on Leg 1 and Leg 2
stubs = ['Short upfront', 'Long upfront', 'Short in arrears', 'Long in arrears']
for stub in stubs:
    req_stub = {
        'currency': 'USD',
        'tenor': '15M',
        'fixed_coupon_pct': 4.0,
        'leg1_stub_rule': stub,
        'leg2_stub_rule': stub
    }
    res = requests.post(f'{base_url}/api/price', json=req_stub).json()
    assert res['status'] == 'success', f'Failed for stub {stub}'
    par = res['data']['pricing_results']['par_swap_rate_pct']
    print(f'Stub {stub}: Par={par:.4f}%')

print('ALL API TESTS PASSED!')
