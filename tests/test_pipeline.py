import unittest
from datetime import datetime, timezone

from leadfinder import decisions, discover, owners, telegram
from leadfinder.sources import Page
from tests.helpers import FakeAI, FakeProvider, biz, conf, sources, store

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)
GUIDE = "https://guide.example/new-vegan-bakeries-bangkok"
GUIDE_TEXT = (
    "# Bangkok's new vegan bakeries\n"
    "Nook Bakery in Ari bakes vegan croissants every morning.\n"
    "Fernleaf Cafe added a dessert counter.\n"
    "Moon Crumb has closed its doors after five years.\n"
)
SITE_DOWN = lambda url: (False, None)


def provider(**over):
    results = {"new vegan bakery Bangkok": [
        ("https://www.instagram.com/nook", "Nook", "Bangkok"),
        ("https://www.noodlenyc.example/", "Noodle Bar", "Bangkok street food vibes"),
        (GUIDE, "Bangkok's new vegan bakeries", "New openings in Bangkok"),
    ]}
    pages = {GUIDE: (GUIDE_TEXT, "2026-09-01", [])}
    return FakeProvider(results=over.get("results", results), pages=over.get("pages", pages), **{k: v for k, v in over.items() if k not in ("results", "pages")})


class DiscoverTests(unittest.TestCase):
    def setUp(self):
        self.c = conf(queries=["new vegan bakery Bangkok"], searches_per_run=1)
        self.s = store(self.c)
        self.s.add_account(name="Fernleaf Cafe", status="customer")
        self.ai = FakeAI({GUIDE: [
            biz("Nook Bakery", "Nook Bakery in Ari bakes vegan croissants every morning."),
            biz("Fernleaf Cafe", "Fernleaf Cafe added a dessert counter."),
            biz("Moon Crumb", "Moon Crumb has closed its doors after five years."),
            biz("Invented Bakery", "Invented Bakery is the best in town."),
        ]})

    def test_suggests_only_new_open_quoted_fits_and_says_why_others_were_held(self):
        p = provider()
        report = discover.run(self.c, self.s, sources(self.c, p), self.ai, week=0, site=SITE_DOWN, now=NOW)
        self.assertEqual([x["name"] for x in report["suggested"]], ["Nook Bakery"])
        held = {h["name"]: h["why"] for h in report["held"]}
        self.assertIn("already have it", held["Fernleaf Cafe"])
        self.assertEqual(held["Moon Crumb"], "the source says it closed")
        self.assertEqual(held["Invented Bakery"], "the quote isn't on the page")
        self.assertNotIn("fetch:https://www.instagram.com/nook", p.calls)
        self.assertNotIn("fetch:https://www.noodlenyc.example/", p.calls)
        lead = self.s.pending()[0]
        self.assertEqual(lead["details"]["open_check"], "named in an article from Sep 2026")

    def test_low_fit_is_held_and_runs_never_suggest_the_same_lead_twice(self):
        report = discover.run(self.c, self.s, sources(self.c, provider()), FakeAI(self.ai._businesses, fit=0.2),
                              week=0, site=SITE_DOWN, now=NOW)
        self.assertEqual(report["suggested"], [])
        self.assertTrue(any("not a fit" in h["why"] for h in report["held"]))
        discover.run(self.c, self.s, sources(self.c, provider()), self.ai, week=0, site=SITE_DOWN, now=NOW)
        again = discover.run(self.c, self.s, sources(self.c, provider()), self.ai, week=0, site=SITE_DOWN, now=NOW)
        self.assertEqual(again["suggested"], [])

    def test_paid_provider_out_of_credits_falls_back_to_the_free_one(self):
        paid = FakeProvider("paid", paid=True, fail="credits or rate limit")
        report = discover.run(self.c, self.s, sources(self.c, paid, provider()), self.ai, week=0, site=SITE_DOWN, now=NOW)
        self.assertEqual(len(report["suggested"]), 1)
        self.assertEqual(paid.calls, ["search:new vegan bakery Bangkok"])  # disabled after one failure

    def test_query_rotation_covers_every_query(self):
        qs = ["a", "b", "c", "d", "e"]
        seen = {q for w in range(len(qs)) for q in discover.queries_for_week(qs, w, 2)}
        self.assertEqual(seen, set(qs))


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.c = conf()
        self.s = store(self.c)
        self.known = self.s.add_account(name="Fernleaf Cafe", status="customer")

    def lead(self, name="Nook Bakery", **details):
        return self.s.propose("new_lead", name, f"{name} in Ari bakes croissants.", GUIDE,
                              {"industry": "Bakery", "fit": 0.8, "website": "https://nook.example", **details})

    def test_add_creates_a_lead_with_its_source(self):
        pid = self.lead()
        self.assertEqual(decisions.decide(self.s, pid, "add"), "added")
        account = next(a for a in self.s.accounts() if a["name"] == "Nook Bakery")
        self.assertEqual((account["status"], account["website"]), ("lead", "https://nook.example"))
        self.assertIn(GUIDE, account["notes"])
        self.assertEqual(decisions.decide(self.s, pid, "add"), "already added")

    def test_same_remembers_the_name_and_domain_as_aliases(self):
        pid = self.lead("Fern Table", maybe_same={"id": self.known, "name": "Fernleaf Cafe", "why": "fern"})
        self.assertEqual(decisions.decide(self.s, pid, "same"), "linked to Fernleaf Cafe")
        self.assertEqual({(a["kind"], a["value"]) for a in self.s.aliases()}, {("name", "Fern Table"), ("domain", "nook.example")})

    def test_skip_reasons_and_closed_sources(self):
        decisions.decide(self.s, self.lead("A Bakery"), "skip", "closed")
        decisions.decide(self.s, self.lead("B Bakery"), "skip", "closed")
        self.assertEqual(self.s.closed_counts(), {GUIDE: 2})

    def test_owner_save_records_evidence(self):
        pid = self.s.propose("owner", "Mali Somsri", "Founder Mali Somsri opened Nook in 2024.", "https://nook.example/about",
                             {"business": "Fernleaf Cafe", "role": "founder"}, self.known)
        decisions.decide(self.s, pid, "save")
        account = next(a for a in self.s.accounts() if a["id"] == self.known)
        self.assertEqual((account["owner_name"], account["owner_role"]), ("Mali Somsri", "founder"))


