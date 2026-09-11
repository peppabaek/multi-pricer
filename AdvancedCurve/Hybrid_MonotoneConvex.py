import QuantLib as ql
import pandas as pd
import math as math
from datetime import datetime
import sys

def parse_tenor(tenor_str: str) -> ql.Period:
    """Pillar 문자열을 QuantLib의 Period 객체로 변환합니다."""
    tenor_str = tenor_str.upper()
    if tenor_str == 'O/N':
        return ql.Period(1, ql.Days)
    unit = tenor_str[-1]
    value = int(tenor_str[:-1])
    if unit == 'W':
        return ql.Period(value, ql.Weeks)
    elif unit == 'M':
        return ql.Period(value, ql.Months)
    elif unit == 'Y':
        return ql.Period(value, ql.Years)
    else:
        raise ValueError(f"Unknown tenor format: {tenor_str}")

def create_sofr_curve_from_market_data(
    eval_date: ql.Date, 
    market_data_df: pd.DataFrame, 
    interpolation_type: str
) -> ql.YieldTermStructure:
    """
    시장을 바탕으로 USD SOFR OIS 커브를 생성합니다.
    지원하는 보간법: 'MonotoneConvexForward', 'FlatForward'
    """
    # 1. QuantLib 기본 환경 설정
    ql.Settings.instance().evaluationDate = eval_date
    payment_calendar = ql.UnitedStates(ql.UnitedStates.FederalReserve)
    day_counter = ql.Actual360() # SOFR OIS 시장 관행

    # 2. RateHelper 리스트 초기화
    rate_helpers = []
    deposit_helpers = [] # DepositRateHelper를 임시 저장할 리스트

    # 3. 커브 핸들 및 SOFR 인덱스 생성
    sofr_curve_handle = ql.RelinkableYieldTermStructureHandle()
    sofr_index = ql.Sofr(sofr_curve_handle)

    # 4. 시장 데이터를 바탕으로 RateHelper 생성
    for index, row in market_data_df.iterrows():
        pillar = row['Tenor']
        rate = row['Market rate'] / 100.0
        quote = ql.QuoteHandle(ql.SimpleQuote(rate))
        tenor = parse_tenor(pillar)
        if pillar.upper() == 'O/N':
            helper = ql.DepositRateHelper(
                quote, tenor, 0, payment_calendar,
                ql.ModifiedFollowing, False, day_counter
            )
            deposit_helpers.append(helper)

    # 4-1. 임시 커브 생성
    # MonotoneConvexForward의 경우 초기 추정을 위해 LinearForward 사용
    if interpolation_type == 'MonotoneConvexForward' and len(deposit_helpers) >= 2:
        temp_curve = ql.PiecewiseLinearForward(eval_date, deposit_helpers, day_counter)
    else:
        temp_curve = ql.PiecewiseFlatForward(eval_date, deposit_helpers, day_counter)
    sofr_curve_handle.linkTo(temp_curve)

    # 4-2. OISRateHelper 생성
    for index, row in market_data_df.iterrows():
        pillar = row['Tenor']
        rate = row['Market rate'] / 100.0
        quote = ql.QuoteHandle(ql.SimpleQuote(rate))
        tenor = parse_tenor(pillar)
        
        if pillar.upper() != 'O/N': # O/N은 DepositRateHelper로 처리했으므로 제외
            freq = ql.Annual if tenor > ql.Period(1, ql.Years) else ql.Once
            helper = ql.OISRateHelper(2, tenor, quote, sofr_index, discountingCurve=sofr_curve_handle, paymentLag=2, paymentFrequency=freq)
            rate_helpers.append(helper)

    # 4-3. 최종 Helper 리스트 생성
    rate_helpers = deposit_helpers + rate_helpers

    # 5. 커브 빌드
    print(f"... [{interpolation_type}] 보간법을 사용하여 커브를 생성합니다.")
    sys.stdout.flush()
    
    if interpolation_type == 'MonotoneConvexForward':
        bootstrap = ql.IterativeBootstrap(
            accuracy=1.0e-15, # Max precision
            maxEvaluations=100000, # Increased max evaluations
            dontThrow=True # Don't crash if convergence is close but not exact
        )
        convex_monotone = ql.ConvexMonotone(
            quadraticity=0.00001, monotonicity=1, forcePositive=True
        )
        sofr_curve = ql.PiecewiseConvexMonotoneForward(
            eval_date, rate_helpers, day_counter, 
            bootstrap, 
            convex_monotone
        )
        
    elif interpolation_type == 'FlatForward':
        # Short Curve precision set to 1e-15 as requested
        bootstrap = ql.IterativeBootstrap(accuracy=1.0e-15, maxEvaluations=100000, dontThrow=True)
        sofr_curve = ql.PiecewiseFlatForward(
            eval_date, rate_helpers, day_counter, bootstrap
        )
        
    else:
        raise ValueError(f"지원하지 않는 보간법입니다: {interpolation_type}")
    
    # 6. 생성된 커브를 핸들에 연결(link)
    sofr_curve_handle.linkTo(sofr_curve)
    
    return sofr_curve

