"""Expected, secret-safe failures for aligned portfolio returns."""

from __future__ import annotations


class PortfolioAnalysisError(Exception):
    """Base class for expected portfolio-analysis failures."""


class InvalidAlignedReturnMatrixError(PortfolioAnalysisError):
    """Raised when an aligned return matrix violates a domain invariant."""


class InvalidMinimumObservationsError(PortfolioAnalysisError):
    """Raised when the configured common-close minimum cannot produce returns."""


class EmptyReturnUniverseError(PortfolioAnalysisError):
    """Raised when no active stock histories were supplied."""


class EmptyStockHistoryError(PortfolioAnalysisError):
    """Raised when one active stock has no daily bars."""

    def __init__(self, stock_code: str) -> None:
        self.stock_code = stock_code
        super().__init__(f"종목코드 {stock_code}의 일별 시세 이력이 비어 있습니다.")


class InsufficientStockObservationsError(PortfolioAnalysisError):
    """Raised when one stock has fewer closes than the configured minimum."""

    def __init__(self, stock_code: str, actual: int, required: int) -> None:
        self.stock_code = stock_code
        self.actual = actual
        self.required = required
        super().__init__(
            f"종목코드 {stock_code}의 종가 관측치가 부족합니다: "
            f"{actual}개 (최소 {required}개 필요)."
        )


class InsufficientCommonObservationsError(PortfolioAnalysisError):
    """Raised when the common close-date intersection is too small."""

    def __init__(self, actual: int, required: int) -> None:
        self.actual = actual
        self.required = required
        super().__init__(
            f"모든 종목의 공통 종가 관측치가 부족합니다: {actual}개 (최소 {required}개 필요)."
        )


class ReturnStockCodeMismatchError(PortfolioAnalysisError):
    """Raised when a bar belongs to a different stock than its history."""

    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"일별 시세 종목코드가 유니버스 종목과 일치하지 않습니다: "
            f"예상 {expected}, 실제 {actual}."
        )


class DuplicateReturnStockCodeError(PortfolioAnalysisError):
    """Raised when the input contains the same universe stock more than once."""

    def __init__(self, stock_code: str) -> None:
        self.stock_code = stock_code
        super().__init__(f"수익률 입력에 종목코드 {stock_code}가 중복되었습니다.")


class DuplicateDailyBarDateError(PortfolioAnalysisError):
    """Raised when one stock history repeats a trade date."""

    def __init__(self, stock_code: str) -> None:
        self.stock_code = stock_code
        super().__init__(f"종목코드 {stock_code}의 일별 시세에 중복 거래일이 있습니다.")


class UnsortedDailyBarsError(PortfolioAnalysisError):
    """Raised when one stock history is not strictly oldest-first."""

    def __init__(self, stock_code: str) -> None:
        self.stock_code = stock_code
        super().__init__(
            f"종목코드 {stock_code}의 일별 시세는 거래일 기준 엄격한 오름차순이어야 합니다."
        )


class InvalidPerformanceMetricsError(PortfolioAnalysisError):
    """Raised when one immutable performance summary violates its invariants."""


class InvalidHistoricalUniverseAnalysisError(PortfolioAnalysisError):
    """Raised when historical-analysis dimensions or values are inconsistent."""


class InsufficientPerformanceObservationsError(PortfolioAnalysisError):
    """Raised when fewer than two aligned daily returns are available."""

    def __init__(self, actual: int) -> None:
        self.actual = actual
        super().__init__(
            f"과거 성과 분석에는 최소 2개의 수익률 관측치가 필요합니다: 현재 {actual}개."
        )


class InvalidPerformanceReturnError(PortfolioAnalysisError):
    """Raised when a return cannot produce a positive growth factor."""


class HistoricalReportStockOrderError(PortfolioAnalysisError):
    """Raised when stock names cannot be aligned exactly to matrix columns."""


class HistoricalReportError(Exception):
    """Base class for expected HTML rendering or storage failures."""


class HistoricalReportRenderError(HistoricalReportError):
    """Raised when a self-contained report cannot be rendered safely."""


class HistoricalReportStorageError(HistoricalReportError):
    """Raised when a report cannot be stored atomically and privately."""


class HistoricalReportAlreadyExistsError(HistoricalReportStorageError):
    """Raised when storing a report would overwrite an existing path."""


class HistoricalReportLockTimeoutError(HistoricalReportStorageError):
    """Raised when an output-path lock cannot be acquired in time."""


