"""
Base collector interface for all opportunity sources.
Every new data source implements this interface.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RawOpportunity:
    """Raw opportunity before normalization."""
    source: str
    source_url: str
    title: str
    description_raw: str
    url: str
    organization: Optional[str] = None
    deadline: Optional[str] = None
    posted_date: Optional[str] = None
    location: Optional[str] = None
    raw_html: Optional[str] = None
    extra_fields: dict = field(default_factory=dict)


@dataclass
class ScrapeResult:
    """Result of a single scrape run."""
    source: str
    timestamp: datetime
    success: bool
    records_found: int
    records_new: int
    records_updated: int
    errors: list = field(default_factory=list)
    duration_seconds: float = 0.0


class BaseCollector(ABC):
    """Abstract base class for all opportunity collectors."""

    def __init__(self, source_name: str, config: dict):
        self.source_name = source_name
        self.config = config
        self.rate_limit_delay = config.get("rate_limit_delay", 5)
        self.logger = logging.getLogger(f"collector.{source_name}")

    @abstractmethod
    def collect(self) -> list[RawOpportunity]:
        """
        Fetch and return raw opportunities from this source.
        Must be implemented by each collector.
        """
        pass

    def run(self) -> ScrapeResult:
        """Execute collection with logging and error handling."""
        start = time.time()
        self.logger.info(f"Starting collection from {self.source_name}")

        try:
            raw_opportunities = self.collect()
            duration = time.time() - start

            result = ScrapeResult(
                source=self.source_name,
                timestamp=datetime.utcnow(),
                success=True,
                records_found=len(raw_opportunities),
                records_new=0,  # Updated after dedup in pipeline
                records_updated=0,
                duration_seconds=duration,
            )

            self.logger.info(
                f"Collected {result.records_found} records from "
                f"{self.source_name} in {duration:.1f}s"
            )
            return result

        except Exception as e:
            duration = time.time() - start
            self.logger.error(f"Collection failed for {self.source_name}: {e}")

            return ScrapeResult(
                source=self.source_name,
                timestamp=datetime.utcnow(),
                success=False,
                records_found=0,
                records_new=0,
                records_updated=0,
                errors=[str(e)],
                duration_seconds=duration,
            )

    def _rate_limit(self):
        """Respect rate limits between requests."""
        time.sleep(self.rate_limit_delay)
