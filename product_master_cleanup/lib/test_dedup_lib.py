import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dedup_lib import (base_name, cluster, extract_specs, normalise,  # noqa: E402
                       similarity, spec_key)


class NormaliseTests(unittest.TestCase):
    def test_arabic_digits_and_words(self):
        self.assertEqual(normalise("كوع ٩٠ درجة ٢ انش"), "كوع 90deg 2in")

    def test_persian_digits(self):
        self.assertIn("18mm", normalise("لوح ۱۸ mm"))

    def test_inch_mark_and_degree(self):
        self.assertEqual(normalise('HP 2" Elbow 90°'), "hp 2in elbow 90deg")

    def test_inch_variants_equal(self):
        forms = ['PPR Elbow 2"', "PPR Elbow 2''", "PPR Elbow 2 inch", "PPR Elbow 2 inches",
                 "PPR Elbow 2 in", "PPR Elbow 2”"]
        self.assertEqual(len({normalise(f) for f in forms}), 1)
        self.assertEqual(normalise(forms[0]), "ppr elbow 2in")

    def test_fractions(self):
        self.assertEqual(normalise('1/2" PPR Elbow'), "0.5in ppr elbow")
        self.assertEqual(normalise('GI Pipe 1-1/2"'), "gi pipe 1.5in")
        self.assertEqual(normalise('GI Pipe 1 1/2"'), "gi pipe 1.5in")
        self.assertEqual(normalise("Socket 3/4 inch"), "socket 0.75in")

    def test_mm_variants(self):
        self.assertEqual(normalise("Pipe 20 m.m"), normalise("Pipe 20mm"))
        self.assertEqual(normalise("Cable 3x2.5 sq.mm"), "cable 3x2.5mm2")
        self.assertEqual(normalise("Cable 3×2.5mm²"), normalise("Cable 3 * 2.5 sqmm"))

    def test_degree_variants(self):
        self.assertEqual(normalise("Elbow 90 degree"), normalise("Elbow 90°"))
        self.assertEqual(normalise("Elbow 45 deg"), "elbow 45deg")

    def test_noise_words_removed(self):
        self.assertEqual(normalise("Original Brand PPR Pipe New"), "ppr pipe")

    def test_custom_noise_list(self):
        self.assertEqual(normalise("Acme PPR Pipe", noise_words=["acme"]), "ppr pipe")
        self.assertEqual(normalise("Original PPR Pipe", noise_words=[]), "original ppr pipe")

    def test_punctuation_and_decimals(self):
        self.assertEqual(normalise("Cable, (2.5mm2)  ; flex."), "cable 2.5mm2 flex")

    def test_voltage_rating(self):
        self.assertIn("0.6-1kv", normalise("Cable 0.6/1 kV"))

    def test_empty(self):
        self.assertEqual(normalise(None), "")
        self.assertEqual(normalise("   "), "")


class SpecTests(unittest.TestCase):
    def test_ppr_pipe(self):
        s = extract_specs("PPR Pipe 20mm PN20")
        self.assertEqual((s["pipe_mm"], s["pn"], s["material"]), ("20", "pn20", "ppr"))

    def test_elbow_inch_angle(self):
        s = extract_specs('HP 2" Elbow 90°')
        self.assertEqual((s["pipe_in"], s["angle"]), ("2", "90"))

    def test_cable_4c_16mm2(self):
        s = extract_specs("Cable 4C x 16mm2 Cu/XLPE/SWA/PVC")
        self.assertEqual((s["cores"], s["cable_mm2"]), ("4", "16"))
        self.assertEqual(s["material"], "copper/pvc")

    def test_cable_core_word_and_3x(self):
        self.assertEqual(extract_specs("Cable 4 core 16 sqmm")["cores"], "4")
        s = extract_specs("Cable 3x2.5mm2")
        self.assertEqual((s["cores"], s["cable_mm2"]), ("3", "2.5"))
        self.assertNotIn("dims", s)

    def test_voltage(self):
        self.assertEqual(extract_specs("Cable 3x4mm2 0.6/1kV")["voltage"], "0.6-1kv")
        self.assertEqual(extract_specs("Transformer 230V")["voltage"], "230v")

    def test_colours(self):
        self.assertEqual(extract_specs("Emulsion Paint White 18L")["colour"], "white")
        self.assertEqual(extract_specs("دهان ابيض 18 لتر")["colour"], "white")
        self.assertEqual(extract_specs("Paint Gray")["colour"], "grey")

    def test_plywood(self):
        s = extract_specs("Marine Plywood 18mm 2440x1220")
        self.assertEqual((s["thickness_mm"], s["dims"]), ("18", "2440x1220"))

    def test_rebar(self):
        self.assertEqual(extract_specs("Steel Bar T16 12m")["rebar"], "16")
        self.assertEqual(extract_specs("Steel Bar T16 12m")["length_m"], "12")
        self.assertEqual(extract_specs("Deformed Bar Y12")["rebar"], "12")
        self.assertEqual(extract_specs("Rebar 12mm")["rebar"], "12")

    def test_materials(self):
        self.assertEqual(extract_specs("Ductile Iron Gate Valve DN100 PN16")["material"], "ductile iron")
        self.assertEqual(extract_specs("uPVC Elbow 4in")["material"], "upvc")
        self.assertEqual(extract_specs("U-PVC Pipe")["material"], "upvc")

    def test_schedule_dn(self):
        s = extract_specs('GI Pipe 1-1/2" Sch 40')
        self.assertEqual((s["pipe_in"], s["schedule"], s["material"]), ("1.5", "sch40", "gi"))
        self.assertEqual(extract_specs("Flange DN50")["pipe_dn"], "50")

    def test_dimensions_and_reducer(self):
        self.assertEqual(extract_specs("Steel Plate 100x50x5mm")["dims"], "100x50x5mm")
        self.assertEqual(extract_specs('Reducer 2" x 1-1/2"')["pipe_in"], "2x1.5")

    def test_conduit_pvc(self):
        s = extract_specs("PVC Conduit 20mm Grey 3m")
        self.assertEqual((s["pipe_mm"], s["colour"], s["length_m"]), ("20", "grey", "3"))


