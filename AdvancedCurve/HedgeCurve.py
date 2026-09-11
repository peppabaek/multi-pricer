import QuantLib as ql
import numpy as np
import pandas as pd

# 1. Configuration & Initial Data
np.random.seed(42)  

initial_rates = np.array([0.027, 0.0286, 0.0298, 0.0315, 0.035, 0.038, 0.040, 0.042, 0.045])
pca_loadings = np.array([
    [ 0.0000,  0.0000,  0.0000],  
    [ 0.0026, -0.0016,  0.0007],  
    [ 0.0055, -0.0031,  0.0010],  
    [ 0.0122, -0.0058,  0.0008],  
    [ 0.0360, -0.0125, -0.0035],  
    [ 0.0321, -0.0006, -0.0016],  
    [ 0.0308,  0.0105,  0.0011],  
    [ 0.0248,  0.0177, -0.0053],  
    [ 0.0195,  0.0142, -0.0028]   
])
norms = np.linalg.norm(pca_loadings, axis=1, keepdims=True)
loadings = np.divide(pca_loadings, norms, out=np.zeros_like(pca_loadings), where=norms!=0)
vols = np.array([0.005, 0.003, 0.002]) / np.sqrt(252)
mr_speed = 0.05
days_sim = 126
num_paths = 100

today = ql.Date(20, 4, 2026)
ql.Settings.instance().evaluationDate = today
calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
day_count = ql.Actual360()

# Quotes (Market Quotes)
quotes = [ql.SimpleQuote(rate) for rate in initial_rates]
quote_handles = [ql.QuoteHandle(q) for q in quotes]

curve_handle_cubic = ql.RelinkableYieldTermStructureHandle()
sofr_index_cubic = ql.Sofr(curve_handle_cubic)
curve_handle_linear = ql.RelinkableYieldTermStructureHandle()
sofr_index_linear = ql.Sofr(curve_handle_linear)

curve_handle_zero = ql.RelinkableYieldTermStructureHandle()
sofr_index_zero = ql.Sofr(curve_handle_zero)
engine_zero = ql.DiscountingSwapEngine(curve_handle_zero)

pillar_tenors = ["1D", "1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y"]
helpers_cubic = []
helpers_linear = []
for i, tenor_str in enumerate(pillar_tenors):
    period = ql.Period(tenor_str)
    if tenor_str == "1D":
        helpers_cubic.append(ql.DepositRateHelper(quote_handles[i], period, 0, calendar, ql.Following, False, day_count))
        helpers_linear.append(ql.DepositRateHelper(quote_handles[i], period, 0, calendar, ql.Following, False, day_count))
    else:
        helpers_cubic.append(ql.OISRateHelper(2, period, quote_handles[i], sofr_index_cubic))
        helpers_linear.append(ql.OISRateHelper(2, period, quote_handles[i], sofr_index_linear))

curve_cubic = ql.PiecewiseLogCubicDiscount(0, calendar, helpers_cubic, day_count)
curve_linear = ql.PiecewiseLinearZero(0, calendar, helpers_linear, day_count)
curve_cubic.enableExtrapolation()
curve_linear.enableExtrapolation()

curve_handle_cubic.linkTo(curve_cubic)
curve_handle_linear.linkTo(curve_linear)

engine_cubic = ql.DiscountingSwapEngine(curve_handle_cubic)
engine_linear = ql.DiscountingSwapEngine(curve_handle_linear)

# Dynamic Zero Curve Preparation
nodes_init = curve_cubic.nodes()
pillar_dates = [node[0] for node in nodes_init]

sys_dates = [today]
for d in range(1, days_sim + 1):
    sys_dates.append(calendar.advance(sys_dates[-1], 1, ql.Days))

# 2. Portfolio Setup
base_nominal = 100_000_000
cp_dates = [calendar.advance(today, ql.Period(18, ql.Months)), calendar.advance(today, ql.Period(30, ql.Months))]
base_schedule = ql.Schedule([today] + cp_dates, calendar, ql.ModifiedFollowing)

