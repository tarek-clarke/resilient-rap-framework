library(targets)
library(reticulate)

# Define the research step
list(
  tar_target(
    website_screenshot,
    capture_site("https://example-ecommerce.com"),
    format = "file"
  ),
  
  tar_target(
    visual_extraction,
    {
      # Call the Python agent inside the ROCm container
      source_python("vision_agent.py")
      detect_price_clusters(website_screenshot)
    }
  ),
  
  tar_target(
    signed_data,
    {
      # Dr. Clarke's Aegis Principle: Sign the data immediately
      digest::digest(visual_extraction, algo = "sha256")
    }
  )
)