class AllocationResearchError(PortfolioAnalysisError):
    """Base class for expected allocation-research calculation failures."""


class InvalidAllocationTargetError(AllocationResearchError):
    """Raised when an allocation target violates its domain invariants."""


class InvalidAllocationBacktestConfigError(AllocationResearchError):
    """Raised when an allocation backtest setting is invalid."""


class InvalidAlignedPricePanelError(AllocationResearchError):
    """Raised when an aligned open/close panel violates its invariants."""


class InvalidAllocationPolicyInputError(AllocationResearchError):
    """Raised when a policy input exposes inconsistent or future observations."""


class InvalidAllocationRebalanceError(AllocationResearchError):
    """Raised when one rebalance record violates accounting invariants."""


class InvalidAllocationBacktestResultError(AllocationResearchError):
    """Raised when an allocation result violates dimensions or value invariants."""


class InvalidAllocationResearchTrialError(AllocationResearchError):
    """Raised when a persisted research trial is internally inconsistent."""


class EmptyAllocationUniverseError(AllocationResearchError):
    """Raised when no active histories were supplied for allocation research."""


class DuplicateAllocationStockCodeError(AllocationResearchError):
    """Raised when allocation input repeats a stock code."""

    def __init__(self, stock_code: str) -> None:
        self.stock_code = stock_code
        super().__init__(f"자산배분 입력에 종목코드 {stock_code}가 중복되었습니다.")


class EmptyAllocationStockHistoryError(AllocationResearchError):
    """Raised when one allocation input history has no bars."""

    def __init__(self, stock_code: str) -> None:
        self.stock_code = stock_code
        super().__init__(f"종목코드 {stock_code}의 자산배분용 일별 시세가 비어 있습니다.")


class AllocationStockCodeMismatchError(AllocationResearchError):
    """Raised when a bar does not belong to its universe stock."""

    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"자산배분 일별 시세 종목코드가 일치하지 않습니다: 예상 {expected}, 실제 {actual}."
        )


class DuplicateAllocationBarDateError(AllocationResearchError):
    """Raised when one allocation history repeats a trade date."""

    def __init__(self, stock_code: str) -> None:
        self.stock_code = stock_code
        super().__init__(f"종목코드 {stock_code}의 자산배분 일별 시세에 중복 거래일이 있습니다.")


class UnsortedAllocationBarsError(AllocationResearchError):
    """Raised when allocation bars are not strictly oldest-first."""

    def __init__(self, stock_code: str) -> None:
        self.stock_code = stock_code
        super().__init__(
            f"종목코드 {stock_code}의 자산배분 일별 시세는 엄격한 오름차순이어야 합니다."
        )


class InsufficientAllocationObservationsError(AllocationResearchError):
    """Raised when common prices cannot support training and evaluation."""

    def __init__(self, actual: int, required: int) -> None:
        self.actual = actual
        self.required = required
        super().__init__(
            f"공통 거래일 가격 관측치가 부족합니다: {actual}개 (최소 {required}개 필요)."
        )


class AllocationZeroVolatilityError(AllocationResearchError):
    """Raised when inverse-volatility weights cannot be calculated."""

    def __init__(self, stock_code: str) -> None:
        self.stock_code = stock_code
        super().__init__(f"종목코드 {stock_code}의 표본변동성이 0이거나 계산 불가능합니다.")


class AllocationSelfFinancingError(AllocationResearchError):
    """Raised when transaction costs cannot be reconciled without external cash."""


class AllocationTrialStorageError(Exception):
    """Base class for expected allocation trial registry failures."""


class AllocationTrialAlreadyExistsError(AllocationTrialStorageError):
    """Raised when a trial file would be overwritten."""


class AllocationTrialLockTimeoutError(AllocationTrialStorageError):
    """Raised when an output-specific trial lock cannot be acquired."""


class RiskModelError(PortfolioAnalysisError):
    """Base class for expected dynamic-risk-model calculation failures."""


class RiskModelConfigurationError(RiskModelError):
    """Raised when fixed risk-model settings violate their invariants."""


class RiskModelAsOfDateNotFoundError(RiskModelError):
    """Raised when an estimate date is absent from the aligned return matrix."""

    def __init__(self, as_of_date: object) -> None:
        self.as_of_date = as_of_date
        super().__init__(f"위험모형 기준일 {as_of_date}이 공통 수익률 날짜에 없습니다.")


