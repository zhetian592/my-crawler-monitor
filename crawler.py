name: Tier1 - Manual

on:
  workflow_dispatch:

concurrency:
  group: tier1-manual
  cancel-in-progress: false

jobs:
  crawl:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.PAT_TOKEN }}
          fetch-depth: 1          # 加快检出速度

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install -r requirements.txt

      - name: Start RSS proxy (if needed)
        run: |
          python rss_proxy.py --port 1200 &
          sleep 3
          curl -fsS http://localhost:1200/health || {
            echo "❌ RSS proxy health check failed"
            exit 1
          }

      - name: Run crawler
        env:
          # 只保留实际使用的 Key（已移除 GOOGLE_API_KEY）
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
        run: python crawler.py

      - name: Generate commit message
        id: msg
        run: |
          echo "COMMIT_MSG=Manual update $(date -u '+%Y-%m-%d %H:%M:%S UTC')" >> $GITHUB_ENV

      - name: Commit and push changes
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: ${{ env.COMMIT_MSG }}
          file_pattern: "data/* report.md report.html reports/*"
          commit_user_name: "github-actions[bot]"
          commit_user_email: "41898282+github-actions[bot]@users.noreply.github.com"
          commit_author: "github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>"
        env:
          GITHUB_TOKEN: ${{ secrets.PAT_TOKEN }}
