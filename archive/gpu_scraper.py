import requests
from bs4 import BeautifulSoup
import time
import datetime
import os
import csv
import re
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

# --- SETTINGS ---
FORCE_GPU = True 
CSV_FILE = "/root/Web-Scraping-Demo/scraped_data.csv"
URL_LIST_FILE = "/root/Web-Scraping-Demo/urls.txt"

def save_to_csv(data):
    file_exists = os.path.isfile(CSV_FILE)
    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["Date", "Platform", "Title", "Price", "Rating", "URL"])
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)
    print(f"   [+] Data saved to CSV")

def get_best_price(text_block):
    if not text_block: return "N/A"
    matches = re.findall(r"\$([\d,]+)", text_block)
    if not matches: return "Price Not Found"
    try:
        values = [int(m.replace(',', '')) for m in matches]
        return f"${min(values)}"
    except:
        return matches[0]

def resource_mapper(url, index, total):
    print(f"\n--- Processing {index}/{total}: {url[:40]}... ---")
    
    try:
        with sync_playwright() as p:
            # print("   [>] Launching Browser...")
            context = p.chromium.launch_persistent_context(
                "./user_data",
                headless=True,
                viewport={"width": 1920, "height": 1080},
                args=["--headless=new", "--disable-blink-features=AutomationControlled", "--disable-gpu", "--no-sandbox"]
            )
            
            page = context.pages[0]
            page.goto(url)

            domain = urlparse(url).netloc
            platform = "Unknown"
            title = "Not Found"
            price = "Not Found"
            rating = "N/A"

            # --- AMAZON LOGIC ---
            if "amazon" in domain:
                platform = "Amazon"
                try:
                    page.wait_for_selector("#productTitle", timeout=10000)
                    title = page.locator("#productTitle").first.inner_text().strip()
                    
                    p_whole = page.locator(".a-price-whole").first.inner_text().replace(".", "")
                    p_frac = page.locator(".a-price-fraction").first.inner_text()
                    price = f"${p_whole}.{p_frac}"
                    
                    rating = page.locator("span[data-action='acrStarsLink-click-metrics']").first.inner_text().strip()
                except:
                    pass

            # --- AIRBNB LOGIC ---
            elif "airbnb" in domain:
                platform = "Airbnb"
                try:
                    page.wait_for_selector("h1", state="visible", timeout=15000)
                    title = page.locator("h1").first.inner_text().strip()
                    
                    try:
                        sidebar_text = page.locator("div[data-testid='book-it-default']").inner_text()
                        price = get_best_price(sidebar_text)
                    except:
                        body_text = page.locator("body").inner_text()
                        price = get_best_price(body_text[:2000])

                    try:
                        rating = page.locator("div[data-testid='pdp-reviews-highlight-banner-host-rating']").first.inner_text()
                    except:
                        rating = "N/A"
                except:
                    pass

            print(f"   [V] CAPTURED: {title[:30]}... | {price}")

            # --- SAVE ---
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"screenshots/{platform}_{timestamp}.png"
            os.makedirs("/root/Web-Scraping-Demo/screenshots", exist_ok=True)
            
            page.screenshot(path=filename)
            
            save_to_csv({
                "Date": timestamp,
                "Platform": platform,
                "Title": title,
                "Price": price,
                "Rating": rating,
                "URL": url
            })
            
            context.close()
            return "SUCCESS"

    except Exception as e:
        print(f"   [X] Failed: {e}")
        return "ERROR"

if __name__ == "__main__":
    # 1. Check if urls.txt exists
    if not os.path.exists(URL_LIST_FILE):
        print("ERROR: 'urls.txt' not found! Please create it and add links.")
    else:
        # 2. Read the file
        with open(URL_LIST_FILE, "r") as f:
            urls = [line.strip() for line in f if line.strip()]
        
        print(f"Loaded {len(urls)} targets from urls.txt")
        
        # 3. Loop through them
        for i, url in enumerate(urls, 1):
            resource_mapper(url, i, len(urls))
            
            # 4. Polite Delay (prevents bans)
            if i < len(urls):
                print("   [z] Sleeping 3 seconds...")
                time.sleep(3)
                
        print("\nAll tasks complete. Check 'scraped_data.csv'.")