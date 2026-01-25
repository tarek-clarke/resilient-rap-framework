import requests
from bs4 import BeautifulSoup
import time
import datetime
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

# NOTE: Uncomment this if/when you fix the stealth library version
# from playwright_stealth import stealth_sync 

def resource_mapper(url):
    print(f"\n--- Stimulus Analysis: {url} ---")
    start_time = time.time()
    
    try:
        # --- Phase 1: Lightweight Reconnaissance (CPU) ---
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Metrics Calculation
        page_title = soup.title.string.strip() if soup.title else "No Title Found"
        tag_count = len(soup.find_all())
        text_length = len(soup.get_text())
        density = tag_count / (text_length + 1)
        is_dynamic = any(attr in response.text for attr in ['__NEXT_DATA__', 'root-app', 'chunk.js', 'airbnb-bootstrap'])

        print(f"DEBUG: HTTP Status = {response.status_code}")
        print(f"DEBUG: Page Title = '{page_title}'")
        print(f"Metrics: Tags={tag_count}, Text={text_length}, Density={density:.4f}")

        # --- Phase 2: Decision Logic ---
        if density < 0.01 or is_dynamic or text_length < 1000:
            print("DECISION: Mapping to GPU (Playwright/Chromium Path)")
            
            # --- START PLAYWRIGHT LOGIC ---
            with sync_playwright() as p:
                # We use a 'user_data' folder inside the project so cookies persist
                user_data_dir = "./user_data" 

                print("Launching Headless Browser...")
                context = p.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=True, 
                    args=["--disable-blink-features=AutomationControlled"]
                )
                
                context.set_default_timeout(60000)
                page = context.pages[0]
                
                # stealth_sync(page) # Uncomment if library is fixed
                
                print(f"Navigating to {url}...")
                page.goto(url)
                
                # --- SMARTER WAIT STRATEGY ---
                print("Waiting for DOM structure...")
                page.wait_for_load_state('domcontentloaded')
                
                try:
                    print("Waiting for main content (h1)...")
                    page.wait_for_selector('h1', state='visible', timeout=15000)
                except Exception as e:
                    print("Warning: H1 tag not found or timed out. Proceeding anyway.")
                
                time.sleep(2) # Buffer for images
                
                # --- FILENAME & PATH GENERATION ---
                domain = urlparse(url).netloc
                current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                filename = f"{domain}_{current_time}.png"
                
                # Ensure the directory exists
                output_dir = "screenshots"
                os.makedirs(output_dir, exist_ok=True)
                
                screenshot_path = os.path.join(output_dir, filename)
                # ----------------------------------

                # Verify content
                full_title = page.title()
                print(f"GPU Rendered Title: {full_title}")
                
                try:
                    page.screenshot(path=screenshot_path)
                    print(f"Success! Saved to: {screenshot_path}")
                except Exception as e:
                    print(f"Error saving screenshot: {e}")
                
                context.close()
            # --- END PLAYWRIGHT LOGIC ---

            status = "GPU_ACCELERATED"
        else:
            print("DECISION: Mapping to CPU (BeautifulSoup Path)")
            status = "CPU_STATIC"

        exec_time = time.time() - start_time
        print(f"Infrastructure Logic complete in {exec_time:.2f}s | Status: {status}")
        return status

    except Exception as e:
        print(f"Critical Infrastructure Failure: {e}")
        return "ERROR"

if __name__ == "__main__":
    target_url = input("Enter the target URL to map: ")
    resource_mapper(target_url)