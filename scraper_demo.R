# PREREQUISITES:
# install.packages(c("chromote", "tidyverse", "jsonlite"))
# You must have Google Chrome installed on your machine.

library(chromote)
library(tidyverse)
library(jsonlite)

# --- CONFIGURATION ---
target_url <- "books.toscrape.com" # (Change to any product)

#target_url <- "https://www.amazon.ca/Nintendo-SwitchTM-Mario-KartTM-Bundle/dp/B0FC5FJZ9Z/ref=sr_1_5?crid=29PDC2HETQIA3&dib=eyJ2IjoiMSJ9.aWB7UsjDSpzvVxh4jhDCyH05Pa6sAKO9dPkCt_aOxu_kVYi__AsdYiFkGeYfmhXE7aRBG9n1FFUnPSlI2MOlRc4gZ4d_HlwLVFFfYyU_O3moBHbvBOE3sc_GpZd_FsbSoc0ih8PWWAeCRg0qnSyKFgx3KCsicoK_0ZCyLQx_412YhU5TXzvjbHyPpkqB4-n_HUV-3Wwb0HBhHQkbUCycpMzMtuTW2Kly5zGiEcHgh4BsPk9Tooe8HgUIKu5seWxfCTeoYudUgSjBiSjgrKYwRMDAYw5ga7Q-8Hrxo52c-3o.T6hcxH2vg6ZG-dHiqwgqHmVuicWC2VMbg_VIHZMZ8X4&dib_tag=se&keywords=nintendo+switch+2&qid=1767905629&sprefix=nintendo+switch+2%2Caps%2C123&sr=8-5" # Example: Nintendo Switch 2 (Change to any product)
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
Sys.sleep(3) # Extra wait for Amazon's dynamic price widgets to render

# --- 2. THE VISUAL EXTRACTION (The PhD Innovation) ---
# Instead of asking for ".a-price-whole" (which might change),
# We inject JavaScript to find elements based on how they LOOK.

cat("Step 2: Scanning visual layout...\n")

# This JS function finds all elements with a '$' and returns their Computed Styles
js_visual_scan <- "
(() => {
  const allNodes = document.body.getElementsByTagName('*');
  const candidates = [];
  
  for (let node of allNodes) {
    // 1. Is it visible?
    if (node.offsetParent === null) continue;
    
    // 2. Does it look like a price? (Regex match)
    // We check the direct text content of the node
    const text = node.innerText;
    if (text && text.includes('$') && text.length < 20) {
      
      // 3. THE MAGIC: Get Visual Metrics (Not DOM Tree)
      const rect = node.getBoundingClientRect();
      const style = window.getComputedStyle(node);
      
      candidates.push({
        text: text.trim(),
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        fontSize: parseFloat(style.fontSize), // Critical for visual hierarchy
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
# B) Has the LARGEST font size among dollar signs.

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

# Close the browser
# b$close()