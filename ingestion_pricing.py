from base_ingestor import BaseIngestor
from bs4 import BeautifulSoup
import requests
import re


class PricingIngestor(BaseIngestor):
    """
    Adapter for scraping pricing data from semi-structured web pages.
    This is a refactored version of your GPU scraper.
    """

    def __init__(self, url: str):
        super().__init__(source_name="pricing_scraper")
        self.url = url

    # ---------------------------------------------------------
    def connect(self):
        self.session = requests.Session()

    # ---------------------------------------------------------
    def extract_raw(self):
        response = self.session.get(self.url, timeout=10)
        response.raise_for_status()
        return response.text

    # ---------------------------------------------------------
    def parse(self, raw):
        soup = BeautifulSoup(raw, "html.parser")
        text = soup.get_text(" ", strip=True)
        return text

    # ---------------------------------------------------------
    def validate(self, parsed):
        if "$" not in parsed:
            raise ValueError("No price-like patterns found in page text")

    # ---------------------------------------------------------
    def normalize(self, parsed):
        # Extract price-like patterns
        matches = re.findall(r"\$[\d,]+(?:\.\d{2})?", parsed)

        normalized = []
        for m in matches:
            clean = m.replace("$", "").replace(",", "")
            try:
                price = float(clean)
                normalized.append({"price": price})
            except ValueError:
                continue

        return normalized
