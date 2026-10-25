# Running on a schedule

The finder is a set of commands, so any scheduler works. Times below are local to the machine; cloud cron services often run in UTC, so convert.

A rhythm that works for a small sales team:

| When | Command | Why |
|---|---|---|
| Monday 07:30 | `leadfinder discover && leadfinder telegram send` | New leads waiting with your morning coffee |
| Tuesday and Thursday 07:00 | `leadfinder owners && leadfinder telegram send` | Owners for the leads you added |
| Always | `leadfinder telegram listen` | Applies your taps |

## cron (Linux, macOS)

`crontab -e`, then (replace the path):

```cron
30 7 * * 1   cd /path/to/owner-first-lead-finder && .venv/bin/leadfinder discover >> data/discover.log 2>&1 && .venv/bin/leadfinder telegram send >> data/telegram.log 2>&1
0 7 * * 2,4  cd /path/to/owner-first-lead-finder && .venv/bin/leadfinder owners >> data/owners.log 2>&1 && .venv/bin/leadfinder telegram send >> data/telegram.log 2>&1
```

For the always-on listener, use a process manager (systemd, launchd), or replace it with a cron line every few minutes:

```cron
*/5 * * * *  cd /path/to/owner-first-lead-finder && .venv/bin/leadfinder telegram poll >> data/telegram.log 2>&1
```

`telegram poll` handles waiting taps once and exits.

## launchd (macOS)

Save as `~/Library/LaunchAgents/local.leadfinder.listen.plist` (replace the paths), then `launchctl load` it:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.leadfinder.listen</string>
  <key>WorkingDirectory</key><string>/path/to/owner-first-lead-finder</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/owner-first-lead-finder/.venv/bin/leadfinder</string>
    <string>telegram</string><string>listen</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/path/to/owner-first-lead-finder/data/telegram.log</string>
  <key>StandardErrorPath</key><string>/path/to/owner-first-lead-finder/data/telegram.log</string>
</dict>
</plist>
```

Use a `StartCalendarInterval` entry instead of `KeepAlive` for the Monday and Tuesday/Thursday jobs.
