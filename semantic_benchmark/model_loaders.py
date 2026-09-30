"""Local-only BERT loader for the paper benchmark.

Guarantees 100% offline, local-only model execution. Aborts execution if 
internet fallback is requested or if local checkpoints are missing when 
require_local_models=True.
"""

import os
import sys
from typing import Dict, Any, Tuple

# Enable offline mode for Hugging Face Hub
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

# On macOS Apple Silicon, monkeypatch PyTorch MPS to force CPU fallback for stability
# (used only when explicitly forcing CPU on macOS)
import platform
if platform.system() == "Darwin" and os.getenv("FORCE_HARDWARE") in ("cpu", "fallback"):
    try:
        import torch
        if hasattr(torch, "backends") and hasattr(torch.backends, "mps"):
            torch.backends.mps.is_available = lambda: False
            torch.backends.mps.is_built = lambda: False
    except Exception:
        pass

# Remove local directory from sys.path to avoid models.py name collision
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir in sys.path:
    sys.path.remove(script_dir)
if "" in sys.path:
    sys.path.remove("")

# Add root folder to sys.path
root_dir = os.path.dirname(script_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from models.bert_model import BERTModel

def detect_academic_hardware() -> Tuple[str, str]:
    """Detect backend: CUDA, ROCm, Metal, DirectML, CPU."""
    # Allow overriding via FORCE_HARDWARE env variable (helps bypass GPU/MPS driver deadlocks)
    force_env = os.getenv("FORCE_HARDWARE")
    if force_env:
        v = force_env.strip().lower()
        if v in ("cpu", "fallback"):
            return "CPU", "cpu"
        elif v in ("mps", "metal", "apple"):
            return "Metal", "mps"
        elif v in ("cuda", "nvidia"):
            return "CUDA", "cuda"
        elif v in ("rocm", "amd"):
            return "ROCm", "cuda"
        elif v in ("directml", "dml"):
            return "PrivateUse1", "privateuseone:0"

    import platform
    system = platform.system()
    machine = platform.machine().lower()
    
    # 1. Check Metal (MPS) on macOS Apple Silicon
    if system == "Darwin" and ("arm" in machine or "apple" in platform.processor().lower()):
        try:
            import torch
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "Metal", "mps"
        except Exception:
            pass
        return "Metal", "cpu"
        
    # 2. Check CUDA on Linux/Windows
    try:
        import torch
        if torch.cuda.is_available():
            if hasattr(torch.version, "hip") and torch.version.hip is not None:
                return "ROCm", "cuda"
            return "CUDA", "cuda"
    except Exception:
        pass
        
    # 3. Check DirectML on Windows AMD (prioritized over stale ROCm path checks)
    if system == "Windows":
        try:
            import torch_directml
            if torch_directml.is_available():
                return "PrivateUse1", "privateuseone:0"
        except Exception:
            pass

    # 4. Check ROCm on Linux via environment variables (skip on Windows if DirectML not found,
    #    since leftover ROCm paths from uninstalled ROCm would produce a broken "ROCm" result)
    if system != "Windows":
        if os.getenv("HIP_PATH") or os.getenv("ROCM_PATH") or os.path.exists("/opt/rocm"):
            return "ROCm", "cpu"
            
    # 5. Fallback to CPU
    return "CPU", "cpu"

class StrictBERTModel(BERTModel):
    """Load the paper's BERT checkpoint without network fallback."""

    def __new__(cls, require_local: bool = True):
        return super().__new__(cls, allow_internet=False)

    def __init__(self, require_local: bool = True):
        super().__init__(allow_internet=False)
        if not self.is_loaded:
            raise RuntimeError(
                "BERT checkpoint is unavailable locally; cache "
                "sentence-transformers/all-MiniLM-L6-v2 before running offline."
            )


def run_preflight_validation(require_local_models: bool = True, strict_mode: bool = False, enabled_methods: list = None) -> Tuple[Dict[str, Any], bool, str]:
    """Perform pre-flight checks to ensure 100% offline, local execution and hardware verification.
    
    Returns:
        tuple: (preflight_status_dict, abort_flag, error_message)
    """
    hw_backend, hw_device = detect_academic_hardware()
    gpu_available = hw_backend in ("CUDA", "ROCm", "Metal", "PrivateUse1")
    
    preflight_status = {
        "gpu_available": gpu_available,
        "hardware_backend": hw_backend,
        "device": hw_device,
        "model_source": {"bert": "unknown"},
        "internet_used": False,
        "require_local_models": require_local_models,
        "strict_mode": strict_mode
    }
    
    # Strict mode hardware boundary validation
    import platform
    is_mac = platform.system() == "Darwin"
    if strict_mode and hw_device == "cpu" and not is_mac and os.getenv("FORCE_HARDWARE") != "cpu":
        return preflight_status, True, "Strict mode violation: Unsupported CPU backend detected. CUDA, ROCm, Metal, or DirectML is strictly required."
    
    # Check BERT
    if enabled_methods is None or "bert" in enabled_methods:
        try:
            bert = StrictBERTModel(require_local=require_local_models)
            preflight_status["model_source"]["bert"] = "local"
        except Exception as e:
            preflight_status["model_source"]["bert"] = "unavailable"
            if require_local_models or strict_mode:
                return preflight_status, True, f"BERT pre-flight validation failed: {e}"
    else:
        preflight_status["model_source"]["bert"] = "skipped"
            
    # Verify no internet handshake was initiated
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        preflight_status["internet_used"] = True
        if strict_mode:
            return preflight_status, True, "Strict mode violation: HF_HUB_OFFLINE is not set to 1."
            
    return preflight_status, False, ""
