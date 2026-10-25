import unittest
from datetime import datetime, timezone

from leadfinder import checks, text as t
from leadfinder.sources import Page
from tests.helpers import conf


class TextTests(unittest.TestCase):
    def test_names_match_without_legal_suffix_accents_or_punctuation(self):
        self.assertEqual(t.name_key("Gâteau House Co., Ltd."), t.name_key("gateau house"))
        self.assertNotEqual(t.name_key("Gateau House"), t.name_key("Gateau Home"))

    def test_domains_handles_and_phones(self):
        self.assertEqual(t.domain("https://www.nookbakery.example/menu"), "nookbakery.example")
        self.assertEqual(t.handle("instagram.com/nook.bakes"), "nook.bakes")
        self.assertEqual(t.handle("Line OA @nookbkk"), "nookbkk")
        self.assertEqual(t.phone_key("+66 81 234 5678", "66"), t.phone_key("081-234-5678", "66"))

    def test_quote_must_be_on_the_page_ignoring_markdown_and_spacing(self):
        page = "## New openings\n- **Nook Bakery** in Ari bakes vegan croissants every morning."
        self.assertTrue(t.quote_on_page("Nook Bakery in Ari bakes vegan croissants every morning.", page))
        self.assertFalse(t.quote_on_page("Nook Bakery sells the best croissants in town.", page))
        self.assertTrue(t.quote_names("Nook Bakery in Ari bakes vegan croissants", "Nook Bakery (Nook Foods Ltd)"))
        self.assertFalse(t.quote_names("A bakery in Ari bakes vegan croissants", "Nook Bakery"))

    def test_thai_marks_are_kept(self):
        self.assertIn("ร้านเบเกอรี่", t.fold("ร้านเบเกอรี่"))


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.index = checks.Index(
            [{"id": 1, "name": "Fernleaf Cafe", "status": "customer", "website": "https://fernleaf.example", "phone": "081 111 2222"},
             {"id": 2, "name": "Sunny Loaf", "status": "prospect", "instagram": "@sunnyloaf"}],
            [{"account_id": 2, "kind": "name", "value": "Sunny Loaf Bakehouse"}], "66")

    def test_known_businesses_are_held_back_by_any_matching_fact(self):
        self.assertEqual(self.index.exact({"name": "Fernleaf Café Co., Ltd."})[1], "same name")
        self.assertEqual(self.index.exact({"name": "Totally New", "website": "www.fernleaf.example/menu"})[1], "same website")
        self.assertEqual(self.index.exact({"name": "x", "phone": "+66 81 111 2222"})[1], "same phone")
        self.assertEqual(self.index.exact({"name": "x", "instagram": "instagram.com/sunnyloaf"})[1], "same Instagram")
        self.assertEqual(self.index.exact({"name": "Sunny Loaf Bakehouse"})[0]["id"], 2)
        self.assertIsNone(self.index.exact({"name": "Moon Crumb"}))

    def test_look_alikes_are_flagged_not_held(self):
        account, why = self.index.look_alike({"name": "Fern Table"})
        self.assertEqual(account["id"], 1)
        self.assertIn("fern", why)
        self.assertIsNone(self.index.look_alike({"name": "Moon Crumb"}))

    def test_directories_social_and_jobs_are_not_sources(self):
        self.assertFalse(checks.is_source("https://www.instagram.com/nook"))
        self.assertFalse(checks.is_source("https://www.tripadvisor.com/x"))
        self.assertFalse(checks.is_source("https://news.example/jobs/baker"))
        self.assertTrue(checks.is_source("https://guide.example/best-bakeries"))

    def test_results_must_be_about_the_city_searched(self):
        c = conf()
        bkk = c.place_for("new vegan bakery Bangkok")
        self.assertTrue(checks.names_place("New dessert cafés in Bangkok", "x https://mag.example/a", bkk, c.other_places))
        self.assertFalse(checks.names_place("Bangkok street food vibes", "Noodle Bar https://www.noodlenyc.example/", bkk, c.other_places))
        self.assertFalse(checks.names_place("Bangkok Grillin'", "NYC's New Restaurant Openings https://x.example", bkk, c.other_places))
        self.assertFalse(checks.names_place("Best bakeries", "Best bakeries https://y.example", bkk, c.other_places))

    def test_open_check(self):
        c, now = conf(), datetime(2026, 10, 20, tzinfo=timezone.utc)
        loads = lambda url: (True, Page(url, "Welcome to Nook Bakery"))
        down = lambda url: (False, None)
        self.assertFalse(checks.open_check({"name": "Nook"}, "Nook has closed its doors.", None, c, loads, now=now)[0])
        self.assertTrue(checks.open_check({"name": "Nook", "website": "nook.example"}, "Nook bakes.", None, c, loads, now=now)[0])
        self.assertFalse(checks.open_check({"name": "Nook", "website": "nook.example"}, "Nook bakes.", None, c, down, now=now)[0])
        self.assertTrue(checks.open_check({"name": "Nook"}, "Nook bakes.", "2026-03-01", c, down, now=now)[0])
        self.assertFalse(checks.open_check({"name": "Nook"}, "Nook bakes.", "2023-01-01", c, down, now=now)[0])
        self.assertFalse(checks.open_check({"name": "Nook"}, "Nook bakes.", None, c, down, now=now)[0])

    def test_closed_means_this_business_not_its_neighbour(self):
        guide = "Nook Bakery in Ari bakes croissants.\nMoon Crumb has closed its doors."
        self.assertFalse(checks.says_closed(guide, "Nook Bakery"))
        self.assertTrue(checks.says_closed(guide, "Moon Crumb"))
        self.assertTrue(checks.says_closed("We loved Nook Bakery. It has closed for good.", "Nook Bakery"))
        self.assertTrue(checks.says_closed("Sorry, we are permanently closed.", "Nook Bakery"))  # its own site

    def test_sources_marked_closed_twice_are_dropped(self):
        self.assertEqual(checks.stale_sources({"https://old.example": 2, "https://ok.example": 1}), {"https://old.example"})


if __name__ == "__main__":
    unittest.main()