class BaseNameTests(unittest.TestCase):
    def test_example_shared_base(self):
        self.assertEqual(base_name('HP 2" Elbow 90°'), "hp elbow")
        self.assertEqual(base_name('HP 3" Elbow 45°'), "hp elbow")

    def test_cable_base(self):
        self.assertEqual(base_name("Cable 4C x 16mm2 Cu/XLPE/SWA/PVC"), "cable xlpe swa")

    def test_rebar_base(self):
        self.assertEqual(base_name("Steel Bar T16 12m"), "steel bar")

    def test_arabic_base(self):
        self.assertEqual(base_name("كوع ٩٠ درجة ٢ انش"), "كوع")


class MustNotMatchTests(unittest.TestCase):
    PAIRS = [
        ('PPR Elbow 2" 90°', 'PPR Elbow 3" 90°'),
        ('PPR Elbow 2" 90°', 'PPR Elbow 2" 45°'),
        ("PPR Pipe 25mm PN10", "PPR Pipe 25mm PN16"),
        ("Cable 4C x 16mm2 Cu/XLPE", "Cable 3C x 16mm2 Cu/XLPE"),
        ("Cable 4C x 16mm2 Cu/XLPE", "Cable 4C x 25mm2 Cu/XLPE"),
        ("Steel Bar T12 12m", "Steel Bar T16 12m"),
        ("Emulsion Paint White 18L", "Emulsion Paint Blue 18L"),
        ('PPR Socket 1/2"', 'PPR Socket 3/4"'),
        ("Plywood 12mm", "Plywood 18mm"),
        ("كوع ٩٠ درجة ٢ انش", "كوع ٩٠ درجة ٣ انش"),
    ]

    def test_normalised_strings_differ(self):
        for a, b in self.PAIRS:
            with self.subTest(a=a, b=b):
                self.assertNotEqual(normalise(a), normalise(b))

    def test_spec_keys_differ_but_base_same(self):
        for a, b in self.PAIRS[:6]:
            with self.subTest(a=a, b=b):
                self.assertNotEqual(spec_key(a), spec_key(b))


class SimilarityTests(unittest.TestCase):
    def test_identical_and_reordered(self):
        self.assertEqual(similarity("PPR Elbow 2in", 'ppr   elbow 2"'), 100.0)
        self.assertEqual(similarity("PPR Elbow 2in", "2in Elbow PPR"), 100.0)

    def test_unrelated_low(self):
        self.assertLess(similarity("PPR Elbow 2in", "Emulsion Paint White"), 60)

    def test_empty(self):
        self.assertEqual(similarity("", "x"), 0.0)

    def test_typo_high(self):
        self.assertGreater(similarity("Elbow PPR 2in", "Elbo PPR 2in"), 85)


class ClusterTests(unittest.TestCase):
    ITEMS = [
        {"id": 1, "name": 'PPR Elbow 2" 90°', "cat": "fittings"},
        {"id": 2, "name": "ppr elbow 2 inch 90 degree", "cat": "fittings"},
        {"id": 3, "name": 'PPR Elbow 3" 90°', "cat": "fittings"},
        {"id": 4, "name": "PPR Elbow 2in 90deg", "cat": "other"},
        {"id": 5, "name": "Emulsion Paint White", "cat": "paint"},
    ]

    def test_equal_key(self):
        res = cluster(self.ITEMS, key_fn=lambda i: normalise(i["name"]))
        self.assertEqual(sorted(sorted(c.ids) for c in res), [[1, 2, 4]])
        self.assertTrue(all(p[2] == 100.0 for c in res for p in c.pairs))

    def test_fuzzy_within_block(self):
        res = cluster(self.ITEMS, key_fn=lambda i: i["name"], threshold=99,
                      block_fn=lambda i: i["cat"])
        groups = [sorted(c.ids) for c in res]
        self.assertIn([1, 2], groups)
        self.assertNotIn(4, [x for g in groups for x in g])
        self.assertTrue(all(p[2] >= 99 for c in res for p in c.pairs))

    def test_spec_block_keeps_sizes_apart(self):
        res = cluster(self.ITEMS, key_fn=lambda i: base_name(i["name"]), threshold=95,
                      block_fn=lambda i: spec_key(i["name"]))
        self.assertEqual(sorted(sorted(c.ids) for c in res), [[1, 2, 4]])

    def test_transitive_union_and_min_size(self):
        items = [(1, "ppr elbow"), (2, "ppr elbow x"), (3, "ppr elbow x y"), (4, "zzz")]
        res = cluster(items, key_fn=lambda i: i[1], threshold=75)
        self.assertEqual([sorted(c.ids) for c in res], [[1, 2, 3]])
        self.assertEqual(len(cluster(items, key_fn=lambda i: i[1], threshold=75, min_size=1)), 2)


if __name__ == "__main__":
    unittest.main()