class HybridCurveWrapper:
    """
    두 개의 QuantLib YieldTermStructure를 결합하여 하나의 커브처럼 동작하게 하는 래퍼 클래스입니다.
    switch_date를 기준으로 단기 커브와 장기 커브를 전환합니다.
    """
    def __init__(self, short_curve, long_curve, switch_date):
        self.short_curve = short_curve
        self.long_curve = long_curve
        self.switch_date = switch_date

    def discount(self, d, extrapolate=False):
        if d <= self.switch_date:
            return self.short_curve.discount(d, extrapolate)
        else:
            # 단순 전환 (Simple Switch)
            return self.long_curve.discount(d, extrapolate)

    def zeroRate(self, d, day_counter, compounding, frequency=ql.Annual, extrapolate=False):
        if d <= self.switch_date:
            return self.short_curve.zeroRate(d, day_counter, compounding, frequency, extrapolate)
        else:
            return self.long_curve.zeroRate(d, day_counter, compounding, frequency, extrapolate)

    def forwardRate(self, d1, d2, day_counter, compounding, frequency=ql.Annual, extrapolate=False):
        # 시작일(d1)을 기준으로 커브 선택
        if d1 < self.switch_date:
            return self.short_curve.forwardRate(d1, d2, day_counter, compounding, frequency, extrapolate)
        else:
            return self.long_curve.forwardRate(d1, d2, day_counter, compounding, frequency, extrapolate)
    
    def enableExtrapolation(self):
        self.short_curve.enableExtrapolation()
        self.long_curve.enableExtrapolation()

def generate_ql_output(
    eval_date: ql.Date, 
    curve: ql.YieldTermStructure,
    dates_df: pd.DataFrame,
    market_data_df: pd.DataFrame
) -> pd.DataFrame:
    """
    캘리브레이션된 커브를 사용하여 Murex 포맷과 동일한 결과물을 생성합니다.
    """
    results = []
    day_counter_zc = ql.Actual365Fixed()
 
    pillar_dates = set(pd.to_datetime(market_data_df['Maturity']))

    for date_str in dates_df['Date']:
        current_date_dt = datetime.strptime(date_str, '%Y-%m-%d')
        current_date_ql = ql.Date.from_date(current_date_dt)
        
        pillar = 'Y' if pd.to_datetime(date_str) in pillar_dates else 'N'

        if current_date_ql == eval_date:
            zc = curve.zeroRate(eval_date, day_counter_zc, ql.Continuous).rate() * 100
            df = 1.0
            fwd_rate = 0.0
        else:
            zc = curve.zeroRate(current_date_ql, day_counter_zc, ql.Continuous).rate() * 100
            df = curve.discount(current_date_ql)
            prev_date_ql = current_date_ql - ql.Period(1, ql.Days)
            fwd_rate = curve.forwardRate(
                prev_date_ql, current_date_ql,
                ql.Actual360(), ql.Simple
            ).rate() * 100

        results.append([date_str, zc, df, pillar, fwd_rate])

    return pd.DataFrame(results, columns=['Date', 'ZC', 'DF', 'Pillar', 'Forward rate'])

