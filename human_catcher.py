from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

def capture_with_persistence():
    with sync_playwright() as p:
        # Save your 'identity' to a folder on your G: Drive
        user_data_dir = "/app/user_data"
        
        # Use launch_persistent_context instead of a standard browser
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False, # Set to False temporarily to solve the CAPTCHA once
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0]
        
        # Apply the 2026 Stealth Class
        Stealth().apply_stealth_sync(page)
        
        # Manually navigate to Google once and solve the robot screen
        page.goto("https://www.google.com/search?q=AMD+7900+XT+price")
        
        # The script will wait here. Solve the CAPTCHA in the window!
        print("Please solve the CAPTCHA in the VS Code window if it appears...")
        page.wait_for_load_state("networkidle")
        
        page.screenshot(path="/app/test_target.png")
        context.close()

capture_with_persistence()