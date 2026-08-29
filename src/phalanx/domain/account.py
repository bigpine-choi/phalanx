"""Immutable, provider-neutral representation of a KIS account snapshot."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)


def _reject_binary_float(value: Any) -> Any:
    if isinstance(value, (bool, float)):
        raise ValueError("decimal values must not be provided as float or bool")
    return value


def _require_finite_decimal(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("decimal values must be finite")
    return value


def _serialize_decimal(value: Decimal) -> str:
    return format(value, "f")


DecimalValue = Annotated[
    Decimal,
    BeforeValidator(_reject_binary_float),
    AfterValidator(_require_finite_decimal),
    PlainSerializer(_serialize_decimal, return_type=str, when_used="json"),
]
NonNegativeDecimal = Annotated[DecimalValue, Field(ge=Decimal("0"))]


class _FrozenDomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AccountPosition(_FrozenDomainModel):
    """One normalized domestic-stock balance row."""

    stock_code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
    product_name: str = Field(min_length=1, max_length=200)
    holding_quantity: NonNegativeDecimal
    sellable_quantity: NonNegativeDecimal
    purchase_amount: NonNegativeDecimal
    evaluation_amount: NonNegativeDecimal
    profit_loss: DecimalValue

    @field_validator("stock_code", "product_name", mode="before")
    @classmethod
    def _strip_required_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @model_validator(mode="after")
    def _require_sellable_quantity_within_holding(self) -> Self:
        if self.sellable_quantity > self.holding_quantity:
            raise ValueError("sellable_quantity must not exceed holding_quantity")
        return self


class AccountSummary(_FrozenDomainModel):
    """Normalized account totals without inferring orderable cash."""

    deposit_total: DecimalValue
    orderable_cash: None = None
    securities_evaluation_amount: NonNegativeDecimal
    purchase_amount_total: NonNegativeDecimal
    evaluation_amount_total: NonNegativeDecimal
    profit_loss_total: DecimalValue
    total_assets: DecimalValue
    net_assets: DecimalValue


class RawEvidenceField(_FrozenDomainModel):
    """One allow-listed raw KIS response field preserved as immutable text."""

    _SENSITIVE_FIELD_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "authorization",
            "appkey",
            "app_key",
            "appsecret",
            "app_secret",
            "access_token",
            "token",
            "account_number",
            "account_no",
            "cano",
            "acnt_prdt_cd",
        }
    )

    name: str = Field(min_length=1, max_length=100)
    value: str | None

    @field_validator("name", mode="before")
    @classmethod
    def _reject_sensitive_field_names(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        normalized = stripped.lower().replace("-", "_")
        if normalized in cls._SENSITIVE_FIELD_NAMES:
            raise ValueError("sensitive fields are not permitted in snapshot evidence")
        return stripped


class RawEvidenceRecord(_FrozenDomainModel):
    """An immutable raw KIS output record."""

    fields: tuple[RawEvidenceField, ...] = ()

    @model_validator(mode="after")
    def _require_unique_field_names(self) -> Self:
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("raw evidence field names must be unique within a record")
        return self


class ApiPageEvidence(_FrozenDomainModel):
    """Sanitized evidence retained for one successfully fetched balance page."""

    received_at: datetime
    http_status: int = Field(ge=100, le=599)
    tr_cont: str
    ctx_area_fk100: str
    ctx_area_nk100: str
    rt_cd: str
    msg_cd: str
    msg1: str
    response_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output1: tuple[RawEvidenceRecord, ...] = ()
    output2: tuple[RawEvidenceRecord, ...] = ()
    placeholder_rows: tuple[RawEvidenceRecord, ...] = ()

    @field_validator("received_at")
    @classmethod
    def _require_timezone_aware_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        return value


class SnapshotEvidence(_FrozenDomainModel):
    """Deeply immutable, sanitized API evidence for a complete snapshot."""

    pages: tuple[ApiPageEvidence, ...] = Field(min_length=1)
    summary_consistency_warnings: tuple[str, ...] = ()


class AccountSnapshot(_FrozenDomainModel):
    """A complete immutable account observation."""

    schema_version: Literal["1"] = "1"
    provider: Literal["korea_investment_securities"] = "korea_investment_securities"
    currency: Literal["KRW"] = "KRW"
    account_number_masked: str = Field(pattern=r"^\d{4}\*{4}-\*{2}$")
    query_started_at: datetime
    query_completed_at: datetime
    summary: AccountSummary
    positions: tuple[AccountPosition, ...] = ()
    zero_quantity_balances: tuple[AccountPosition, ...] = ()
    evidence: SnapshotEvidence

    @field_validator("query_started_at", "query_completed_at")
    @classmethod
    def _require_timezone_aware_query_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("query timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_snapshot_invariants(self) -> Self:
        if self.query_completed_at < self.query_started_at:
            raise ValueError("query_completed_at must not be earlier than query_started_at")

        position_codes: list[str] = []
        for position in self.positions:
            if position.holding_quantity <= 0:
                raise ValueError("positions must contain only positive holding quantities")
            position_codes.append(position.stock_code)

        zero_quantity_codes: list[str] = []
        for position in self.zero_quantity_balances:
            if position.holding_quantity != 0:
                raise ValueError("zero_quantity_balances must contain only zero holding quantities")
            zero_quantity_codes.append(position.stock_code)

        if len(position_codes) != len(set(position_codes)):
            raise ValueError("positions must not contain duplicate stock codes")
        if len(zero_quantity_codes) != len(set(zero_quantity_codes)):
            raise ValueError("zero_quantity_balances must not contain duplicate stock codes")
        if set(position_codes) & set(zero_quantity_codes):
            raise ValueError("a stock code must not appear in both balance collections")

        return self
