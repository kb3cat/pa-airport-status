name: Update PA Airport Status

on:
  workflow_dispatch:
  schedule:
    - cron: "*/5 * * * *"

permissions:
  contents: write

concurrency:
  group: pa-airport-status
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
          python-version: "3.11"

      - name: Run updater
        run: python3 scripts/update_status.py

      - name: Commit and push if changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

          if git diff --quiet; then
            echo "No changes to commit."
            exit 0
          fi

          git add docs/status.json
          git commit -m "Update airport status.json"
          git push
