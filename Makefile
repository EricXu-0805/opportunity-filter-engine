.PHONY: install test run collect lint clean

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

# Clean
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
