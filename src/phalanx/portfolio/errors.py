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


__all__ = [
    "AllocationResearchError",
    "AllocationSelfFinancingError",
    "AllocationStockCodeMismatchError",
    "AllocationTrialAlreadyExistsError",
    "AllocationTrialLockTimeoutError",
    "AllocationTrialStorageError",
    "AllocationZeroVolatilityError",
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
    "InsufficientPerformanceObservationsError",
    "InsufficientStockObservationsError",
    "InvalidAlignedPricePanelError",
    "InvalidAlignedReturnMatrixError",
    "InvalidAllocationBacktestConfigError",
    "InvalidAllocationBacktestResultError",
    "InvalidAllocationPolicyInputError",
    "InvalidAllocationRebalanceError",
    "InvalidAllocationResearchTrialError",
    "InvalidAllocationTargetError",
    "InvalidHistoricalUniverseAnalysisError",
    "InvalidMinimumObservationsError",
    "InvalidPerformanceMetricsError",
    "InvalidPerformanceReturnError",
    "PortfolioAnalysisError",
    "ReturnStockCodeMismatchError",
    "UnsortedAllocationBarsError",
    "UnsortedDailyBarsError",
]
