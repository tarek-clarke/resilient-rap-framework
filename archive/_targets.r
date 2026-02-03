library(targets)
library(reticulate)

# PIVOT: Use the System Python instead of the broken Conda one
use_python("/usr/bin/python3", required = TRUE)

list(
  tar_target(
    screenshot_file,
    {
      img_path <- "test_site.png"
      # This ensures Playwright runs in the correct system scope
      py_run_string("from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto('https://www.google.com')
    page.screenshot(path='test_site.png')
    browser.close()")
      "test_site.png"
    },
    format = "file"
  ),

  tar_target(
    vision_results,
    {
      source_python("vision_agent.py")
      detect_price_clusters(screenshot_file)
    }
  )
)