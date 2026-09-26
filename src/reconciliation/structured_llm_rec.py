import json
import time
import re
from typing import Dict, List, Tuple
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

class StructuredLLMReconciler:
    def __init__(self, hardware_profile: str = "cpu", batch_size: int = 4, llm_manager=None,
                 model_env: str = "QWEN_MODEL_ID", default_model_id: str = "Qwen/Qwen2.5-1.5B-Instruct",
                 max_new_tokens: int = 64):
        self.batch_size = batch_size
        self.hardware_profile = hardware_profile
        self._llm = llm_manager
        self._own_manager = llm_manager is None
        self.model_env = model_env
        self.default_model_id = default_model_id
        self.max_new_tokens = max_new_tokens

    def _get_manager(self):
        if self._llm is None:
            from ..inference.llm_manager import LLMManager
            import os as _os
            model_id = _os.environ.get(self.model_env, _os.environ.get("HF_MODEL_ID", self.default_model_id))
            device = "cuda" if self.hardware_profile in ("cuda", "rocm") else "mps" if self.hardware_profile == "silicon" else "cpu"
            self._llm = LLMManager(
                model_id=model_id,
                device=device,
                load_in_4bit=_os.environ.get("HF_LOAD_4BIT", "").lower() in ("1", "true", "yes"),
                load_in_8bit=_os.environ.get("HF_LOAD_8BIT", "").lower() in ("1", "true", "yes"),
            )
        if not self._llm.is_loaded:
            # LLMManager instances are shared by model ID; oracle passes
            # deliberately unload them between methods to cap VRAM use.
            if not self._llm.load():
                raise RuntimeError(f"Failed to load local LLM: {self.default_model_id}")
        return self._llm

    @staticmethod
    def _clean_output(text: str) -> str:
        """Remove presentation wrappers without accepting arbitrary prose."""
        text = re.sub(r'<\|think\|>.*?<\|/think\|>', '', text, flags=re.DOTALL)
        text = re.sub(r'```(?:json)?\s*', '', text)
        return re.sub(r'```', '', text).strip()

    @staticmethod
    def _field_spec(data: Dict) -> List[Dict[str, object]]:
        return [
            {"i": index, "name": str(name), "type": type(value).__name__}
            for index, (name, value) in enumerate(data.items())
        ]

    def _mapping_messages(self, original: Dict, drifted: Dict) -> List[Dict[str, str]]:
        """Return a compact, machine-verifiable schema-mapping request.

        Explicit source/target index pairs remain unambiguous if a small model
        omits one source.  A positional array cannot identify the omitted
        position and would shift every subsequent mapping.
        """
        original_spec = json.dumps(self._field_spec(original), separators=(",", ":"))
        drifted_spec = json.dumps(self._field_spec(drifted), separators=(",", ":"))
        return [{
            "role": "user",
            "content": (
                "Match each original schema field to at most one drifted schema field.\n"
                f"ORIGINAL_FIELDS={original_spec}\n"
                f"DRIFTED_FIELDS={drifted_spec}\n"
                f"Return ONLY a valid JSON array containing exactly {len(original)} pairs, "
                "one for every ORIGINAL_FIELDS index in ascending order. "
                "Each pair must be [original_index,drifted_index]. Use null as the "
                "drifted_index when no match exists. Example for three original fields: "
                "[[0,2],[1,null],[2,0]]. Drifted indices must be unique. Do not return "
                "field names, objects, Markdown, explanations, or placeholder text."
            ),
        }]

    def _token_budget(self, original: Dict) -> int:
        """Provide enough room for wide schemas without permitting long prose."""
        return max(self.max_new_tokens, min(256, 16 + 8 * len(original)))

    def _parse_index_mapping(
        self,
        text: str,
        original: Dict,
        drifted: Dict,
    ) -> Tuple[List[Tuple[str, str]], List[str], bool, bool]:
        source_keys = list(original.keys())
        target_keys = list(drifted.keys())
        cleaned = self._clean_output(text)
        array_start = cleaned.find("[")
        array_end = cleaned.rfind("]")
        if array_start < 0 or array_end < array_start:
            return [], source_keys, False, False
        try:
            indices = json.loads(cleaned[array_start:array_end + 1])
        except json.JSONDecodeError:
            return [], source_keys, False, False
        if not isinstance(indices, list):
            return [], source_keys, False, False

        # Canonical format: explicit [source_index, target_index] pairs.  The
        # legacy positional format is still accepted for archived model tests,
        # but only when its length is exact because shorter positional output
        # cannot identify which source was omitted.
        explicit_pairs = bool(indices) and all(
            isinstance(item, list) and len(item) == 2 for item in indices
        )
        if explicit_pairs:
            assignments = indices
        elif len(indices) == len(source_keys):
            assignments = [[source_index, target_index]
                           for source_index, target_index in enumerate(indices)]
        else:
            return [], source_keys, False, False

        used_sources = set()
        used_targets = set()
        mapped: List[Tuple[str, str]] = []
        unmapped_indices = set(range(len(source_keys)))
        mapping_valid = True
        for source_index, target_index in assignments:
            if (
                isinstance(source_index, bool)
                or not isinstance(source_index, int)
                or source_index < 0
                or source_index >= len(source_keys)
                or source_index in used_sources
            ):
                mapping_valid = False
                continue
            used_sources.add(source_index)
            source = source_keys[source_index]
            if target_index is None:
                continue
            if (
                isinstance(target_index, bool)
                or not isinstance(target_index, int)
                or target_index < 0
                or target_index >= len(target_keys)
                or target_index in used_targets
            ):
                mapping_valid = False
                continue
            used_targets.add(target_index)
            unmapped_indices.discard(source_index)
            mapped.append((source, target_keys[target_index]))
        if len(used_sources) != len(source_keys):
            mapping_valid = False
        unmapped = [source_keys[index] for index in sorted(unmapped_indices)]
        # Preserve partial mappings so a low-quality LLM response is measured
        # rather than aborting the entire oracle sweep.
        return mapped, unmapped, True, mapping_valid

    def _infer(self, original: Dict, drifted: Dict) -> Dict[str, str]:
        manager = self._get_manager()
        if not manager or not manager.is_loaded:
            return {}

        messages = self._mapping_messages(original, drifted)
        response = manager.generate_response(
            messages,
            max_new_tokens=self._token_budget(original),
            temperature=0.0,
            top_p=1.0,
            json_array_only=True,
        )
        mapped, _, output_valid, _mapping_valid = self._parse_index_mapping(
            response, original, drifted
        )
        return dict(mapped) if output_valid else {}

    def reconcile_batch(self, pairs: List[Tuple[Dict, Dict]], progress_cb=None) -> List[Dict]:
        manager = self._get_manager()
        if not manager or not manager.is_loaded:
            raise RuntimeError(f"Local LLM is not loaded: {self.default_model_id}")

        start = time.perf_counter()
        results = []
        total = len(pairs)
        coerced_pairs = []
        for orig, drift in pairs:
            if isinstance(orig, list):
                orig = {str(i): v for i, v in enumerate(orig)}
            elif not isinstance(orig, dict):
                orig = {}
            if isinstance(drift, list):
                drift = {str(i): v for i, v in enumerate(drift)}
            elif not isinstance(drift, dict):
                drift = {}
            coerced_pairs.append((orig, drift))
        pairs = coerced_pairs
        
        # Sub-batching into self.batch_size chunks for GPU batch generation
        chunk_size = max(1, self.batch_size)
        for chunk_idx in range(0, total, chunk_size):
            chunk_pairs = pairs[chunk_idx:chunk_idx + chunk_size]
            batch_messages = [
                self._mapping_messages(orig, drift) for orig, drift in chunk_pairs
            ]

            chunk_token_budget = max(
                self._token_budget(orig) for orig, _drift in chunk_pairs
            )
            responses = manager.generate_batch_responses(
                batch_messages,
                max_new_tokens=chunk_token_budget,
                temperature=0.0,
                top_p=1.0,
                json_array_only=True,
            )

            response_texts = [
                responses[offset] if offset < len(responses) else ""
                for offset in range(len(chunk_pairs))
            ]
            parsed = [
                self._parse_index_mapping(response_texts[offset], orig, drift)
                for offset, (orig, drift) in enumerate(chunk_pairs)
            ]
            retried = [False] * len(chunk_pairs)

            # Retry all invalid records together.  The former per-record retry
            # loop serialized thousands of accelerator calls on sparse-drift
            # streams and dominated the eight-hour wall-clock budget.
            for _attempt in range(2):
                invalid_offsets = [
                    offset
                    for offset, (_mapped, _unmapped, output_valid, mapping_valid)
                    in enumerate(parsed)
                    if not output_valid or not mapping_valid
                ]
                if not invalid_offsets:
                    break
                retry_batches = []
                for offset in invalid_offsets:
                    orig, _drift = chunk_pairs[offset]
                    retried[offset] = True
                    retry_batches.append([{
                        "role": "user",
                        "content": (
                            batch_messages[offset][0]["content"]
                            + f"\nThe prior response failed validation. Return exactly "
                            f"{len(orig)} [original_index,drifted_index] pairs, covering "
                            f"original indices 0 through {max(0, len(orig) - 1)} exactly once, "
                            "using only integers, null, commas, and brackets."
                        ),
                    }])
                retry_responses = manager.generate_batch_responses(
                    retry_batches,
                    max_new_tokens=max(
                        self._token_budget(chunk_pairs[offset][0])
                        for offset in invalid_offsets
                    ),
                    temperature=0.0,
                    top_p=1.0,
                    json_array_only=True,
                )
                for retry_index, offset in enumerate(invalid_offsets):
                    orig, drift = chunk_pairs[offset]
                    response_texts[offset] = (
                        retry_responses[retry_index]
                        if retry_index < len(retry_responses) else ""
                    )
                    parsed[offset] = self._parse_index_mapping(
                        response_texts[offset], orig, drift
                    )

            for offset, (orig, _drift) in enumerate(chunk_pairs):
                idx = chunk_idx + offset
                if progress_cb:
                    progress_cb(idx, total)
                mapped, unmapped, output_valid, mapping_valid = parsed[offset]
                if not output_valid:
                    preview = self._clean_output(response_texts[offset])[:160]
                    print(
                        f"[LLM] Invalid indexed mapping after retries: {preview!r}",
                        flush=True,
                    )
                elif not mapping_valid:
                    print(
                        "[LLM] Indexed JSON was valid but mapping constraints "
                        "were violated after retries; recording partial accuracy",
                        flush=True,
                    )
                accuracy = len(mapped) / len(orig.keys()) if orig.keys() else 0.0
                results.append({
                    "accuracy": accuracy,
                    "latency_ms": 0.0,
                    "mapped_fields": mapped,
                    "unmapped_fields": unmapped,
                    "batch_size": self.batch_size,
                    "structured_output_valid": output_valid,
                    "structured_mapping_valid": mapping_valid,
                    "structured_output_retried": retried[offset],
                })

        total_time = (time.perf_counter() - start) * 1000
        per_packet = total_time / len(pairs) if pairs else 0
        for r in results:
            r["latency_ms"] = per_packet
        return results

    def reconcile(self, original: Dict, drifted: Dict) -> Dict:
        return self.reconcile_batch([(original, drifted)])[0]

    def __del__(self):
        if self._own_manager and self._llm:
            self._llm.unload()
