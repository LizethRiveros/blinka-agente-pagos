import os
import sys
import unittest
from functools import partial

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blinka import runner
from blinka.engine import BLOCK, ESCALATE, PAY, evaluate, new_state, norm_inv
from blinka.extract import extract_document, extract_regex, parse_amount, parse_date, read_document

# Las pruebas no deben depender de internet ni de una clave: solo el lector por reglas.
rules_only = partial(extract_document, use_llm=False)


def ex(**kw):
    base = dict(beneficiary="CloudHost Inc", amount=480.0, currency="USD", due_date="2026-10-30",
                invoice_number="CH-1")
    base.update(kw)
    return base


class Parsing(unittest.TestCase):
    def test_amount_formats(self):
        for raw, want in [("4.800.000", 4800000), ("36,000.00", 36000), ("1.250,50", 1250.5),
                          ("480.00", 480), ("36 000,00", 36000), ("2,000.01", 2000.01)]:
            self.assertEqual(parse_amount(raw), want, raw)

    def test_dates(self):
        self.assertEqual(parse_date("25/10/2026"), "2026-10-25")
        self.assertEqual(parse_date("5 de noviembre de 2026"), "2026-11-05")
        self.assertIsNone(parse_date("31/02/2026"))

    def test_dollar_sign_alone_is_not_a_currency(self):
        data, _ = extract_regex("Proveedor: X\nTotal: $ 100.00\nVence: 2026-10-30")
        self.assertIsNone(data["currency"])

    def test_contradictory_totals_are_flagged(self):
        _, amb = extract_regex("Total a pagar: USD 900.00\n\nTotal a pagar: USD 1,400.00")
        self.assertEqual(amb, ["amount"])

    def test_invoice_number_normalization(self):
        self.assertEqual(norm_inv("px 0231"), norm_inv("PX-231"))


class Batch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = runner.load_rules()
        cls.batch = runner.run_batch(cls.rules, extractor=rules_only)
        cls.exp = runner.load_expected()

    def test_every_readable_decision_matches_expected(self):
        for r in self.batch["results"]:
            if self.exp[r["file"]]["needs_claude"]:
                continue
            self.assertEqual(r["decision"], self.exp[r["file"]]["expected"], r["file"] + ": " + r["reason"])

    def test_never_pays_what_it_should_not(self):
        for r in self.batch["results"]:
            if r["decision"] == PAY:
                self.assertEqual(self.exp[r["file"]]["expected"], PAY, r["file"])
                self.assertTrue(all(c["ok"] for c in r["checks"]), r["file"])

    def test_unreadable_photos_escalate(self):
        for r in self.batch["results"]:
            if r["file"].endswith(".png"):
                self.assertEqual(r["decision"], ESCALATE)

    def test_pdfs_are_read_without_extra_libraries(self):
        pdfs = [r for r in self.batch["results"] if r["file"].endswith(".pdf")]
        self.assertGreaterEqual(len(pdfs), 4)
        for r in pdfs:
            self.assertEqual(r["reader"]["readers"], ["reglas"])
            self.assertIsNotNone(r["extracted"]["amount"], r["file"])

    def test_budget_never_exceeded(self):
        self.assertLessEqual(self.batch["state"]["spent_usd"], self.rules["period_budget_usd"])

    def test_every_decision_is_explained(self):
        self.assertTrue(all(r["reason"] for r in self.batch["results"]))

    def test_human_approval_only_for_escalated(self):
        paid = next(r for r in self.batch["results"] if r["decision"] == PAY)
        with self.assertRaises(ValueError):
            runner.review(self.batch, paid["file"], "approve")

    def test_all_document_types_are_read(self):
        for name in ("01_pixel_octubre.txt", "02_cloudhost_octubre.pdf", "44_foto_contable.png"):
            doc = read_document(os.path.join(runner.DATA, "invoices", name))
            self.assertIn(doc["kind"], ("text", "pdf", "image"))