def convert_to_ql_curve(
    eval_date: ql.Date,
    hybrid_curve: HybridCurveWrapper,
    max_date: ql.Date
) -> ql.YieldTermStructure:
    """
    HybridCurveWrapper를 샘플링하여 QuantLib의 DiscountCurve 객체로 변환합니다.
    ZeroCurve(Linear Zero Rate) 대신 DiscountCurve(LogLinear Discount)를 사용하여
    FlatForward(Constant Forward) 구간의 정확도를 높입니다.
    """
    dates = []
    dfs = []
    day_counter = ql.Actual360() # Match market convention
    
    # 기준일부터 최대 만기까지 일별로 샘플링
    d = eval_date
    while d <= max_date:
        dates.append(d)
        df = hybrid_curve.discount(d)
        dfs.append(df)
        d += ql.Period(1, ql.Days)

    return ql.DiscountCurve(dates, dfs, day_counter)

def create_hybrid_curve_iterative(
    eval_date: ql.Date,
    short_curve: ql.YieldTermStructure,
    market_data_df: pd.DataFrame,
    switch_date: ql.Date,
    max_iter: int = 30,
    tolerance: float = 1e-5,
    long_end_interpolation: str = 'MonotoneConvexForward'
) -> ql.YieldTermStructure:
    """
    Global Bootstrapping (Dependent Calibration)을 수행하여 Hybrid Curve를 생성합니다.
    Short Curve는 고정하고, Long Curve의 Input Quote를 반복적으로 조정하여 
    Hybrid Curve가 시장가(Market Rate)를 정확히 Repricing하도록 만듭니다.
    """
    print(f"Starting Global Bootstrapping (Quote Adjustment Method)...")
    sys.stdout.flush()
    
    # 1. 초기 Quote 설정 (Market Rate 그대로 시작)
    current_quotes = {}
    market_rates = {} 
    ql_quotes = {}
    rate_helpers = []
    
    payment_calendar = ql.UnitedStates(ql.UnitedStates.FederalReserve)
    day_counter = ql.Actual360()
    sofr_curve_handle = ql.RelinkableYieldTermStructureHandle()
    sofr_index = ql.Sofr(sofr_curve_handle)

    # Helper 생성
    for index, row in market_data_df.iterrows():
        pillar = row['Tenor']
        rate = row['Market rate'] / 100.0
        
        market_rates[pillar] = rate
        current_quotes[pillar] = rate
        
        ql_quote = ql.SimpleQuote(rate)
        ql_quotes[pillar] = ql_quote
        handle = ql.QuoteHandle(ql_quote)
        
        tenor = parse_tenor(pillar)
        
        if pillar.upper() == 'O/N':
            helper = ql.DepositRateHelper(
                handle, tenor, 0, payment_calendar,
                ql.ModifiedFollowing, False, day_counter
            )
            rate_helpers.append(helper)
        else:
            freq = ql.Annual if tenor > ql.Period(1, ql.Years) else ql.Once
            helper = ql.OISRateHelper(
                2, tenor, handle, sofr_index, 
                paymentLag=2, 
                paymentFrequency=freq
            )
            rate_helpers.append(helper)

    # 2. Iteration
    current_long_curve = None
    
    for i in range(max_iter):
        # A. Long Curve 생성
        bootstrap = ql.IterativeBootstrap(accuracy=1.0e-15, maxEvaluations=100000, dontThrow=True)
        convex_monotone = ql.ConvexMonotone(quadraticity=0.00001, monotonicity=1, forcePositive=True)
        
        if current_long_curve is None:
             temp_curve = ql.PiecewiseLinearForward(eval_date, rate_helpers, day_counter)
             sofr_curve_handle.linkTo(temp_curve)
        else:
             sofr_curve_handle.linkTo(current_long_curve)

        if long_end_interpolation == 'MonotoneConvexForward':
            new_long_curve = ql.PiecewiseConvexMonotoneForward(
                eval_date, rate_helpers, day_counter, 
                bootstrap, 
                convex_monotone
            )
        else:
             raise ValueError(f"Unknown interpolation: {long_end_interpolation}")
        new_long_curve.enableExtrapolation()
        
        sofr_curve_handle.linkTo(new_long_curve)
        current_long_curve = new_long_curve
        
        # B. Hybrid Wrapper 생성
        hybrid_wrapper = HybridCurveWrapper(short_curve, current_long_curve, switch_date)
        hybrid_wrapper.enableExtrapolation()
        
        # C. Repricing 및 Error 계산
        max_error = 0.0
        print(f"Iteration {i+1}: Checking Repricing Errors...")
        sys.stdout.flush()
        
        # Manual Pricing Function
        def get_hybrid_rate(pillar, tenor, market_val):
            if pillar == 'O/N':
                start = eval_date
                end = payment_calendar.advance(start, tenor)
                df_start = hybrid_wrapper.discount(start)
                df_end = hybrid_wrapper.discount(end)
                t = day_counter.yearFraction(start, end)
                if t==0: return 0.0
                return (df_start/df_end - 1.0)/t
            else:
                empty_h = ql.YieldTermStructureHandle()
                idx = ql.OvernightIndex("USD SOFR", 0, ql.USDCurrency(), payment_calendar, day_counter, empty_h)
                ois = ql.MakeOIS(tenor, idx, 0.0, paymentLag=2)
                
                fixed_leg = ois.fixedLeg()
                annuity = 0.0
                for cf in fixed_leg:
                    c = ql.as_coupon(cf)
                    annuity += c.accrualPeriod() * hybrid_wrapper.discount(c.date())
                
                floating_leg = ois.overnightLeg()
                float_npv = 0.0
                for cf in floating_leg:
                    c = ql.as_coupon(cf)
                    d_s = c.accrualStartDate()
                    d_e = c.accrualEndDate()
                    d_p = c.date()
                    term = (hybrid_wrapper.discount(d_s)/hybrid_wrapper.discount(d_e) - 1.0)
                    float_npv += term * hybrid_wrapper.discount(d_p)
                
                if annuity == 0: return 0.0
                return float_npv / annuity

        converged = True
        
        for pillar, ql_quote in ql_quotes.items():
            tenor = parse_tenor(pillar)
            maturity = payment_calendar.advance(eval_date, tenor)
            
            if maturity > switch_date:
                model_rate = get_hybrid_rate(pillar, tenor, market_rates[pillar])
                market_rate = market_rates[pillar]
                
                error = model_rate - market_rate
                max_error = max(max_error, abs(error))
                
                new_quote_val = ql_quote.value() - error
                ql_quote.setValue(new_quote_val)
                current_quotes[pillar] = new_quote_val
                
                if abs(error) > tolerance:
                    converged = False

        print(f"  Max Error (> SwitchDate): {max_error * 10000:.6f} bps")
        sys.stdout.flush()
        
        if converged:
            print(f"Converged after {i+1} iterations.")
    print("-" * 60)
    return current_long_curve

