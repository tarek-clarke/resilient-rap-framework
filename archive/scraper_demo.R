# PREREQUISITES:
# install.packages(c("chromote", "tidyverse", "jsonlite"))
# You must have Google Chrome installed on your machine.

library(chromote)
library(tidyverse)
library(jsonlite)

# --- CONFIGURATION ---

# OPTION A: Robust Testing Sandbox (GUARANTEED TO WORK)
# We use this for the demo to avoid CAPTCHAs or Out-of-Stock errors.
# Note: This site uses British Pounds (£), so our visual scanner looks for that symbol.
target_url <- "http://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"

# OPTION B: Real-World Target (Amazon Canada)
# Uncomment this to test against a live environment (Note: May trigger CAPTCHA)
# target_url <- "https://www.amazon.ca/dp/B09G9F5T3N"

user_agent <- "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# --- 1. INITIALIZE THE "EYE" (Headless Chrome) ---
# We create a Chromote object. This is your "Robot Browser".
b <- ChromoteSession$new()

# Set User Agent to avoid immediate blocking
b$Network$setUserAgentOverride(userAgent = user_agent)

# Navigate to the page
cat("Step 1: Navigating to page...\n")
b$Page$navigate(target_url)
b$Page$loadEventFired() # Wait for load
Sys.sleep(3) # Extra wait for dynamic price widgets to render

# --- 2. THE VISUAL EXTRACTION (The PhD Innovation) ---
# Instead of asking for ".a-price-whole" (which might change),
# We inject JavaScript to find elements based on how they LOOK.

cat("Step 2: Scanning visual layout...\n")

# This JS function finds all elements with a '$' OR '£' and returns their Computed Styles
js_visual_scan <- "
(() => {
  const allNodes = document.body.getElementsByTagName('*');
  const candidates = [];
  
  for (let node of allNodes) {
    // 1. Is it visible?
    if (node.offsetParent === null) continue;
    
    // 2. Does it look like a price? (Check for $ OR £)
    const text = node.innerText;
    // UPDATED CHECK: Looks for Dollar ($) OR Pound (£)
    if (text && (text.includes('$') || text.includes('£')) && text.length < 20) {
      
      // 3. THE MAGIC: Get Visual Metrics (Not DOM Tree)
      const rect = node.getBoundingClientRect();
      const style = window.getComputedStyle(node);
      
      candidates.push({
        text: text.trim(),
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        fontSize: parseFloat(style.fontSize), 
        color: style.color,
        tag: node.tagName
      });
    }
  }
  return candidates;
})();
"

# Run the JS and get the result back into R
result <- b$Runtime$evaluate(js_visual_scan, returnByValue = TRUE)
data_raw <- result$result$value

# Convert list to Tibble for analysis
df_candidates <- bind_rows(data_raw) %>% 
  # Filter out noise (hidden zeros, tiny text)
  filter(fontSize > 0, width > 0) %>% 
  distinct(text, x, y, .keep_all = TRUE)

# --- 3. THE "SELF-HEALING" HEURISTIC ---
# We don't care what the class name is. 
# We assume the "Real Price" is:
# A) In the top 800 pixels (Visible on load)
# B) Has the LARGEST font size among currency elements.

cat("Step 3: Applying Visual Logic...\n")

best_match <- df_candidates %>%
  filter(y < 800) %>%            # Must be in the 'Buy Box' area
  arrange(desc(fontSize)) %>%    # Sort by biggest font
  slice(1)                       # Take the winner

# --- 4. OUTPUT RESULTS ---

print("--- RAW CANDIDATES (What the robot saw) ---")
print(df_candidates %>% select(text, fontSize, x, y) %>% head(5))

print("--- FINAL DECISION (The 'Visual' Price) ---")
if(nrow(best_match) > 0) {
  cat(sprintf("Detected Price: %s\n", best_match$text))
  cat(sprintf("Confidence Reason: It was the largest price (Size: %spx) at position Y=%s\n", 
              best_match$fontSize, best_match$y))
} else {
  cat("No price detected visually.\n")
}

# Close the browser when done
# b$close()