temp_base = ql.OvernightIndexedSwap(ql.Swap.Receiver, base_nominal, base_schedule, 0.0, day_count, sofr_index_cubic)
temp_base.setPricingEngine(engine_cubic)
market_base_par_rate = temp_base.fairRate()

base_swap_cubic = ql.OvernightIndexedSwap(ql.Swap.Receiver, base_nominal, base_schedule, market_base_par_rate, day_count, sofr_index_cubic)
base_swap_linear = ql.OvernightIndexedSwap(ql.Swap.Receiver, base_nominal, base_schedule, market_base_par_rate, day_count, sofr_index_linear)
# Zero Curve Evaluator Swap (Uses dedicated sofr_index_zero to track dynamic bumps)
base_swap_zero = ql.OvernightIndexedSwap(ql.Swap.Receiver, base_nominal, base_schedule, market_base_par_rate, day_count, sofr_index_zero)

base_swap_cubic.setPricingEngine(engine_cubic)
base_swap_linear.setPricingEngine(engine_linear)
base_swap_zero.setPricingEngine(engine_zero)


def create_hedge_swap(tenor_period, float_index, fixed_rate, nominal, start_date):
    maturity = calendar.advance(start_date, tenor_period)
    schedule = ql.Schedule(start_date, maturity, ql.Period("1Y"), calendar, ql.ModifiedFollowing, ql.ModifiedFollowing, ql.DateGeneration.Backward, False)
    return ql.OvernightIndexedSwap(ql.Swap.Payer, nominal, schedule, fixed_rate, day_count, float_index)

temp_2y = create_hedge_swap(ql.Period("2Y"), sofr_index_cubic, 0.0, 1.0, today)
temp_2y.setPricingEngine(engine_cubic)
h2_par = temp_2y.fairRate()

temp_3y = create_hedge_swap(ql.Period("3Y"), sofr_index_cubic, 0.0, 1.0, today)
temp_3y.setPricingEngine(engine_cubic)
h3_par = temp_3y.fairRate()

unit_h2_cubic = create_hedge_swap(ql.Period("2Y"), sofr_index_cubic, h2_par, 1.0, today)
unit_h3_cubic = create_hedge_swap(ql.Period("3Y"), sofr_index_cubic, h3_par, 1.0, today)
unit_h2_cubic.setPricingEngine(engine_cubic)
unit_h3_cubic.setPricingEngine(engine_cubic)

unit_h2_linear = create_hedge_swap(ql.Period("2Y"), sofr_index_linear, h2_par, 1.0, today)
unit_h3_linear = create_hedge_swap(ql.Period("3Y"), sofr_index_linear, h3_par, 1.0, today)
unit_h2_linear.setPricingEngine(engine_linear)
unit_h3_linear.setPricingEngine(engine_linear)

unit_h2_zero = create_hedge_swap(ql.Period("2Y"), sofr_index_zero, h2_par, 1.0, today)
unit_h3_zero = create_hedge_swap(ql.Period("3Y"), sofr_index_zero, h3_par, 1.0, today)
unit_h2_zero.setPricingEngine(engine_zero)
unit_h3_zero.setPricingEngine(engine_zero)

# 3. Hedge Calculation Strategies
def calc_dv01(obj, node_idx, quote_list):
    origin = quote_list[node_idx].value()
    base_npv = obj.NPV()
    quote_list[node_idx].setValue(origin + 0.0001)
    up_npv = obj.NPV()
    quote_list[node_idx].setValue(origin)
    return up_npv - base_npv

def calc_hedge_strA_linear():
    dv01_b_2, dv01_b_3 = calc_dv01(base_swap_linear, 5, quotes), calc_dv01(base_swap_linear, 6, quotes)
    dv01_h2_2, dv01_h2_3 = calc_dv01(unit_h2_linear, 5, quotes), calc_dv01(unit_h2_linear, 6, quotes)
    dv01_h3_2, dv01_h3_3 = calc_dv01(unit_h3_linear, 5, quotes), calc_dv01(unit_h3_linear, 6, quotes)
    
    A = np.array([[dv01_h2_2, dv01_h3_2], [dv01_h2_3, dv01_h3_3]])
    b = np.array([-dv01_b_2, -dv01_b_3])
    w = np.linalg.solve(A, b)
    return w[0], w[1]

