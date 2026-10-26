![Uploading ebimaruredesign.png…]()


# Owner-first Lead Finder

Find new small-business buyers for what you sell, and the person at each one who decides, with you approving every suggestion.

Built for small suppliers who sell to independent food businesses: bakeries, cafés, restaurants and grocers. Once a week it searches the web for guides and articles about new shops in your cities, reads them, and suggests a handful of businesses that fit what you sell. Twice a week it looks for the owner of each lead you approved. Nothing is added to your list until you tap **Add**.

```
 Monday                                   Tuesday and Thursday
 ┌──────────────┐                         ┌──────────────────────┐
 │ search the   │  guides & articles      │ for each approved    │
 │ web (2 Qs)   │────────────┐            │ lead: own website,   │
 └──────────────┘            ▼            │ about/team pages,    │
                    ┌──────────────────┐  │ press interviews     │
                    │ AI lists the     │  └─────────┬────────────┘
                    │ businesses named │            ▼
                    │ + exact sentence │  ┌──────────────────────┐
                    └────────┬─────────┘  │ AI names the owner   │
                             ▼            │ + exact sentence     │
                    ┌──────────────────┐  └─────────┬────────────┘
                    │ checks in code:  │            ▼
                    │ quote is real,   │  ┌──────────────────────┐
                    │ not already known│  │ quote check in code, │
                    │ still open, fits │  │ registry link        │
                    └────────┬─────────┘  └─────────┬────────────┘
                             ▼                      ▼
                     ┌────────────────────────────────────┐
                     │  you decide: Telegram or terminal  │
                     │  Add · Same as… · Closed ·         │
                     │  Customer · Not a fit · Save       │
                     └────────────────────────────────────┘
```

## Why "owner first"

A shop's general inbox rarely replies. Small food businesses buy when the person who decides what goes into the croissants hears from you directly, whatever the size of the order. So finding the shop is only half the job; this tool also finds who runs it.

## The rules it follows

- **The AI finds, code decides, you approve.** The model only reads pages and judges fit. Whether a suggestion reaches you is decided by plain code, and nothing is saved without your decision.
- **Every suggestion comes with its source sentence**, copied from the page, and code checks that the sentence really is on the saved page. Made-up businesses and owners are dropped.
- **No duplicates.** Import your customers and prospects once; a business that matches one by name, website, social handle or phone is never suggested. Look-alike names are flagged "might be the same as…".
- **Still open.** A lead is held back if the source says it closed, if its own website is down, or if the only evidence is an old article. Searches only count results from the past year.
- **Right place.** Search results about another city are skipped, even when they mention yours in passing.
- **Social media and directories are never sources.** Review sites, maps, delivery apps and job boards can't become saved facts.
- **Registries are linked, never scraped.** Owner suggestions can carry a link to your country's company registry for you to check by hand.
- **It learns from your skips.** A guide that keeps leading to closed shops stops being read.
- **Bounded spend.** A paid search provider is used within a per-run budget, with a free one as the automatic backup.

## What you need

- Python 3.11 or newer.
- An [Anthropic API key](https://console.anthropic.com) (reads pages and judges fit).
- At least one search provider:
  - [TinyFish](https://tinyfish.ai): free Search and Fetch tier. Enough on its own.
  - [Firecrawl](https://firecrawl.dev): paid, cleaner pages. Used first when set, with TinyFish as the backup.
- Optional: a Telegram bot to approve suggestions from your phone.

## Set up

```bash
git clone https://github.com/<you>/owner-first-lead-finder.git
cd owner-first-lead-finder
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp config.example.toml config.toml   # describe your business
cp .env.example .env                 # add your keys
```

1. **Describe your business** in `config.toml`: what you sell, who buys it, what to exclude, your cities and the searches a customer would type. Queries containing `{place}` run once per city. Write the `match` words for each city in every language your guides use.
2. **Import what you already have**, so you never get suggestions for current customers:
   ```bash
   leadfinder import my-accounts.csv
   ```
   Columns: `name, status, website, phone, instagram, line, industry, area, notes` (status is `customer` or `prospect`). See `examples/accounts.csv`.
3. **Run it:**
   ```bash
   leadfinder discover          # find new leads (a report of what was suggested and why others were held)
   leadfinder review            # decide them in the terminal
   leadfinder owners            # find owners for leads you added
   leadfinder export leads.csv  # approved leads with owners, for your CRM or spreadsheet
   ```

### Approving from your phone (optional)

1. Message [@BotFather](https://t.me/BotFather) on Telegram, create a bot, and put its token in `TELEGRAM_BOT_TOKEN`.
2. Send your bot any message, then open `https://api.telegram.org/bot<token>/getUpdates` and copy `chat.id` into `TELEGRAM_CHAT_ID`.
3. `leadfinder telegram send` posts waiting suggestions with buttons; `leadfinder telegram listen` handles your taps (no web server needed). Only taps from your own chat are acted on.

## Run it on a schedule

See [docs/scheduling.md](docs/scheduling.md) for cron and macOS launchd examples. A good rhythm: discover on Monday morning, owners on Tuesday and Thursday, `telegram send` after each, and `telegram listen` always running.

## What it costs

Each weekly run makes 2 searches, reads up to 4 pages, and makes one AI call per page plus one per candidate. Owner runs read a few pages per lead. On TinyFish's free tier the search side costs nothing. AI cost depends on page length and model. Change `[ai] model` and `effort` in `config.toml` to trade quality for cost.

## Make it yours

- **Selling something else?** Change `[business]` and `queries`. The checks don't care what you sell.
- **Another country?** Set `country`, `phone_country_code`, your cities' `match` words, and optionally `registry_url`.
- **More leads?** Raise `searches_per_run` and `max_proposals`. You'll get more decisions to make, too.
- **Your own CRM?** Use `export`, or read `data/leadfinder.db` (SQLite) directly.

## Responsible use

- Reach out the way you'd want to be reached: one personal message, not a mailing list. Follow your local rules on direct marketing and personal data (for example GDPR, PDPA or CAN-SPAM).
- Owner names come only from public business pages and press, and only for the business they run. Don't use this to profile private individuals.
- Respect websites' terms. Don't point the tool at sites that forbid automated access, and never automate a government registry.
- Keep `.env`, `config.toml` and `data/` private. They're in `.gitignore` for that reason.

## Development

```bash
python -m unittest discover -s tests -t .
```

Tests run offline with fake web and AI responses, so no keys are needed. Every business in them is made up.

## License

MIT. See [LICENSE](LICENSE).
