import QuantLib as ql
import pandas as pd
import math as math
from datetime import datetime

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
    interpolation_type: str = 'FlatForward'
) -> ql.YieldTermStructure:
    """
    시장을 바탕으로 USD SOFR OIS 커브를 생성합니다. (수정됨)
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

    # 4. 시장 데이터를 바탕으로 RateHelper 생성 (기존과 동일)
    deposit_helpers = []
    rate_helpers = []
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

    # 4-1. 임시 커브 생성 (기존과 동일)
    if interpolation_type in ['MonotoneConvexForward', 'LogMixedLinearCubicDiscount'] and len(deposit_helpers) >= 2:
        temp_curve = ql.PiecewiseLinearForward(eval_date, deposit_helpers, day_counter)
    else:
        temp_curve = ql.PiecewiseFlatForward(eval_date, deposit_helpers, day_counter)
    sofr_curve_handle.linkTo(temp_curve)

    # 4-2. OISRateHelper 생성 (기존과 동일)
    for index, row in market_data_df.iterrows():
        pillar = row['Tenor']
        rate = row['Market rate'] / 100.0
        quote = ql.QuoteHandle(ql.SimpleQuote(rate))
        tenor = parse_tenor(pillar)
        if pillar.upper() not in ['O/N']:
            freq = ql.Annual if tenor > ql.Period(1, ql.Years) else ql.Once
            helper = ql.OISRateHelper(2, tenor, quote, sofr_index, discountingCurve=sofr_curve_handle, paymentLag=2, paymentFrequency=freq)
            rate_helpers.append(helper)

    # 4-3. 최종 Helper 리스트 생성 (기존과 동일)
    rate_helpers = deposit_helpers + rate_helpers

    # 5. 커브 빌드 (수정됨)
    
    # 5-1. (추가) 공통으로 사용할 IterativeBootstrap 객체 생성
    bootstrap = ql.IterativeBootstrap(
        accuracy=1.0e-14, 
        maxEvaluations=5000, 
        dontThrow=False
    )
    
    # 5-2. (추가) LogMixedLinearCubicDiscount를 위한 분기점(n_split) 계산
    #      (2Y 테너를 기준으로 Linear와 Cubic을 분리)
    switch_tenor_period = ql.Period(3, ql.Years)
    switch_date = eval_date + switch_tenor_period
    n_split = 0
    for i, helper in enumerate(rate_helpers):
        if helper.maturityDate() > switch_date:
            n_split = i
            break
    if n_split == 0: # 2Y보다 긴 테너가 없으면
        n_split = len(rate_helpers) 

    print(f"... [{interpolation_type}] 보간법을 사용하여 커브를 생성합니다.")
    
    if interpolation_type == 'LinearForward':
        sofr_curve = ql.PiecewiseLinearForward(
            eval_date, rate_helpers, day_counter
        )
    
    # --- ⬇️ 여기가 추가된 블록 ⬇️ ---
    elif interpolation_type == 'LogMixedLinearCubicDiscount':
        print(f"... 2Y 분기점(n={n_split})을 기준으로 Mixed 보간법을 설정합니다.")
        
        # --- ⬇️ 여기가 수정된 부분 ⬇️ ---
        # 믹서기 객체 생성: 
        # 이 클래스는 Linear와 Cubic을 쓴다는 것을 이미 알고 있으므로,
        # "어디서" 섞을지(n_split)만 알려주면 됩니다.
        mixed_interpolator = ql.LogMixedLinearCubic(
            n_split # <- ql.Linear(), ql.Cubic() 삭제
        )
        # --- ⬆️ 여기까지 ⬆️ ---
        
        jumps = ql.QuoteHandleVector()
        jumpDates = ql.DateVector()

        sofr_curve = ql.PiecewiseLogMixedLinearCubicDiscount(
            eval_date,          
            rate_helpers,       
            day_counter,        
            jumps,              
            jumpDates,          
            mixed_interpolator, # 6. i (interpolator)
            bootstrap           # 7. b (bootstrap)
        )
    # --- ⬆️ 여기까지 ⬆️ ---
    
    elif interpolation_type == 'MonotoneConvexForward':
        convex_monotone = ql.ConvexMonotone(
            quadraticity=0.00001, monotonicity=1, forcePositive=True
        )
        # bootstrap 객체는 위에서 공통으로 생성
        sofr_curve = ql.PiecewiseConvexMonotoneForward(
            eval_date, rate_helpers, day_counter, 
            bootstrap, # 4번째 인자: IterativeBootstrap 객체
            convex_monotone # 5번째 인자: ConvexMonotone 객체
        )
        
    elif interpolation_type == 'LogLinearDiscount':
        sofr_curve = ql.PiecewiseLogLinearDiscount(
            eval_date, rate_helpers, day_counter
        )
        
    elif interpolation_type == 'FlatForward': # 기본값
        sofr_curve = ql.PiecewiseFlatForward(
            eval_date, rate_helpers, day_counter
        )
    else:
        raise ValueError(f"지원하지 않는 보간법입니다: {interpolation_type}")
    
    # 6. 생성된 커브를 핸들에 연결(link)
    sofr_curve_handle.linkTo(sofr_curve)
    
    return sofr_curve




# (HybridCurveWrapper: Continuous Hermite Blending 방식 적용)
class HybridCurveWrapper:
    """
    Continuous Hybrid Curve Wrapper:
    단순접합(Hard Splice) 대신 2Y Junction 주변에서 C^1 Hermite Partition of Unity
    (w(u) = 3u^2 - 2u^3)를 적용하여 단기 Flat Forward와 장기 Cubic Spline을
    도약(Jump) 및 꺾임(Kink) 없이 부드럽고 연속적으로 연결(Continuous)하는 래퍼 객체.
    """
    
    def __init__(self, 
                 curve1_handle: ql.YieldTermStructureHandle, 
                 curve2_handle: ql.YieldTermStructureHandle, 
                 switch_date: ql.Date,
                 transition_days: int = 120):
        
        self.curve1 = curve1_handle
        self.curve2 = curve2_handle
        self.switch_date = switch_date
        self.transition_days = transition_days
        
        self.t_end = switch_date
        self.t_start = switch_date - ql.Period(transition_days, ql.Days)
        self.span_days = float(self.t_end - self.t_start)
        
        self._ref_date = self.curve1.referenceDate()
        self._day_counter = self.curve1.dayCounter()
        self._calendar = self.curve1.calendar()

    def _get_weight(self, d: ql.Date) -> float:
        if d <= self.t_start:
            return 0.0
        elif d >= self.t_end:
            return 1.0
        u = float(d - self.t_start) / self.span_days
        u = max(0.0, min(1.0, u))
        return 3.0 * (u ** 2) - 2.0 * (u ** 3)

    def zeroRate(self, *args):
        if isinstance(args[0], ql.Date):
            d = args[0]
            w = self._get_weight(d)
            if w == 0.0:
                return self.curve1.zeroRate(*args)
            elif w == 1.0:
                return self.curve2.zeroRate(*args)
            z1 = self.curve1.zeroRate(*args).rate()
            z2 = self.curve2.zeroRate(*args).rate()
            z_blend = (1.0 - w) * z1 + w * z2
            day_counter = args[1] if len(args) > 1 else self._day_counter
            comp = args[2] if len(args) > 2 else ql.Continuous
            freq = args[3] if len(args) > 3 else ql.Annual
            return ql.InterestRate(z_blend, day_counter, comp, freq)
        elif isinstance(args[0], (float, int)):
            return self.curve1.zeroRate(*args)
        else:
            raise TypeError("HybridCurveWrapper: 알 수 없는 zeroRate 호출입니다.")

    def discount(self, *args):
        d = args[0]
        w = self._get_weight(d)
        if w == 0.0:
            return self.curve1.discount(*args)
        elif w == 1.0:
            return self.curve2.discount(*args)
        df1 = float(self.curve1.discount(*args))
        df2 = float(self.curve2.discount(*args))
        log_df1 = math.log(max(1e-12, df1))
        log_df2 = math.log(max(1e-12, df2))
        log_df = (1.0 - w) * log_df1 + w * log_df2
        return math.exp(log_df)

    def forwardRate(self, *args):
        d = args[0]
        w = self._get_weight(d)
        if w == 0.0:
            return self.curve1.forwardRate(*args)
        elif w == 1.0:
            return self.curve2.forwardRate(*args)
        f1 = self.curve1.forwardRate(*args).rate()
        f2 = self.curve2.forwardRate(*args).rate()
        f_blend = (1.0 - w) * f1 + w * f2
        day_counter = args[2] if len(args) > 2 else self._day_counter
        comp = args[3] if len(args) > 3 else ql.Continuous
        freq = args[4] if len(args) > 4 else ql.Annual
        return ql.InterestRate(f_blend, day_counter, comp, freq)

    def referenceDate(self) -> ql.Date:
        return self._ref_date

    def calendar(self) -> ql.Calendar:
        return self._calendar

    def dayCounter(self) -> ql.DayCounter:
        return self._day_counter

    def maxDate(self) -> ql.Date:
        return self.curve2.maxDate()


def main():
    """메인 실행 함수"""
    # --- 데이터 준비 (MC: FlatForward + MonotoneConvexForward + HybridCurve용) ---
    MARKET_DATA_MC_FILE = 'market_data_MC.csv'
    MUREX_OUTPUT_MC_FILE = 'murex_output_MC.csv'

    market_df_mc = pd.read_csv(MARKET_DATA_MC_FILE, parse_dates=['Start date', 'Maturity'])
    eval_date_str = market_df_mc['Start date'].iloc[0].strftime('%Y-%m-%d')
    eval_date = ql.Date.from_date(datetime.strptime(eval_date_str, '%Y-%m-%d'))

    # --- FlatForward 커브 생성 (HybridCurveWrapper용) ---
    print("=" * 75)
    print("[FlatForward] 보간법을 사용하여 커브 생성을 시작합니다.")
    print(f"기준일: {eval_date_str}")
    sofr_flat_forward_curve = create_sofr_curve_from_market_data(eval_date, market_df_mc, interpolation_type='FlatForward')
    sofr_flat_forward_curve.enableExtrapolation()
    print("캘리브레이션 완료.\n")

    # --- MonotoneConvexForward 커브 생성 (HybridCurveWrapper용) ---
    print("=" * 75)
    print("[MonotoneConvexForward] 보간법을 사용하여 커브 생성을 시작합니다.")
    print(f"기준일: {eval_date_str}")
    sofr_mc_forward_curve = create_sofr_curve_from_market_data(eval_date, market_df_mc, interpolation_type='MonotoneConvexForward')
    sofr_mc_forward_curve.enableExtrapolation()
    print("캘리브레이션 완료.\n")

    # --- 하이브리드 커브 생성 ---
    print("=" * 75)
    print("두 커브를 이어붙여 하이브리드 커브를 생성합니다.")
    curve1_handle = ql.YieldTermStructureHandle(sofr_flat_forward_curve)
    curve2_handle = ql.YieldTermStructureHandle(sofr_mc_forward_curve)

    switch_date = eval_date + ql.Period(2, ql.Years)
    print(f"분기점(Switch Date): {switch_date}")
    print(f"[HybridCurveWrapper]를 사용하여 커브를 생성합니다...")
    hybrid_curve = HybridCurveWrapper(curve1_handle, curve2_handle, switch_date)
    print("하이브리드 커브 생성 완료.\n")

    # --- LogMixedLinearCubicDiscount: 별도 데이터 소스 사용 ---
    print("-" * 75)
    print("!!! [LogMixedLinearCubicDiscount]에 대해서는 다른 데이터 소스를 사용합니다. !!!")
    MARKET_DATA_SP_FILE = 'market_data_SP.csv'
    MUREX_OUTPUT_SP_FILE = 'murex_output_SP.csv'

    market_df_logmixed = pd.read_csv(MARKET_DATA_SP_FILE, parse_dates=['Start date', 'Maturity'])
    murex_df_logmixed = pd.read_csv(MUREX_OUTPUT_SP_FILE)

    print("=" * 75)
    print("[LogMixedLinearCubicDiscount] 보간법을 사용하여 커브 생성을 시작합니다.")
    print(f"기준일: {eval_date_str}")
    sofr_logmixed_curve = create_sofr_curve_from_market_data(eval_date, market_df_logmixed, interpolation_type='LogMixedLinearCubicDiscount')
    sofr_logmixed_curve.enableExtrapolation()
    print("캘리브레이션 완료.\n")

    # --- [LogMixedLinearCubicDiscount] 캘리브레이션 결과 검증 (vs Murex Pillar) ---
    murex_pillars = murex_df_logmixed[murex_df_logmixed['Pillar'] == 'Y'].copy()
    murex_pillars['Date'] = pd.to_datetime(murex_pillars['Date']).dt.date

    print("=" * 75)
    print("--- [LogMixedLinearCubicDiscount] 캘리브레이션 결과 검증 (vs Murex Pillar) ---")
    print(f"{'Pillar':<6} {'Maturity':<12} {'Murex ZC (%)':<15} {'QL ZC (%)':<12} {'Abs. Diff. (bps)':<18}")
    print("-" * 75)

    day_counter_for_zc = ql.Actual365Fixed()

    for index, row in market_df_logmixed.iterrows():
        pillar_str = row['Tenor']
        murex_row = murex_pillars[murex_pillars['Date'] == row['Maturity'].date()]

        if not murex_row.empty:
            maturity_date_ql = ql.Date.from_date(row['Maturity'])
            ql_zc = sofr_logmixed_curve.zeroRate(maturity_date_ql, day_counter_for_zc, ql.Continuous).rate() * 100
            murex_zc = murex_row.iloc[0]['ZC']
            diff_bps = abs(ql_zc - murex_zc) * 100
            print(f"{pillar_str:<6} {row['Maturity'].strftime('%Y-%m-%d'):<12} {murex_zc:<15.4f} {ql_zc:<12.4f} {diff_bps:<18.4f}")

if __name__ == '__main__':
    main()