def calc_jacobian():
    # 9 Par quotes -> 9 Zero rates (leaving out today's node at index 0)
    nodes_current = curve_cubic.nodes()
    cur_pillar_dates = [node[0] for node in nodes_current]
    base_zeros = np.array([curve_cubic.zeroRate(cur_pillar_dates[i], day_count, ql.Continuous).rate() for i in range(1, 10)])
    J = np.zeros((9, 9))
    bump = 0.0001
    
    for j in range(9):
        o_val = quotes[j].value()
        quotes[j].setValue(o_val + bump)
        bumped_zeros = np.array([curve_cubic.zeroRate(cur_pillar_dates[i], day_count, ql.Continuous).rate() for i in range(1, 10)])
        J[:, j] = (bumped_zeros - base_zeros) / bump
        quotes[j].setValue(o_val)
    return J

def calc_zero_deltas(obj):
    deltas = np.zeros(9)
    bump = 0.0001
    
    # Extract dynamic sliding pillar dates and true base zero rates array
    nodes_current = curve_cubic.nodes()
    cur_pillar_dates = [node[0] for node in nodes_current]
    
    zero_rates = [curve_cubic.zeroRate(cur_pillar_dates[i], day_count, ql.Continuous).rate() for i in range(10)]
    zero_rates[0] = zero_rates[1] # To avoid jump at today
    
    # Calculate Base NPV without bump
    base_zc = ql.ZeroCurve(cur_pillar_dates, zero_rates, day_count, calendar, ql.Linear(), ql.Continuous, ql.Annual)
    base_zc.enableExtrapolation()
    curve_handle_zero.linkTo(base_zc)
    base_npv = obj.NPV()
    
    for i in range(1, 10):
        bumped_rates = zero_rates.copy()
        bumped_rates[i] += bump
        
        bumped_zc = ql.ZeroCurve(cur_pillar_dates, bumped_rates, day_count, calendar, ql.Linear(), ql.Continuous, ql.Annual)
        bumped_zc.enableExtrapolation()
        curve_handle_zero.linkTo(bumped_zc)
        
        up_npv = obj.NPV()
        deltas[i-1] = up_npv - base_npv
    return deltas

def calc_hedge_strB_dual():
    J = calc_jacobian()
    
    z_b = calc_zero_deltas(base_swap_zero)
    z_h2 = calc_zero_deltas(unit_h2_zero)
    z_h3 = calc_zero_deltas(unit_h3_zero)
    
    # Par Delta = J_Transpose * Zero_Delta (Rule of Chain differentiation)
    p_b = J.T @ z_b
    p_h2 = J.T @ z_h2
    p_h3 = J.T @ z_h3
    
    # Bucket 5(2Y), Bucket 6(3Y)
    A = np.array([[p_h2[5], p_h3[5]], [p_h2[6], p_h3[6]]])
    b = np.array([-p_b[5], -p_b[6]])
    w = np.linalg.solve(A, b)
    return w[0], w[1]

# Display initial Day 0 configurations
q2_A, q3_A = calc_hedge_strA_linear()
q2_B, q3_B = calc_hedge_strB_dual()
print(f"Day 0 Hedge (Str A: Linear PAR) | 2Y: {q2_A:,.0f}, 3Y: {q3_A:,.0f}")
print(f"Day 0 Hedge (Str B: Dual Jacobian) | 2Y: {q2_B:,.0f}, 3Y: {q3_B:,.0f}")

