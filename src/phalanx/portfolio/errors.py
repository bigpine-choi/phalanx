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


__all__ = [
    "DuplicateDailyBarDateError",
    "DuplicateReturnStockCodeError",
    "EmptyReturnUniverseError",
    "EmptyStockHistoryError",
    "HistoricalReportAlreadyExistsError",
    "HistoricalReportError",
    "HistoricalReportLockTimeoutError",
    "HistoricalReportRenderError",
    "HistoricalReportStockOrderError",
    "HistoricalReportStorageError",
    "InsufficientCommonObservationsError",
    "InsufficientPerformanceObservationsError",
    "InsufficientStockObservationsError",
    "InvalidAlignedReturnMatrixError",
    "InvalidHistoricalUniverseAnalysisError",
    "InvalidMinimumObservationsError",
    "InvalidPerformanceMetricsError",
    "InvalidPerformanceReturnError",
    "PortfolioAnalysisError",
    "ReturnStockCodeMismatchError",
    "UnsortedDailyBarsError",
]