class InsufficientRiskHistoryError(RiskModelError):
    """Raised when a trailing estimate window is shorter than configured."""

    def __init__(self, actual: int, required: int, *, as_of_date: object | None = None) -> None:
        self.actual = actual
        self.required = required
        self.as_of_date = as_of_date
        suffix = "" if as_of_date is None else f" · 기준일 {as_of_date}"
        super().__init__(
            f"위험모형 수익률 관측치가 부족합니다: {actual}개 (최소 {required}개 필요){suffix}."
        )


class InsufficientCorrelationHistoryError(RiskModelError):
    """Raised when IEWMA has too few causal standardized observations."""

    def __init__(self, actual: int, required: int, *, as_of_date: object | None = None) -> None:
        self.actual = actual
        self.required = required
        self.as_of_date = as_of_date
        suffix = "" if as_of_date is None else f" · 기준일 {as_of_date}"
        super().__init__(
            f"IEWMA 상관관계 관측치가 부족합니다: {actual}개 (최소 {required}개 필요){suffix}."
        )


class InsufficientDownsideHistoryError(RiskModelError):
    """Raised when the deterministic downside subset is too small."""

    def __init__(self, actual: int, required: int, *, as_of_date: object | None = None) -> None:
        self.actual = actual
        self.required = required
        self.as_of_date = as_of_date
        suffix = "" if as_of_date is None else f" · 기준일 {as_of_date}"
        super().__init__(
            f"하방 스트레스 선택 관측치가 부족합니다: {actual}개 (최소 {required}개 필요){suffix}."
        )


class DegenerateRiskSeriesError(RiskModelError):
    """Raised when one stock has zero variance and no risk can be estimated."""

    def __init__(self, stock_code: str) -> None:
        self.stock_code = stock_code
        super().__init__(
            f"종목코드 {stock_code}의 수익률 분산이 0이어서 위험을 추정할 수 없습니다."
        )


class RiskModelNumericalError(RiskModelError):
    """Raised when finite numerical estimation cannot be completed safely."""


class MateriallyIndefiniteCovarianceError(RiskModelNumericalError):
    """Raised when a matrix has a negative eigenvalue beyond numerical noise."""

    def __init__(self, minimum_eigenvalue: float, tolerance: float) -> None:
        self.minimum_eigenvalue = minimum_eigenvalue
        self.tolerance = tolerance
        super().__init__(
            "공분산 행렬에 수치 허용오차를 넘는 음의 고윳값이 있습니다: "
            f"최솟값 {minimum_eigenvalue:.6g}, 허용오차 {tolerance:.6g}."
        )


class RiskModelQualityError(RiskModelNumericalError):
    """Raised when numerical repair would exceed the configured quality ceiling."""


class RiskModelTrialStorageError(Exception):
    """Base class for expected dynamic-risk-model trial storage failures."""


class RiskModelTrialAlreadyExistsError(RiskModelTrialStorageError):
    """Raised when a risk-model trial file would be overwritten."""


class RiskModelTrialLockTimeoutError(RiskModelTrialStorageError):
    """Raised when a risk-model trial lock cannot be acquired."""


class RiskModelTrialCorruptionError(RiskModelTrialStorageError):
    """Raised when a stored risk-model trial is malformed or inconsistent."""


class ConstrainedErcResearchError(PortfolioAnalysisError):
    """Base class for expected constrained-ERC research failures."""


class InvalidConstrainedErcDomainError(ConstrainedErcResearchError):
    """Raised when an immutable constrained-ERC value violates its contract."""


class ConstrainedErcInfeasibleBoundsError(ConstrainedErcResearchError):
    """Raised when per-asset bounds cannot contain a fully invested sleeve."""


class ConstrainedErcInvalidCovarianceError(ConstrainedErcResearchError):
    """Raised when covariance dimensions, order, or numerical quality are invalid."""


class ConstrainedErcDegenerateVarianceError(ConstrainedErcResearchError):
    """Raised when a feasible candidate has no positive portfolio variance."""


class ConstrainedErcLambdaBracketError(ConstrainedErcResearchError):
    """Raised when the positive lambda search cannot bracket weight sum one."""


class ConstrainedErcCcdConvergenceError(ConstrainedErcResearchError):
    """Raised when deterministic cyclical coordinate descent does not converge."""


class ConstrainedErcBisectionConvergenceError(ConstrainedErcResearchError):
    """Raised when outer lambda bisection does not reach the fixed sum tolerance."""


class ConstrainedErcReconciliationError(ConstrainedErcResearchError):
    """Raised when float weights cannot be reconciled to exact Decimal weights."""


