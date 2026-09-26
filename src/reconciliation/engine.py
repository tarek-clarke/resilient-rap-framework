from typing import Dict, List, Tuple
from .levenshtein_rec import LevenshteinReconciler
from .regex_rec import RegexReconciler
from .bert_rec import BERTReconciler
from .structured_llm_rec import StructuredLLMReconciler
from .semantic_reconcilers import (
    BGEReconciler,
    CohereEmbedV4Reconciler,
    CrossEncoderReconciler,
    SchemaRegistryReconciler,
)

class ReconciliationEngine:
    def __init__(self, hardware_profile: str = "cpu", batch_size: int = 4):
        self.batch_size = batch_size
        self.reconcilers = {
            "levenshtein": LevenshteinReconciler(),
            "regex": RegexReconciler(),
            "schema_registry": SchemaRegistryReconciler(),
        }
        self._factories = {
            "minilm": lambda: BERTReconciler(hardware_profile, batch_size),
            "qwen_1_5b": lambda: StructuredLLMReconciler(hardware_profile, batch_size, model_env="QWEN_MODEL_ID", default_model_id="Qwen/Qwen2.5-1.5B-Instruct"),
            "bge": lambda: BGEReconciler(hardware_profile, batch_size),
            "cohere_embed_v4": lambda: CohereEmbedV4Reconciler(hardware_profile, batch_size),
            "cross_encoder": lambda: CrossEncoderReconciler(hardware_profile, batch_size),
        }

    def reconcile(self, original: Dict, drifted: Dict, method: str) -> Dict:
        if method not in self.reconcilers and method in self._factories:
            self.reconcilers[method] = self._factories[method]()
        if method not in self.reconcilers:
            raise ValueError(f"Unknown method: {method}")

        reconciler = self.reconcilers[method]

        original_data = original.get("data", {})
        drifted_data = drifted.get("data", {})

        result = reconciler.reconcile(original_data, drifted_data)

        return {
            "method": method,
            "accuracy": result["accuracy"],
            "latency_ms": result["latency_ms"],
            "mapped_fields": result["mapped_fields"],
            "unmapped_fields": result["unmapped_fields"],
            "batch_size": self.batch_size
        }

    def reconcile_bert_batch(self, pairs: List[Tuple[Dict, Dict]]) -> List[Dict]:
        bert = self.reconcilers.get("minilm")
        if bert is None:
            self.reconcilers["minilm"] = self._factories["minilm"]()
            bert = self.reconcilers["minilm"]
        if bert and hasattr(bert, "reconcile_batch"):
            return bert.reconcile_batch(pairs)
        return [
            self.reconcile({"data": orig}, {"data": drift}, "minilm")
            for orig, drift in pairs
        ]

    def reconcile_levenshtein_batch(self, pairs: List[Tuple[Dict, Dict]]) -> List[Dict]:
        lev = self.reconcilers.get("levenshtein")
        if lev and hasattr(lev, "reconcile_batch"):
            return lev.reconcile_batch(pairs)
        return [
            self.reconcile({"data": orig}, {"data": drift}, "levenshtein")
            for orig, drift in pairs
        ]

    def reconcile_llm_batch(self, method: str, pairs: List[Tuple[Dict, Dict]], progress_cb=None) -> List[Dict]:
        if method not in self.reconcilers and method in self._factories:
            self.reconcilers[method] = self._factories[method]()
        llm = self.reconcilers.get(method)
        if llm and hasattr(llm, "reconcile_batch"):
            return llm.reconcile_batch(pairs, progress_cb=progress_cb)
        return [
            self.reconcile({"data": orig}, {"data": drift}, method)
            for orig, drift in pairs
        ]

    def release_method(self, method: str) -> None:
        """Unload a model and release accelerator memory after its full pass."""
        reconciler = self.reconcilers.pop(method, None)
        manager = getattr(reconciler, "_llm", None)
        if manager is not None:
            manager.unload()
        model = getattr(reconciler, "model", None)
        if model is not None:
            try:
                del model
                reconciler.model = None
            except Exception:
                pass
        try:
            import gc
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                if hasattr(torch.cuda, "ipc_collect"):
                    torch.cuda.ipc_collect()
        except Exception:
            pass

    def reconcile_semantic_batch(self, method: str, pairs: List[Tuple[Dict, Dict]]) -> List[Dict]:
        if method not in self.reconcilers and method in self._factories:
            self.reconcilers[method] = self._factories[method]()
        if method not in self.reconcilers:
            raise ValueError(f"Unknown semantic method: {method}")
        reconciler = self.reconcilers[method]
        if hasattr(reconciler, "reconcile_batch"):
            return reconciler.reconcile_batch(pairs)
        return [self.reconcile({"data": orig}, {"data": drift}, method) for orig, drift in pairs]
