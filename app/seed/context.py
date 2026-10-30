from dataclasses import dataclass, field

from app.models import Merchant, Supplier


@dataclass
class SeedContext:
    ramesh: Merchant | None = None
    neha: Merchant | None = None
    vikas: Merchant | None = None
    retailers: list[Merchant] = field(default_factory=list)
    ramesh_suppliers: dict[str, Supplier] = field(default_factory=dict)
    neha_suppliers: dict[str, Supplier] = field(default_factory=dict)
    retailer_sharma: dict[int, Supplier] = field(default_factory=dict)  # retailer merchant id -> its Sharma row
