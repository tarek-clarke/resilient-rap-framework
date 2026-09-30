#!/usr/bin/env python3
"""LLM-driven chaos planning helpers.

This module keeps runtime chaos injection lightweight by querying an LLM once
for a reusable stochastic plan, then sampling locally at packet rate.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple


@dataclass
class LLMChaosPlan:
    """Reusable plan for packet-level fault sampling."""

    mode_weights: Dict[str, float] = field(default_factory=dict)
    schema_suffixes: List[str] = field(default_factory=lambda: ["_v2", "_new", "_alt", "_canbus", "_raw"])
    string_tokens: List[str] = field(default_factory=lambda: ["OVERHEAT", "ERR_DECODE", "NaN_text", "---"])
    high_flip_range: Tuple[float, float] = (100.0, 1000.0)
    low_flip_range: Tuple[float, float] = (10.0, 100.0)
    source: str = "default"


_DEFAULT_PROFILE_PRESETS = {
    "balanced": {
        "weights": None,
        "schema_suffixes": ["_v2", "_new", "_alt", "_canbus", "_raw"],
        "string_tokens": ["OVERHEAT", "ERR_DECODE", "NaN_text", "---"],
        "high_flip_range": (100.0, 1000.0),
        "low_flip_range": (10.0, 100.0),
    },
    "aggressive": {
        "weights": {
            "schema_drift": 0.36,
            "string_in_numeric": 0.24,
            "bit_flip_high": 0.18,
            "bit_flip_low": 0.10,
            "sensor_dropout": 0.06,
            "duplicate_timestamp": 0.04,
            "null_value": 0.02,
        },
        "schema_suffixes": ["_v9", "_corrupt", "_shadow", "_legacy", "_raw", "_broken"],
        "string_tokens": ["INVALID_SCHEMA", "BERT_FAIL", "DRIFT_EXCEEDED", "NULLPTR", "@@@"],
        "high_flip_range": (250.0, 5000.0),
        "low_flip_range": (50.0, 500.0),
    },
}


class LLMChaosPlanner:
    """Creates fault-distribution plans from a local lightweight model (e.g. Gemma)."""

    def __init__(
        self,
        model: str = "gemma-4-e4b-it",
        endpoint: str = "http://localhost:11434/api/generate",
        timeout_ms: int = 8000,
        temperature: float = 0.7,
    ) -> None:
        self.model = model
        self.endpoint = endpoint
        self.timeout_ms = max(200, int(timeout_ms))
        self.temperature = float(temperature)

    def build_plan(self, profile: str, modes: Sequence[str], sensors: Sequence[str]) -> LLMChaosPlan:
        default = self._default_plan(profile, modes)
        prompt = self._build_prompt(profile=profile, modes=modes, sensors=sensors)
        try:
            output = self._query_llm(prompt)
            data = self._parse_json(output)
            plan = self._coerce_plan(data, modes)
            plan.source = "llm"
            return plan
        except Exception:
            return default

    @staticmethod
    def _uniform_weights(modes: Sequence[str]) -> Dict[str, float]:
        if not modes:
            return {}
        w = 1.0 / float(len(modes))
        return {m: w for m in modes}

    def _build_prompt(self, profile: str, modes: Sequence[str], sensors: Sequence[str]) -> str:
        mode_text = ", ".join(modes)
        sensor_text = ", ".join(sensors[:10])
        aggressiveness = (
            "Favor adversarial, hard-to-reconcile corruption that stresses semantic matching and BERT-like repair."
            if profile.lower() == "aggressive"
            else "Keep the plan realistic and representative of mixed telemetry faults."
        )
        return (
            "You are generating a chaos-injection plan for telemetry stress testing. "
            "Return strictly valid JSON only. No markdown.\n"
            "Use these allowed modes: " + mode_text + ".\n"
            f"Chaos profile: {profile}.\n"
            f"Sensor examples: {sensor_text}.\n"
            f"Profile guidance: {aggressiveness}\n"
            "JSON schema:\n"
            "{"
            "\"mode_weights\": {\"mode\": number},"
            "\"schema_suffixes\": [string],"
            "\"string_tokens\": [string],"
            "\"high_flip_range\": [number, number],"
            "\"low_flip_range\": [number, number]"
            "}\n"
            "Rules: mode_weights keys must be subset of allowed modes; weights positive; "
            "ranges must be [min,max] with min<max; keep values realistic for chaos testing."
        )

    def _default_plan(self, profile: str, modes: Sequence[str]) -> LLMChaosPlan:
        preset = _DEFAULT_PROFILE_PRESETS.get(profile.lower(), _DEFAULT_PROFILE_PRESETS["balanced"])
        weights = preset.get("weights")
        if weights is None:
            weights = self._uniform_weights(modes)
        else:
            weights = {m: float(weights[m]) for m in modes if m in weights}
            if not weights:
                weights = self._uniform_weights(modes)
            total = sum(weights.values()) or 1.0
            weights = {k: v / total for k, v in weights.items()}

        return LLMChaosPlan(
            mode_weights=weights,
            schema_suffixes=list(preset["schema_suffixes"]),
            string_tokens=list(preset["string_tokens"]),
            high_flip_range=tuple(preset["high_flip_range"]),
            low_flip_range=tuple(preset["low_flip_range"]),
            source="default",
        )

    def _query_llm(self, prompt: str) -> str:
        endpoint_lower = self.endpoint.lower()
        if "/api/generate" in endpoint_lower:
            return self._query_ollama(prompt)
        if endpoint_lower.endswith(":1234") or "/v1" in endpoint_lower:
            return self._query_openai_compatible(prompt)
        # Default to OpenAI-compatible for generic endpoints.
        return self._query_openai_compatible(prompt)

    def _query_ollama(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": self.temperature},
        }
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_ms / 1000.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return str(body.get("response", "")).strip()

    def _query_openai_compatible(self, prompt: str) -> str:
        endpoint = self.endpoint.rstrip("/")
        endpoint_lower = endpoint.lower()

        if endpoint_lower.endswith("/v1"):
            endpoint = endpoint + "/chat/completions"
        elif endpoint_lower.endswith("/v1/"):
            endpoint = endpoint + "chat/completions"
        elif "://" in endpoint and "/" not in endpoint.split("://", 1)[1]:
            endpoint = endpoint + "/v1/chat/completions"

        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # LM Studio accepts dummy key when API auth is disabled.
                "Authorization": "Bearer lm-studio",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self.timeout_ms / 1000.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        choices = body.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, list):
            # Some servers return multi-part content blocks.
            return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict)).strip()
        return str(content).strip()

    @staticmethod
    def _parse_json(raw: str) -> dict:
        if not raw:
            raise ValueError("Empty LLM response")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    def _coerce_plan(self, data: dict, modes: Sequence[str]) -> LLMChaosPlan:
        allowed = set(modes)
        raw_weights = data.get("mode_weights") or {}
        cleaned_weights: Dict[str, float] = {}
        for k, v in raw_weights.items():
            if k in allowed:
                try:
                    val = float(v)
                    if val > 0:
                        cleaned_weights[k] = val
                except Exception:
                    continue
        if not cleaned_weights:
            return self._default_plan(data.get("profile", "balanced"), modes)
        total = sum(cleaned_weights.values()) or 1.0
        cleaned_weights = {k: v / total for k, v in cleaned_weights.items()}

        suffixes = [str(x).strip() for x in (data.get("schema_suffixes") or []) if str(x).strip()]
        tokens = [str(x).strip() for x in (data.get("string_tokens") or []) if str(x).strip()]
        if not suffixes:
            suffixes = ["_v2", "_new", "_alt", "_canbus", "_raw"]
        if not tokens:
            tokens = ["OVERHEAT", "ERR_DECODE", "NaN_text", "---"]

        high_range = self._coerce_range(data.get("high_flip_range"), (100.0, 1000.0))
        low_range = self._coerce_range(data.get("low_flip_range"), (10.0, 100.0))

        return LLMChaosPlan(
            mode_weights=cleaned_weights,
            schema_suffixes=suffixes,
            string_tokens=tokens,
            high_flip_range=high_range,
            low_flip_range=low_range,
        )

    @staticmethod
    def _coerce_range(raw: object, default: Tuple[float, float]) -> Tuple[float, float]:
        if isinstance(raw, list) and len(raw) == 2:
            try:
                lo = float(raw[0])
                hi = float(raw[1])
                if lo < hi:
                    return (lo, hi)
            except Exception:
                pass
        return default
