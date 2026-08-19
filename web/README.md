# Crucible dashboard

Static React app. Reads `public/data/report.json`, which is produced by:

    python -m crucible.cli run --agent devops@v1
    python -m crucible.cli run --agent devops@v2
    python -m crucible.cli report --out web/public/data

There is no backend by design: the replay cache means every number on the page is already
computed, so the deployed site needs no API key and nothing to keep warm.

    npm install
    npm run dev        # http://localhost:5173
    npm run build      # -> dist/