class ConstrainedErcKktValidationError(ConstrainedErcResearchError):
    """Raised when a candidate fails feasibility, Euler, or KKT validation."""


class ConstrainedErcScenarioScheduleError(ConstrainedErcResearchError):
    """Raised when a covariance scenario does not match the shared signal schedule."""


class ConstrainedErcMissingRiskSnapshotError(ConstrainedErcScenarioScheduleError):
    """Raised when an exact signal-date risk snapshot is absent."""


class ConstrainedErcDuplicateRiskSnapshotError(ConstrainedErcScenarioScheduleError):
    """Raised when more than one risk snapshot claims the same signal date."""


class ConstrainedErcTrialStorageError(Exception):
    """Base class for constrained-ERC trial serialization and storage failures."""


class ConstrainedErcTrialAlreadyExistsError(ConstrainedErcTrialStorageError):
    """Raised rather than overwriting an existing constrained-ERC trial."""


class ConstrainedErcTrialLockTimeoutError(ConstrainedErcTrialStorageError):
    """Raised when a constrained-ERC output lock cannot be acquired."""


class ConstrainedErcTrialSerializationError(ConstrainedErcTrialStorageError):
    """Raised when a constrained-ERC trial cannot be safely serialized."""


__all__ = [
    "AllocationResearchError",
    "AllocationSelfFinancingError",
    "AllocationStockCodeMismatchError",
    "AllocationTrialAlreadyExistsError",
    "AllocationTrialLockTimeoutError",
    "AllocationTrialStorageError",
    "AllocationZeroVolatilityError",
    "ConstrainedErcBisectionConvergenceError",
    "ConstrainedErcCcdConvergenceError",
    "ConstrainedErcDegenerateVarianceError",
    "ConstrainedErcDuplicateRiskSnapshotError",
    "ConstrainedErcInfeasibleBoundsError",
    "ConstrainedErcInvalidCovarianceError",
    "ConstrainedErcKktValidationError",
    "ConstrainedErcLambdaBracketError",
    "ConstrainedErcMissingRiskSnapshotError",
    "ConstrainedErcReconciliationError",
    "ConstrainedErcResearchError",
    "ConstrainedErcScenarioScheduleError",
    "ConstrainedErcTrialAlreadyExistsError",
    "ConstrainedErcTrialLockTimeoutError",
    "ConstrainedErcTrialSerializationError",
    "ConstrainedErcTrialStorageError",
    "DegenerateRiskSeriesError",
    "DuplicateAllocationBarDateError",
    "DuplicateAllocationStockCodeError",
    "DuplicateDailyBarDateError",
    "DuplicateReturnStockCodeError",
    "EmptyAllocationStockHistoryError",
    "EmptyAllocationUniverseError",
    "EmptyReturnUniverseError",
    "EmptyStockHistoryError",
    "HistoricalReportAlreadyExistsError",
    "HistoricalReportError",
    "HistoricalReportLockTimeoutError",
    "HistoricalReportRenderError",
    "HistoricalReportStockOrderError",
    "HistoricalReportStorageError",
    "InsufficientAllocationObservationsError",
    "InsufficientCommonObservationsError",
    "InsufficientCorrelationHistoryError",
    "InsufficientDownsideHistoryError",
    "InsufficientPerformanceObservationsError",
    "InsufficientRiskHistoryError",
    "InsufficientStockObservationsError",
    "InvalidAlignedPricePanelError",
    "InvalidAlignedReturnMatrixError",
    "InvalidAllocationBacktestConfigError",
    "InvalidAllocationBacktestResultError",
    "InvalidAllocationPolicyInputError",
    "InvalidAllocationRebalanceError",
    "InvalidAllocationResearchTrialError",
    "InvalidAllocationTargetError",
    "InvalidConstrainedErcDomainError",
    "InvalidHistoricalUniverseAnalysisError",
    "InvalidMinimumObservationsError",
    "InvalidPerformanceMetricsError",
    "InvalidPerformanceReturnError",
    "MateriallyIndefiniteCovarianceError",
    "PortfolioAnalysisError",
    "ReturnStockCodeMismatchError",
    "RiskModelAsOfDateNotFoundError",
    "RiskModelConfigurationError",
    "RiskModelError",
    "RiskModelNumericalError",
    "RiskModelQualityError",
    "RiskModelTrialAlreadyExistsError",
    "RiskModelTrialCorruptionError",
    "RiskModelTrialLockTimeoutError",
    "RiskModelTrialStorageError",
    "UnsortedAllocationBarsError",
    "UnsortedDailyBarsError",
]
