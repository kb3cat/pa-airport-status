name: Update METAR in status.json

on:
  workflow_dispatch:
  schedule:
    - cron: "*/5 * * * *"   # every 5 minutes (GitHub schedules are best-effort)

permissions:
  contents: write

concurrency:
  group: metar-update
  cancel-in-progress: true

jobs:
  update:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.x"

      - name: Update METAR fields in status.json
        run: python3 scripts/update_metar.py
        env:
          STATUS_JSON_PATH: status.json
          OUTPUT_JSON_PATH: status.json
          SLEEP_BETWEEN_REQUESTS_MS: "150"

      - name: Commit and push if changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

          if git diff --quiet; then
            echo "No changes."
            exit 0
          fi

          git add status.json
          git commit -m "Update METAR in status.json"
          git push
