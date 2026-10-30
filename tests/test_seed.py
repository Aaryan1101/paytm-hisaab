from sqlmodel import select

from app.engine import gstin
from app.models import Alert, CollectionIn, CreditNote, ImsEntry, InvoiceRow, Merchant, Supplier
from app.seed.loader import reset_tables, seed_all


def test_counts(seeded):
    s, ctx = seeded
    assert len(s.exec(select(Merchant)).all()) == 42  # Ramesh, Neha, Vikas + 39 retailers
    assert len(ctx.ramesh_suppliers) == 12 and len(ctx.neha_suppliers) == 25
    assert len(ctx.retailers) == 40
    assert len(s.exec(select(InvoiceRow)).all()) > 180


def test_all_supplier_gstins_valid(seeded):
    s, _ = seeded
    assert all(gstin.is_valid(x.gstin) for x in s.exec(select(Supplier)).all())


def test_neha_has_cancelled_and_igst_suppliers(seeded):
    _, ctx = seeded
    assert ctx.neha_suppliers["Kanpur Plastics"].gstin_status == "cancelled"
    out_of_state = [x for x in ctx.neha_suppliers.values() if x.gstin[:2] != "09"]
    assert len(out_of_state) == 2


def test_sharma_is_linked_to_vikas(seeded):
    _, ctx = seeded
    assert ctx.ramesh_suppliers["Sharma Traders"].linked_merchant_id == ctx.vikas.id


def test_invoice_maths_is_consistent(seeded):
    s, _ = seeded
    for inv in s.exec(select(InvoiceRow).limit(80)).all():
        assert abs(inv.taxable_total + inv.tax_total - inv.grand_total) <= 1.0


def test_ramesh_collections_cover_history(seeded):
    s, ctx = seeded
    rows = s.exec(select(CollectionIn).where(CollectionIn.merchant_id == ctx.ramesh.id)).all()
    assert len(rows) >= 90 and all(8_000 <= r.amount <= 25_000 for r in rows)


def test_ims_entries_and_planted_alerts_exist(seeded):
    s, ctx = seeded
    assert len(s.exec(select(ImsEntry).where(ImsEntry.merchant_id == ctx.neha.id)).all()) > 20
    assert s.exec(select(CreditNote).where(CreditNote.merchant_id == ctx.ramesh.id)).first().amount == 2_300
    types = {a.type for a in s.exec(select(Alert).where(Alert.merchant_id == ctx.ramesh.id)).all()}
    assert {"missing_credit_note", "confirm_payee"} <= types


def test_seed_is_deterministic(seeded):
    s, ctx = seeded
    first = sorted(i.grand_total for i in s.exec(select(InvoiceRow)).all())
    reset_tables(s)
    seed_all(s)
    assert sorted(i.grand_total for i in s.exec(select(InvoiceRow)).all()) == first


def test_reset_restores_after_mutation(seeded):
    s, ctx = seeded
    s.add(Alert(merchant_id=ctx.ramesh.id, type="x", severity="info", message_en="x", message_hi="x"))
    s.flush()
    reset_tables(s)
    seed_all(s)
    assert not s.exec(select(Alert).where(Alert.type == "x")).all()
