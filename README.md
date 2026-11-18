# Cairn status

The public status page for Cairn, at https://status.cairnsuite.com.

- `services.json`: the public app addresses that get checked. Add Relay and AI Practice here once they're live on production.
- `.github/workflows/check.yml`: runs every 5 minutes (GitHub may start it late) and runs `scripts/check.py`.
- `scripts/check.py`: checks each service and keeps one row per service per day (checks run, checks failed, worst response time) for 90 days in `data/daily.json`. It commits only when something changes or once an hour. Between commits, results are kept in the Actions cache.
- Alerts: two failures in a row open an issue titled "<Service> down" with the label `incident`, and the first good check closes it. GitHub emails repo watchers about new issues.
- `index.html`: the page, served by GitHub Pages from `main`.

This repo is public. It holds only check results and the page: no keys, no customer data, and no addresses other than the public app addresses.
