.PHONY: install install-dev test run run-streamlit collect lint clean refresh openapi openapi-types

# Install production dependencies
install:
	pip install -r requirements.txt

# Install dev dependencies (includes streamlit + pandas for the legacy explorer)
install-dev:
	pip install -r requirements-dev.txt

# Run tests
test:
	pytest tests/ -v

# Run the FastAPI backend (the actual production server)
run:
	uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

# Run the legacy Streamlit data-explorer dashboard.
# Production UI is the Next.js frontend (see frontend/); this is just an
# ad-hoc tool for browsing data/processed/opportunities.json. Optional.
run-streamlit:
	streamlit run src/app/streamlit_app.py

# Run collectors
collect-our:
	python -m src.collectors.uiuc_our_rss

collect-sro:
	python -m src.collectors.uiuc_sro

# Refresh all data sources (deep scrape by default)
refresh:
	python -m src.collectors.refresh_all

# Refresh without deep scraping (faster)
refresh-quick:
	python -m src.collectors.refresh_all --no-deep

# Clean
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Dump the FastAPI OpenAPI schema to disk (frontend uses this for types).
# Production never serves /openapi.json — only this offline dump exists.
openapi:
	python3 scripts/dump_openapi.py frontend/src/lib/openapi.json

# Regenerate the TypeScript API types from the OpenAPI schema. Requires
# `openapi-typescript` (devDependency); writes api-types.gen.ts which
# `lib/types.ts` can re-export from for incremental migration.
openapi-types: openapi
	cd frontend && npx --yes openapi-typescript src/lib/openapi.json -o src/lib/api-types.gen.ts
