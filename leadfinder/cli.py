"""leadfinder: find new small-business buyers and the people who decide.

  leadfinder import accounts.csv   your existing customers/prospects, so they're never suggested
  leadfinder discover              weekly: search, read guides, suggest new leads
  leadfinder owners                twice a week: find owners for leads you approved
  leadfinder review                approve or skip suggestions in the terminal
  leadfinder telegram send|listen  approve from your phone instead
  leadfinder export leads.csv      approved leads, with owners, for your CRM
  leadfinder status                what's waiting
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config as cfg
from .store import Store


def _context(args, need_sources: bool = False, need_ai: bool = False):
    cfg.load_env(Path(args.env))
    conf = cfg.load(Path(args.config))
    store = Store(conf.data_dir / "leadfinder.db")
    sources = ai = None
    if need_sources:
        from .sources import PageCache, Sources
        sources = Sources.from_config(conf, PageCache(conf.data_dir))
    if need_ai:
        if not (cfg.secret("ANTHROPIC_API_KEY") or cfg.secret("ANTHROPIC_AUTH_TOKEN")):
            raise SystemExit("Set ANTHROPIC_API_KEY in .env (https://console.anthropic.com).")
        from .ai import AI
        ai = AI(conf)
    return conf, store, sources, ai


def _print(report: dict) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="leadfinder", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--env", default=".env")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_imp = sub.add_parser("import", help="import existing businesses from CSV")
    p_imp.add_argument("csv")
    p_dis = sub.add_parser("discover", help="find new leads")
    p_dis.add_argument("--week", type=int, help="which rotation of searches to run (default: this week)")
    p_own = sub.add_parser("owners", help="find owners for approved leads")
    p_own.add_argument("--include-prospects", action="store_true", help="also research imported prospects")
    sub.add_parser("review", help="decide suggestions in the terminal")
    p_tg = sub.add_parser("telegram", help="decide suggestions on Telegram")
    p_tg.add_argument("action", choices=["send", "listen", "poll"])
    p_exp = sub.add_parser("export", help="export approved leads to CSV")
    p_exp.add_argument("csv")
    sub.add_parser("status", help="what's waiting")
    args = ap.parse_args(argv)

    if args.cmd == "import":
        _, store, _, _ = _context(args)
        print(f"imported {store.import_csv(Path(args.csv))} businesses")
    elif args.cmd == "discover":
        from . import discover
        conf, store, sources, ai = _context(args, need_sources=True, need_ai=True)
        _print(discover.run(conf, store, sources, ai, week=args.week))
    elif args.cmd == "owners":
        from . import owners
        conf, store, sources, ai = _context(args, need_sources=True, need_ai=True)
        _print(owners.run(conf, store, sources, ai, include_prospects=args.include_prospects))
    elif args.cmd == "review":
        from .review import review
        _, store, _, _ = _context(args)
        review(store)
    elif args.cmd == "telegram":
        from . import telegram
        conf, store, _, _ = _context(args)
        bot = telegram.Bot.from_env()
        if args.action == "send":
            print(f"sent {telegram.send(store, bot)}")
        else:
            telegram.listen(store, bot, conf.data_dir / "telegram_offset", once=args.action == "poll")
    elif args.cmd == "export":
        _, store, _, _ = _context(args)
        print(f"exported {store.export_csv(Path(args.csv))} leads")
    elif args.cmd == "status":
        _, store, _, _ = _context(args)
        pending = store.pending()
        kinds = {k: sum(1 for p in pending if p["kind"] == k) for k in ("new_lead", "website", "owner")}
        leads = [a for a in store.accounts() if a["status"] == "lead"]
        print(f"waiting: {kinds['new_lead']} new leads, {kinds['website']} websites, {kinds['owner']} owners")
        print(f"approved leads: {len(leads)} ({sum(1 for a in leads if a.get('owner_name'))} with an owner)")


if __name__ == "__main__":
    sys.exit(main())
