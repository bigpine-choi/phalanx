"""Immutable account-overview results shared by CLI and future GUI callers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from phalanx.domain.account import AccountSnapshot, DecimalValue


class _OverviewModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OverviewPosition(_OverviewModel):
    stock_code: str
    product_name: str
    holding_quantity: DecimalValue
    sellable_quantity: DecimalValue
    broker_evaluation_amount: DecimalValue
    observed_price: DecimalValue
    observed_evaluation_amount: DecimalValue
    observed_stock_weight: DecimalValue
    price_request_started_at: datetime
    price_received_at: datetime


class OverviewTotals(_OverviewModel):
    broker_positions_evaluation_amount: DecimalValue
    broker_summary_minus_positions: DecimalValue
    broker_other_assets_and_settlement_adjustments: DecimalValue
    broker_liabilities_and_deductions: DecimalValue
    observed_positions_evaluation_amount: DecimalValue
    observed_minus_broker_positions: DecimalValue


class AccountOverview(_OverviewModel):
    """One complete observation; broker NAV is preserved inside ``snapshot``.

    Prices value only the recorded positive holdings. They neither refresh cash
    and liabilities nor establish a simultaneously observed account NAV.
    """

    schema_version: Literal["1"] = "1"
    report_type: Literal["account_overview"] = "account_overview"
    snapshot: AccountSnapshot
    price_market: Literal["KRX"] = "KRX"
    positions: tuple[OverviewPosition, ...]
    totals: OverviewTotals
    observation_started_at: datetime
    observation_completed_at: datetime
    observation_span_microseconds: int
    max_observation_span_seconds: int
    weight_basis: Literal["observed_positive_holdings_value"] = "observed_positive_holdings_value"
    price_time_basis: Literal["client_request_and_response"] = "client_request_and_response"
    decimal_precision: Literal[50] = 50
    decimal_rounding: Literal["ROUND_HALF_EVEN"] = "ROUND_HALF_EVEN"