# 4. Monte Carlo Simulator
records = []
try:
    for p in range(1, num_paths + 1):
        if p % 10 == 0:
            print(f"Running Path {p}/{num_paths}...")
        
        ql.IndexManager.instance().clearHistories()
        
        f_current = np.zeros(3)
        current_rates = initial_rates.copy()
        for i in range(9):
            quotes[i].setValue(current_rates[i])
            
        cum_pnl_strA = 0.0
        cum_pnl_strB = 0.0
        cum_pnl_linear_internal = 0.0
        
        cum_base_pnl_cubic = 0.0
        cum_h2_pnl_strA_cubic = 0.0
        cum_h3_pnl_strA_cubic = 0.0
        cum_h2_pnl_strB_cubic = 0.0
        cum_h3_pnl_strB_cubic = 0.0
        
        cum_base_pnl_linear = 0.0
        cum_h2_pnl_linear = 0.0
        cum_h3_pnl_linear = 0.0
        
        cum_theta_cubic = 0.0
        cum_theta_linear = 0.0
        cum_delta_pnl_cubic = 0.0
        cum_delta_pnl_linear = 0.0
        
        prev_base_cubic = 0.0
        prev_h2_cubic = 0.0
        prev_h3_cubic = 0.0
        
        prev_base_linear = 0.0
        prev_h2_linear = 0.0
        prev_h3_linear = 0.0
        
        prev_q2_A, prev_q3_A = 0.0, 0.0
        prev_q2_B, prev_q3_B = 0.0, 0.0
            
        for d in range(days_sim + 1):
            eval_date = sys_dates[d]
            ql.Settings.instance().evaluationDate = eval_date
            
            if d > 0:
                prev_date = sys_dates[d-1]
                try:
                    sofr_index_cubic.addFixing(prev_date, current_rates[0], True)
                    sofr_index_linear.addFixing(prev_date, current_rates[0], True)
                except Exception: 
                    pass
                    
                # 1. 시간 경과에 따른 NPV 평가 (Theta)
                aged_base_cubic = base_swap_cubic.NPV()
                aged_base_linear = base_swap_linear.NPV()
                
                daily_theta_cubic = aged_base_cubic - prev_base_cubic
                daily_theta_linear = aged_base_linear - prev_base_linear
                
                random_shock = np.random.normal(0, 1, 3)
                f_current = f_current * (1 - mr_speed) + vols * random_shock
                current_rates = initial_rates + loadings @ f_current
                
                for i in range(9):
                    quotes[i].setValue(current_rates[i])
                    
            # Traders compute hedges in their own systems
            cur_q2_A, cur_q3_A = calc_hedge_strA_linear()
            cur_q2_B, cur_q3_B = calc_hedge_strB_dual()
            
            # The True MTM Evaluations
            base_cubic = base_swap_cubic.NPV()
            h2_cubic = unit_h2_cubic.NPV()
            h3_cubic = unit_h3_cubic.NPV()
            
            # The FALSE Internal MTM Evaluations (Under Linear Par system)
            base_linear = base_swap_linear.NPV()
            h2_linear = unit_h2_linear.NPV()
            h3_linear = unit_h3_linear.NPV()
            
            if d == 0:
                daily_A = 0.0
                daily_B = 0.0
                # 거래 당일(Day 0), Cubic Par Rate로 맺은 거래를 Linear 렌즈로 보면 즉각적인 평가액 터짐(Upfront Loss) 발생
                daily_linear = base_linear + cur_q2_A * h2_linear + cur_q3_A * h3_linear
            else:
                daily_A = (base_cubic - prev_base_cubic) + prev_q2_A * (h2_cubic - prev_h2_cubic) + prev_q3_A * (h3_cubic - prev_h3_cubic)
                daily_B = (base_cubic - prev_base_cubic) + prev_q2_B * (h2_cubic - prev_h2_cubic) + prev_q3_B * (h3_cubic - prev_h3_cubic)
                daily_linear = (base_linear - prev_base_linear) + prev_q2_A * (h2_linear - prev_h2_linear) + prev_q3_A * (h3_linear - prev_h3_linear)
                
                # Theta vs Delta (Rate Effect) 분해
                daily_delta_pnl_cubic = base_cubic - aged_base_cubic
                daily_delta_pnl_linear = base_linear - aged_base_linear
                
                cum_theta_cubic += daily_theta_cubic
                cum_theta_linear += daily_theta_linear
                cum_delta_pnl_cubic += daily_delta_pnl_cubic
                cum_delta_pnl_linear += daily_delta_pnl_linear
                
                # 일일 P&L 요소 분해
                daily_base_cubic = base_cubic - prev_base_cubic
                daily_base_linear = base_linear - prev_base_linear
                
                daily_h2_cubic_strA = prev_q2_A * (h2_cubic - prev_h2_cubic)
                daily_h3_cubic_strA = prev_q3_A * (h3_cubic - prev_h3_cubic)
                
                daily_h2_cubic_strB = prev_q2_B * (h2_cubic - prev_h2_cubic)
                daily_h3_cubic_strB = prev_q3_B * (h3_cubic - prev_h3_cubic)
                
                daily_h2_linear = prev_q2_A * (h2_linear - prev_h2_linear)
                daily_h3_linear = prev_q3_A * (h3_linear - prev_h3_linear)
                
                # 누적 손익 요소
                cum_base_pnl_cubic += daily_base_cubic
                cum_h2_pnl_strA_cubic += daily_h2_cubic_strA
                cum_h3_pnl_strA_cubic += daily_h3_cubic_strA
                
                cum_h2_pnl_strB_cubic += daily_h2_cubic_strB
                cum_h3_pnl_strB_cubic += daily_h3_cubic_strB
                
                cum_base_pnl_linear += daily_base_linear
                cum_h2_pnl_linear += daily_h2_linear
                cum_h3_pnl_linear += daily_h3_linear
                
            cum_pnl_strA += daily_A
            cum_pnl_strB += daily_B
            cum_pnl_linear_internal += daily_linear

            prev_base_cubic = base_cubic
            prev_h2_cubic = h2_cubic
            prev_h3_cubic = h3_cubic
            
            prev_base_linear = base_linear
            prev_h2_linear = h2_linear
            prev_h3_linear = h3_linear
            
            prev_q2_A = cur_q2_A
            prev_q3_A = cur_q3_A
            prev_q2_B = cur_q2_B
            prev_q3_B = cur_q3_B
            
            date_str = f"{sys_dates[d].year()}-{sys_dates[d].month():02d}-{sys_dates[d].dayOfMonth():02d}"
            
            records.append({
                "Day": d,
                "Date": date_str,
                "Path": p,
                "Q2_Req_A": cur_q2_A,
                "Q3_Req_A": cur_q3_A,
                "Q2_Req_B": cur_q2_B,
                "Q3_Req_B": cur_q3_B,
                "NPV_Linear_Internal": cum_pnl_linear_internal,
                "Leakage_StrA": cum_pnl_strA,
                "Leakage_StrB": cum_pnl_strB,
                "Base_PnL_Cubic": cum_base_pnl_cubic,
                "H2_PnL_StrA_Cubic": cum_h2_pnl_strA_cubic,
                "H3_PnL_StrA_Cubic": cum_h3_pnl_strA_cubic,
                "H2_PnL_StrB_Cubic": cum_h2_pnl_strB_cubic,
                "H3_PnL_StrB_Cubic": cum_h3_pnl_strB_cubic,
                "Base_PnL_Linear": cum_base_pnl_linear,
                "H2_PnL_Linear": cum_h2_pnl_linear,
                "H3_PnL_Linear": cum_h3_pnl_linear,
                "Theta_Cubic": cum_theta_cubic,
                "Delta_Cubic": cum_delta_pnl_cubic,
                "Theta_Linear": cum_theta_linear,
                "Delta_Linear": cum_delta_pnl_linear,
                "Rate_2Y": current_rates[5], "Rate_3Y": current_rates[6]
            })

    ql.Settings.instance().evaluationDate = today
    df = pd.DataFrame(records)
    print("Exporting to simulation_results.csv ...")
    df.to_csv("simulation_results.csv", index=False)
    print("Done")

except Exception as e:
    import traceback
    traceback.print_exc()
