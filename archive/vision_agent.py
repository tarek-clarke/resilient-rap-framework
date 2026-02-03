import cv2
import torch
import numpy as np
import os

def detect_price_clusters(image_path):
    # Engage the 7900XT
    gpu_active = torch.cuda.is_available()
    device_name = torch.cuda.get_device_name(0) if gpu_active else "CPU"
    
    print(f"\n--- NPC Perception Engine ---")
    print(f"Hardware Acceleration: {device_name}")
    
    img = cv2.imread(image_path)
    if img is None:
        return "Error: Image not found."

    # Process using OpenCV
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mser = cv2.MSER_create()
    regions, _ = mser.detectRegions(gray)
    
    return {
        "device": device_name,
        "clusters_found": len(regions),
        "status": "Success"
    }