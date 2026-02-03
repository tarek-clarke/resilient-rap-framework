# ==============================================================================
# PhD RESEARCH PROTOTYPE: Vision-Based Self-Healing Scraper
# Author: Tarek Clarke
# Context: Proposed "Resilient RAP" for Official Statistics
# ==============================================================================

# PREREQUISITES:
# install.packages(c("chromote", "tidyverse", "jsonlite", "digest"))

library(chromote)
library(tidyverse)
library(jsonlite)
library(digest) # Added for "Tamper-Evidence" (Clarke et al.)

# --- CONFIGURATION ---
target_url <- "http://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
user_agent <- "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Initialize "Robot Browser"
b <- ChromoteSession$new()
b$Network$setUserAgentOverride(userAgent = user_agent)

cat("\n[1] INITIALIZING AGENT...\n")
cat(sprintf("    Target: %s\n", target_url))
b$Page$navigate(target_url)
b$Page$loadEventFired()
Sys.sleep(2) 

# ==============================================================================
# STEP 1: SIMULATE LEGACY FAILURE (Schema Drift)
# ==============================================================================
# We simulate a "Brittle Pipeline" failure where the CSS class has changed.
# This justifies the need for the "Self-Healing" agent.
# ==============================================================================

cat("\n[2] ATTEMPTING LEGACY EXTRACTION (CSS Selectors)...\n")
legacy_selector <- ".old-price-class-v1" # This simulates a broken selector

# Try to find the element (This will fail)
js_check <- sprintf("document.querySelector('%s') ? document.querySelector('%s').innerText : null", legacy_selector, legacy_selector)
legacy_result <- b$Runtime$evaluate(js_check)$result$value

if (is.null(legacy_result)) {
  cat("    [!] CRITICAL FAILURE: Schema Drift Detected.\n")
  cat("    [!] Legacy selector (.old-price-class-v1) no longer exists.\n")
  cat("    [>] ACTIVATING AUTONOMOUS VISION AGENT (NPC Logic)...\n")
} else {
  stop("Unexpected success - Demo meant to simulate failure.")
}

# ==============================================================================
# STEP 2: VISUAL STIMULI PERCEPTION (The "NPC" Innovation)
# ==============================================================================
# Instead of DOM tree parsing, we extract "Visual Affordances" (Gibson/Gittens).
# We look for "Dominant Stimuli": Largest text, Currency Symbols, Visibility.
# ==============================================================================

cat("\n[3] SCANNING VISUAL LANDSCAPE...\n")

js_visual_scan <- "
(() => {
  const allNodes = document.body.getElementsByTagName('*');
  const candidates = [];
   
  for (let node of allNodes) {
    // 1. Visuospatial Filter: Is it actually visible to a human?
    if (node.offsetParent === null) continue;
    
    // 2. Stimulus Check: Does it contain a currency symbol?
    const text = node.innerText;
    if (text && (text.includes('$') || text.includes('£')) && text.length < 20) {
       
      // 3. Affordance Extraction: Get Visual Metrics
      const rect = node.getBoundingClientRect();
      const style = window.getComputedStyle(node);
       
      candidates.push({
        text: text.trim(),
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        fontSize: parseFloat(style.fontSize), 
        fontWeight: style.fontWeight,
        tag: node.tagName
      });
    }
  }
  return candidates;
})();
"

result <- b$Runtime$evaluate(js_visual_scan, returnByValue = TRUE)
df_stimuli <- bind_rows(result$result$value) %>% 
  filter(fontSize > 0, width > 0) %>% 
  distinct(text, x, y, .keep_all = TRUE)

print(head(df_stimuli))

# ==============================================================================
# STEP 3: DECISION TREE HEURISTIC (Self-Healing)
# ==============================================================================
# The agent decides which stimulus is the "Price" based on a weighted 
# probability of Font Size (Hierarchy) and Position (Buy Box).
# ==============================================================================

cat("\n[4] EXECUTING DECISION LOGIC...\n")

best_match <- df_stimuli %>%
  # Heuristic 1: Position (Must be in top viewport 'Buy Box')
  filter(y < 900) %>% 
  # Heuristic 2: Visual Hierarchy (Price is usually the dominant/largest font)
  arrange(desc(fontSize)) %>% 
  slice(1)

if(nrow(best_match) > 0) {
  cat(sprintf("    [+] HEALING SUCCESSFUL. \n"))
  cat(sprintf("    [+] Detected Price: %s\n", best_match$text))
  cat(sprintf("    [+] Decision Reason: Dominant visual stimulus (Size: %spx) at Y=%s\n", 
              best_match$fontSize, best_match$y))
  
  # ==============================================================================
  # STEP 4: DATA PROVENANCE (The "Clarke" Integrity Check)
  # ==============================================================================
  # We generate a cryptographic hash of the data + timestamp + source.
  # This creates the "Tamper-Evident" audit trail required for Official Stats.
  # ==============================================================================
  
  audit_log <- list(
    value = best_match$text,
    timestamp = Sys.time(),
    source_heuristic = "Visual_Dominance_v1",
    url = target_url
  )
  
  # Create SHA-256 Hash
  integrity_token <- digest(audit_log, algo = "sha256")
  
  cat("\n[5] GENERATING AUDIT TRAIL (Tamper-Evidence)...\n")
  cat(sprintf("    [#] Integrity Token: %s\n", integrity_token))
  cat("    [#] Data locked and ready for ingestion.\n")
  
} else {
  cat("    [-] No price detected visually.\n")
}

# b$close()