class OwnerTests(unittest.TestCase):
    def test_finds_site_reads_about_page_and_suggests_a_verified_owner(self):
        c = conf()
        s = store(c)
        aid = s.add_account(name="Nook Bakery", status="lead", area="Bangkok")
        home, about = "https://www.nookbakery.example/", "https://www.nookbakery.example/about"
        p = FakeProvider(
            results={'"Nook Bakery" Bangkok': [("https://www.tripadvisor.com/nook", "Nook", ""), (home, "Nook Bakery", "")],
                     '"Nook Bakery" founder': []},
            pages={home: ("Welcome to Nook Bakery, Bangkok.", None, ["/about", "https://elsewhere.example/team"]),
                   about: ("Nook Bakery was founded by Mali Somsri, a pastry chef, in 2024.", None, [])})
        ai = FakeAI(owner={"found": True, "name": "Mali Somsri", "role": "founder", "page_index": 1,
                           "quote": "Nook Bakery was founded by Mali Somsri, a pastry chef, in 2024."})
        report = owners.run(conf(data_dir=c.data_dir, registry_url="https://registry.example/search?q={name}"), s, sources(c, p), ai)
        self.assertEqual(report["leads"][0]["status"], "suggested Mali Somsri (founder)")
        kinds = {x["kind"]: x for x in s.pending()}
        self.assertEqual(kinds["website"]["name"], home)
        self.assertEqual(kinds["owner"]["account_id"], aid)
        self.assertEqual(kinds["owner"]["details"]["registry"], "https://registry.example/search?q=Nook%20Bakery")

    def test_an_owner_whose_quote_is_not_on_the_page_is_dropped(self):
        c = conf()
        s = store(c)
        s.add_account(name="Nook Bakery", status="lead", website="https://www.nookbakery.example/")
        p = FakeProvider(results={'"Nook Bakery" founder': []},
                         pages={"https://www.nookbakery.example/": ("Welcome to Nook Bakery.", None, [])})
        ai = FakeAI(owner={"found": True, "name": "Someone Else", "role": "owner", "page_index": 0, "quote": "Owner Someone Else."})
        report = owners.run(c, s, sources(c, p), ai)
        self.assertEqual(report["leads"][0]["status"], "owner answer failed the quote check")
        self.assertEqual(s.pending(), [])


class TelegramTests(unittest.TestCase):
    class Bot:
        chat_id = "42"

        def __init__(self):
            self.calls = []

        def call(self, method, payload, timeout=40):
            self.calls.append((method, payload))
            return {"message_id": 7}

    def test_buttons_send_and_only_this_chat_can_decide(self):
        c = conf()
        s = store(c)
        pid = s.propose("new_lead", "Nook Bakery", "Nook Bakery bakes.", GUIDE, {"fit": 0.8})
        bot = self.Bot()
        self.assertEqual(telegram.send(s, bot), 1)
        self.assertLessEqual(max(len(b["callback_data"]) for row in telegram.buttons(s.proposal(pid)) for b in row), 64)
        other = {"callback_query": {"id": "q", "data": f"lf:{pid}:a", "message": {"message_id": 7, "chat": {"id": 99}}}}
        self.assertEqual(telegram.handle(other, s, bot), "ignored: another chat")
        mine = {"callback_query": {"id": "q", "data": f"lf:{pid}:c", "message": {"message_id": 7, "chat": {"id": 42}}}}
        self.assertEqual(telegram.handle(mine, s, bot), "skipped: closed")
        self.assertEqual(s.proposal(pid)["reason"], "closed")


if __name__ == "__main__":
    unittest.main()