class Rules(unittest.TestCase):
    def setUp(self):
        self.rules = runner.load_rules()

    def decide(self, e, meta=None, state=None):
        return evaluate(e, self.rules, state or new_state(), meta)["decision"]

    def test_unknown_currency_escalates(self):
        self.assertEqual(self.decide(ex(currency="JPY")), ESCALATE)

    def test_missing_fields_never_pay(self):
        self.assertEqual(self.decide({}), ESCALATE)

    def test_hard_limit_blocks_even_for_allowed_beneficiary(self):
        self.assertEqual(self.decide(ex(amount=9000)), BLOCK)

    def test_threshold_boundary(self):
        a = dict(beneficiary="Analytics Studio LLC", currency="USD", due_date="2026-10-30")
        self.assertEqual(self.decide(ex(amount=2000.0, **a)), PAY)
        self.assertEqual(self.decide(ex(amount=2000.01, **a)), ESCALATE)

    def test_tolerance_boundary(self):
        a = dict(beneficiary="Estudio Pixel SAS", currency="COP", due_date="2026-10-30")
        self.assertEqual(self.decide(ex(amount=4896000.0, **a)), PAY)
        self.assertEqual(self.decide(ex(amount=4897000.0, **a)), ESCALATE)

    def test_tolerance_boundary_survives_float_rounding(self):
        # (489.6 - 480) / 480 da 0.02000000000000005 en coma flotante, pero es +2,00% exacto
        self.assertEqual(self.decide(ex(amount=489.6)), PAY)

    def test_budget_exact_fit_then_overflow(self):
        self.rules["period_budget_usd"] = 960
        st = new_state()
        self.assertEqual(self.decide(ex(invoice_number="A-1"), state=st), PAY)
        self.assertEqual(self.decide(ex(invoice_number="A-2"), state=st), PAY)
        self.assertEqual(self.decide(ex(invoice_number="A-3"), state=st), ESCALATE)
        self.assertEqual(st["spent_usd"], 960)

    def test_same_number_other_vendor_is_not_duplicate(self):
        st = new_state()
        self.assertEqual(self.decide(ex(invoice_number="X-100"), state=st), PAY)
        other = ex(beneficiary="Contable Andes SAC", amount=1500.0, currency="PEN", invoice_number="X-100")
        self.assertEqual(self.decide(other, state=st), PAY)

    def test_duplicate_with_different_number_format_is_blocked(self):
        st = new_state()
        self.assertEqual(self.decide(ex(invoice_number="CH-0088"), state=st), PAY)
        self.assertEqual(self.decide(ex(invoice_number="ch 88"), state=st), BLOCK)

    def test_two_readers_disagreeing_never_pay(self):
        meta = {"conflicts": ["amount: reglas=480.0, Claude=4800.0"], "ambiguous": [], "error": None}
        self.assertEqual(self.decide(ex(), meta), ESCALATE)

    def test_reader_error_never_pays(self):
        self.assertEqual(self.decide(ex(), {"error": "Claude no pudo leer (HTTPError)"}), ESCALATE)


class Rails(unittest.TestCase):
    def setUp(self):
        self.rules = runner.load_rules()

    def decide(self, e):
        return evaluate(e, self.rules, new_state())["decision"]

    def test_allowed_rail_pays(self):
        self.assertEqual(self.decide(ex(payment_rail="ACH")), PAY)
        self.assertEqual(self.decide(ex(payment_rail="swift")), PAY)

    def test_rail_not_allowed_for_that_vendor_escalates(self):
        self.assertEqual(self.decide(ex(payment_rail="SPEI")), ESCALATE)

    def test_stablecoin_request_escalates(self):
        for raw in ("USDC on Base", "Stablecoin (USDT)", "usdc"):
            self.assertEqual(self.decide(ex(payment_rail=raw)), ESCALATE, raw)

    def test_unknown_rail_never_pays(self):
        self.assertEqual(self.decide(ex(payment_rail="trueque")), ESCALATE)

    def test_no_rail_in_invoice_keeps_old_behavior(self):
        self.assertEqual(self.decide(ex()), PAY)

    def test_rail_alias_matches(self):
        from blinka.engine import norm_rail
        self.assertEqual(norm_rail("Bre-B"), norm_rail("BRE B"))

    def test_rail_is_read_from_text(self):
        d, _ = extract_regex("Proveedor: CloudHost Inc\nTotal a pagar: USD 480.00\nRuta de pago: SPEI\n")
        self.assertEqual(d["payment_rail"], "SPEI")


class CsvExport(unittest.TestCase):
    def test_csv_has_one_row_per_invoice_and_neutralizes_formulas(self):
        b = runner.run_batch(runner.load_rules(), extractor=rules_only)
        text = runner.export_csv(b)
        self.assertEqual(len(text.strip().splitlines()), len(b["results"]) + 1)
        b["results"][0]["extracted"]["beneficiary"] = "=HYPERLINK(1)"
        self.assertIn("'=HYPERLINK(1)", runner.export_csv(b))

    def test_new_currencies_are_configured(self):
        for c in ("BRL", "CLP", "BOB", "CRC", "ZAR"):
            self.assertIn(c, runner.load_rules()["fx_to_usd"])


if __name__ == "__main__":
    unittest.main()
