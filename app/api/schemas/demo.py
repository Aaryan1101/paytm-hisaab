from pydantic import BaseModel


class SimulatePaymentIn(BaseModel):
    payer_id: int
    supplier_name: str = "Sharma Traders"
    amount: float = 31_500.0


class SimulatePaymentOut(BaseModel):
    gross: float
    mdr: float
    net: float
    matched: list[dict]
    reliability_before: float | None
    reliability_after: float | None


class SimulateCustomerPaymentIn(BaseModel):
    merchant_id: int
    amount: float = 2_500.0


class JobRunOut(BaseModel):
    sent: list[dict]
