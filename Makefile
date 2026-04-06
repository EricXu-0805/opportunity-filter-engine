.PHONY: install test run collect lint clean refresh

# Install dependencies
install:
	pip install -r requirements.txt

# Run tests
test:
	pytest tests/ -v

# Run Streamlit app
run:
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