def reprice_instruments(
    eval_date: ql.Date,
    market_data_df: pd.DataFrame,
    curve: ql.YieldTermStructure
):
    """
    주어진 커브를 사용하여 시장 상품(Deposit, OIS)의 금리를 역산(Repricing)하고 비교합니다.
    """
    print(f"--- Market Instruments Repricing ---")
    print(f"{'Tenor':<6} {'Market Rate (%)':<15} {'Repriced Rate (%)':<18} {'Diff (bps)':<12}")
    print("-" * 60)
    sys.stdout.flush()

    # 커브 핸들 설정
    yts_handle = ql.RelinkableYieldTermStructureHandle()
    
    # HybridCurveWrapper인지 확인
    is_hybrid = isinstance(curve, HybridCurveWrapper)
    
    if not is_hybrid:
        yts_handle.linkTo(curve)
    
    # Explicitly create OvernightIndex with handle for clean leg generation
    sofr_index = ql.OvernightIndex("USD SOFR", 0, ql.USDCurrency(), ql.UnitedStates(ql.UnitedStates.FederalReserve), ql.Actual360(), yts_handle)
    
    payment_calendar = ql.UnitedStates(ql.UnitedStates.FederalReserve)
    day_counter = ql.Actual360()

    for index, row in market_data_df.iterrows():
        pillar = row['Tenor']
        market_rate = row['Market rate']
        quote = ql.QuoteHandle(ql.SimpleQuote(market_rate / 100.0))
        tenor = parse_tenor(pillar)

        implied_rate = 0.0

        if pillar.upper() == 'O/N':
            # DepositRateHelper는 setTermStructure가 없을 수 있으므로 수동 계산
            start_date = eval_date
            maturity_date = payment_calendar.advance(start_date, tenor)
            
            df_start = curve.discount(start_date)
            df_end = curve.discount(maturity_date)
                
            t = day_counter.yearFraction(start_date, maturity_date)
            
            if t > 0:
                implied_rate = (df_start / df_end - 1.0) / t * 100.0
            
        else:
            freq = ql.Annual if tenor > ql.Period(1, ql.Years) else ql.Once
            try:
                if is_hybrid:
                    # HybridCurveWrapper인 경우 수동 Pricing 수행
                    # OISRateHelper와 동일하게 paymentLag=2 설정
                    ois_swap = ql.MakeOIS(tenor, sofr_index, market_rate/100.0, paymentLag=2)
                    
                    # 1. Annuity 계산 (Fixed Leg)
                    fixed_leg = ois_swap.fixedLeg()
                    annuity = 0.0
                    for cf in fixed_leg:
                        coupon = ql.as_coupon(cf)
                        t = coupon.accrualPeriod()
                        d = coupon.date()
                        df = curve.discount(d)
                        annuity += t * df
                        
                    # 2. Floating NPV 계산 (Floating Leg)
                    floating_leg = ois_swap.overnightLeg()
                    floating_npv = 0.0
                    for cf in floating_leg:
                        coupon = ql.as_coupon(cf)
                        d_start = coupon.accrualStartDate()
                        d_end = coupon.accrualEndDate()
                        d_pay = coupon.date()
                        
                        df_start = curve.discount(d_start)
                        df_end = curve.discount(d_end)
                        df_pay = curve.discount(d_pay)
                        
                        # PV = (DF_start / DF_end - 1) * DF_pay
                        term_factor = (df_start / df_end - 1.0)
                        pv_coupon = term_factor * df_pay
                        floating_npv += pv_coupon
                        
                    implied_rate = (floating_npv / annuity) * 100.0
                    
                else:
                    # 일반 QuantLib 커브인 경우 엔진 사용
                    ois_swap = ql.MakeOIS(tenor, sofr_index, market_rate/100.0, paymentLag=2)
                    ois_swap.setPricingEngine(ql.DiscountingSwapEngine(yts_handle))
                    implied_rate = ois_swap.fairRate() * 100.0
                    
            except Exception as e:
                print(f"Error creating/pricing OIS for {pillar}: {e}")
                implied_rate = 0.0
        
        diff_bps = abs(market_rate - implied_rate) * 100

        print(f"{pillar:<6} {market_rate:<15.6f} {implied_rate:<18.6f} {diff_bps:<12.6f}")
    print("-" * 60)
    print("\n")
    sys.stdout.flush()


