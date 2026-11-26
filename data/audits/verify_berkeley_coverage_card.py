"""Observe Berkeley's live school-switcher card during normal campus selection."""
from urllib.parse import urlsplit
from playwright.sync_api import expect


class BerkeleyCoverageCard:
    def __init__(self, page, receipt, output):
        self.receipt = receipt
        self.output = output
        self.responses = []
        page.on("response", self._capture)

    @staticmethod
    def _is_coverage(response):
        return (response.request.method == "GET" and
                urlsplit(response.url).path == "/api/opportunities/coverage" and
                response.ok)

    def _capture(self, response):
        if self._is_coverage(response):
            self.responses.append(response)

    def verify(self, page, card):
        page.get_by_role("textbox", name="Search universities").fill("Berkeley")
        expect(card).to_be_visible(timeout=60000)
        if not self.responses:
            page.wait_for_event("response", predicate=self._is_coverage, timeout=90000)
        response = self.responses[-1]
        payload = response.json()
        counts = payload["schools"]["ucb"]
        self.receipt["berkeley_switcher"] = {
            "http": response.status, "schema": payload["schema"], "counts": counts,
        }
        assert payload["schema"] == "school-coverage-v2"
        assert (counts["listing_count"], counts["faculty_contact_count"], counts["total_count"]) == (71, 2161, 2232)
        expect(card.get_by_text("Saved data snapshot", exact=True)).to_have_count(0, timeout=60000)
        expect(card.get_by_text("2,200+ campus records", exact=True)).to_be_visible()
        expect(card.get_by_text("71 projects & postings · 2,161 professor profiles", exact=True)).to_be_visible()
        self.receipt["berkeley_switcher"]["rendered"] = card.inner_text()
        card.screenshot(path=self.output / "berkeley-live-campus-count.png")