def main():
    """메인 실행 함수"""
    # --- 데이터 준비 (MonotoneConvexForward - 장기 커브용) ---
    MARKET_DATA_MC_FILE = 'market_data_MC.csv'

    market_df_mc = pd.read_csv(MARKET_DATA_MC_FILE, parse_dates=['Start date', 'Maturity'])
    market_df_mc.sort_values(by='Maturity', inplace=True)
    eval_date_str = market_df_mc['Start date'].iloc[0].strftime('%Y-%m-%d')
    eval_date = ql.Date.from_date(datetime.strptime(eval_date_str, '%Y-%m-%d'))

    # --- 데이터 준비 (FlatForward - 단기 커브용) ---
    MARKET_DATA_FILE = 'market_data.csv'

    market_df_flatforward = pd.read_csv(MARKET_DATA_FILE, parse_dates=['Start date', 'Maturity'])
    market_df_flatforward.sort_values(by='Maturity', inplace=True)

    # --- FlatForward 단기 커브 생성 ---
    print("=" * 75)
    print("[FlatForward] 단기 커브 생성을 시작합니다.")
    print(f"기준일: {eval_date_str}")
    sys.stdout.flush()
    sofr_flatforward_curve = create_sofr_curve_from_market_data(
        eval_date, market_df_flatforward, interpolation_type='FlatForward'
    )
    sofr_flatforward_curve.enableExtrapolation()
    print("캘리브레이션 완료.\n")
    sys.stdout.flush()

    # Global Evaluation Date 복구 (Hybrid Curve 생성을 위해)
    ql.Settings.instance().evaluationDate = eval_date

    # --- Hybrid Curve 생성 (Dependent Calibration) ---
    print("=" * 75)
    # Switch Date: 2Y Swap의 실제 만기일(2027-12-08)로 설정
    switch_date = ql.Date(8, 12, 2027)
    
    print(f"[Hybrid Curve] 생성을 시작합니다. (Switch Date: {switch_date})")
    print("Short End: FlatForward (Fixed)")
    print("Long End: MonotoneConvexForward (Iteratively Bootstrapped)")
    sys.stdout.flush()
    
    # Iterative Method 사용
    sofr_long_curve_iterative = create_hybrid_curve_iterative(
        eval_date, sofr_flatforward_curve, market_df_mc, switch_date,
        tolerance=1e-5
    )
    
    # 최종 Hybrid Curve Wrapper 생성
    sofr_hybrid_curve = HybridCurveWrapper(sofr_flatforward_curve, sofr_long_curve_iterative, switch_date)
    sofr_hybrid_curve.enableExtrapolation()
    print("Hybrid Curve 생성 완료 (Global Bootstrapping).\n")
    sys.stdout.flush()

    # --- 데이터 준비 (Hybrid 검증용) ---
    MUREX_OUTPUT_HYBRID_FILE = 'murex_output_Hybrid.csv'
    try:
        murex_df_hybrid = pd.read_csv(MUREX_OUTPUT_HYBRID_FILE)
    except FileNotFoundError:
        print(f"Warning: {MUREX_OUTPUT_HYBRID_FILE} not found. Using MC data for verification structure only.")
        murex_df_hybrid = market_df_mc.copy()

    # --- 캘리브레이션 결과 검증 (vs Murex ZC) ---
    ql.Settings.instance().evaluationDate = eval_date
    murex_pillars = murex_df_hybrid[murex_df_hybrid['Pillar'] == 'Y'].copy()
    murex_pillars['Date'] = pd.to_datetime(murex_pillars['Date']).dt.date

    print("=" * 75)
    print(f"--- [Hybrid (Flat+MC)] 캘리브레이션 결과 검증 (vs Murex Pillar) ---")
    print(f"{'Pillar':<6} {'Maturity':<12} {'Murex ZC (%)':<15} {'QL ZC (%)':<12} {'Abs. Diff. (bps)':<18}")
    print("-" * 75)
    sys.stdout.flush()

    day_counter_for_zc = ql.Actual365Fixed()

    for index, row in market_df_mc.iterrows():
        pillar_str = row['Tenor']
        murex_row = murex_pillars[murex_pillars['Date'] == row['Maturity'].date()]
        
        if not murex_row.empty:
            maturity_date_ql = ql.Date.from_date(row['Maturity'])
            
            ql_zc = sofr_hybrid_curve.zeroRate(maturity_date_ql, day_counter_for_zc, ql.Continuous).rate() * 100
            murex_zc = murex_row.iloc[0]['ZC']
            diff_bps = abs(ql_zc - murex_zc) * 100

            print(f"{pillar_str:<6} {row['Maturity'].strftime('%Y-%m-%d'):<12} {murex_zc:<15.4f} {ql_zc:<12.4f} {diff_bps:<18.4f}")

    # --- QuantLib 결과 파일 생성 ---
    output_file = 'ql_output_hybrid.csv'
    print(f"\n[Hybrid (Flat+MC)] QuantLib 커브 결과물({output_file})을 생성합니다...")
    ql_output_df = generate_ql_output(eval_date, sofr_hybrid_curve, murex_df_hybrid, market_df_mc)
    ql_output_df.to_csv(output_file, index=False, float_format='%.9f')
    print(f"{output_file} 파일 생성이 완료되었습니다.\n")
    sys.stdout.flush()

    # --- Repricing 검증 ---
    print(f"[Hybrid (Flat+MC)] Repricing 검증을 수행합니다.")
    sys.stdout.flush()
    reprice_instruments(eval_date, market_df_mc, sofr_hybrid_curve)

if __name__ == '__main__':
    main()