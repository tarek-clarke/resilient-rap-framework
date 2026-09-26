import os
import sys
import platform
import threading
from typing import Any, Dict, List, Optional, Iterator, Union
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

def _detect_device() -> str:
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _resolve_dtype(requested: str, device: str):
    import torch
    if requested == "auto":
        if device == "cuda":
            return torch.bfloat16
        elif device == "mps":
            return torch.float16
        else:
            return torch.float32
    mapping = {
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
        "float32": torch.float32,
    }
    return mapping.get(requested, torch.bfloat16 if device == "cuda" else torch.float32)


def _resolve_attn(requested: str, model_id: str, device: str) -> Optional[str]:
    if requested == "auto":
        return "eager"
    if requested.lower() == "none":
        return None
    return requested


class LLMManager:
    _instances: Dict[str, "LLMManager"] = {}
    _lock = threading.Lock()

    def __new__(cls, model_id: Optional[str] = None, **kwargs):
        key = model_id or os.environ.get("HF_MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct")
        with cls._lock:
            if key not in cls._instances:
                instance = super().__new__(cls)
                instance._key = key
                instance._initialized = False
                cls._instances[key] = instance
        return cls._instances[key]

    def __init__(self, model_id: Optional[str] = None, **kwargs):
        if getattr(self, "_initialized", False):
            return

        self.model_id = model_id or os.environ.get("HF_MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct")
        self.hf_token = kwargs.get("hf_token") or os.environ.get("HF_TOKEN", None)
        self.max_tokens = int(kwargs.get("max_reasoning_tokens") or os.environ.get("LLM_MAX_REASONING_TOKENS", "2048"))
        self.local_path = kwargs.get("local_model_path") or os.environ.get("HF_LOCAL_MODEL_PATH", None)
        self.load_in_4bit = kwargs.get("load_in_4bit") or os.environ.get("HF_LOAD_4BIT", "").lower() in ("1", "true", "yes")
        self.load_in_8bit = kwargs.get("load_in_8bit") or os.environ.get("HF_LOAD_8BIT", "").lower() in ("1", "true", "yes")

        self.device = kwargs.get("device") or _detect_device()
        self.torch_dtype = _resolve_dtype(
            kwargs.get("torch_dtype") or os.environ.get("HF_TORCH_DTYPE", "auto"),
            self.device
        )
        self.attn_impl = _resolve_attn(
            kwargs.get("attn_implementation") or os.environ.get("HF_ATTN_IMPL", "auto"),
            self.model_id, self.device
        )

        self.model = None
        self.tokenizer = None
        self._json_array_token_ids: Optional[List[int]] = None
        self.is_loaded = False
        self._initialized = True

        if not kwargs.get("lazy", False):
            self.load()

    def load(self) -> bool:
        if self.is_loaded:
            return True
        try:
            import torch
            from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

            model_path = self.local_path or self.model_id

            load_kwargs: Dict[str, Any] = {
                "dtype": self.torch_dtype,
                "trust_remote_code": True,
                "device_map": "auto" if self.device == "cuda" else "mps" if self.device == "mps" else "cpu",
            }

            if self.attn_impl:
                load_kwargs["attn_implementation"] = self.attn_impl

            quantized = False
            if self.load_in_4bit or self.load_in_8bit:
                try:
                    from transformers import BitsAndBytesConfig
                    if self.load_in_4bit:
                        load_kwargs["quantization_config"] = BitsAndBytesConfig(
                            load_in_4bit=True,
                            bnb_4bit_compute_dtype=torch.float16,
                            bnb_4bit_use_double_quant=True,
                        )
                    else:
                        load_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
                    load_kwargs["device_map"] = "auto"
                    quantized = True
                except Exception as e:
                    print(f"[LLM] Quantization unavailable ({e}), loading full precision")

            if self.hf_token:
                load_kwargs["token"] = self.hf_token

            mode = "4bit" if (self.load_in_4bit and quantized) else "8bit" if (self.load_in_8bit and quantized) else "full"
            print(f"[LLM] Loading {model_path} on {self.device} ({mode}, dtype={self.torch_dtype})")
            config = AutoConfig.from_pretrained(model_path, trust_remote_code=True)
            model_class = AutoModelForCausalLM
            if quantized:
                try:
                    self.model = model_class.from_pretrained(model_path, **load_kwargs)
                except Exception as e:
                    print(f"[LLM] 4/8-bit failed ({e}), retrying full precision...")
                    load_kwargs.pop("quantization_config", None)
                    load_kwargs["device_map"] = self.device if self.device != "mps" else "mps"
                    self.model = model_class.from_pretrained(model_path, **load_kwargs)
            else:
                self.model = model_class.from_pretrained(model_path, **load_kwargs)

            tok_kwargs = {"trust_remote_code": True}
            if self.hf_token:
                tok_kwargs["token"] = self.hf_token
            self.tokenizer = AutoTokenizer.from_pretrained(model_path, **tok_kwargs)
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token

            self.model.eval()
            self.is_loaded = True
            print(f"[LLM] Model loaded: {self.model_id} (device={self.model.device})")
            return True
        except Exception as e:
            print(f"[LLM] Failed to load model: {e}")
            self.is_loaded = False
            return False

    def generate_response(
        self,
        messages: List[Dict[str, str]],
        max_new_tokens: Optional[int] = None,
        temperature: float = 0.1,
        top_p: float = 0.8,
        do_sample: bool = False,
        json_array_only: bool = False,
    ) -> str:
        if not self.is_loaded:
            if not self.load():
                return ""

        try:
            import torch

            prompt = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self.tokenizer(prompt, return_tensors="pt")
            if self.device in ("cuda", "mps"):
                inputs = {k: v.to(self.model.device) for k, v in inputs.items()}

            gen_kwargs: Dict[str, Any] = {
                "max_new_tokens": max_new_tokens or 256,
                "do_sample": do_sample,
                "pad_token_id": self.tokenizer.pad_token_id,
                "eos_token_id": self.tokenizer.eos_token_id,
            }
            if do_sample:
                gen_kwargs["temperature"] = temperature
                gen_kwargs["top_p"] = top_p
            if json_array_only:
                gen_kwargs["prefix_allowed_tokens_fn"] = (
                    self._json_array_prefix_constraint(inputs["input_ids"].shape[1])
                )

            with torch.no_grad():
                outputs = self.model.generate(**inputs, **gen_kwargs)

            response = self.tokenizer.decode(
                outputs[0][inputs["input_ids"].shape[1]:],
                skip_special_tokens=True
            )
            return response.strip()
        except Exception as e:
            print(f"[LLM] Generation error: {e}")
            return ""

    def generate_batch_responses(
        self,
        batch_messages: List[List[Dict[str, str]]],
        max_new_tokens: Optional[int] = None,
        temperature: float = 0.1,
        top_p: float = 0.8,
        do_sample: bool = False,
        json_array_only: bool = False,
    ) -> List[str]:
        if not self.is_loaded:
            if not self.load():
                return [""] * len(batch_messages)
        if not batch_messages:
            return []

        try:
            import torch

            old_padding_side = self.tokenizer.padding_side
            self.tokenizer.padding_side = "left"

            prompts = [
                self.tokenizer.apply_chat_template(
                    msgs, tokenize=False, add_generation_prompt=True
                )
                for msgs in batch_messages
            ]
            inputs = self.tokenizer(prompts, return_tensors="pt", padding=True)
            if self.device in ("cuda", "mps"):
                inputs = {k: v.to(self.model.device) for k, v in inputs.items()}

            gen_kwargs: Dict[str, Any] = {
                "max_new_tokens": max_new_tokens or 256,
                "do_sample": do_sample,
                "pad_token_id": self.tokenizer.pad_token_id,
                "eos_token_id": self.tokenizer.eos_token_id,
            }
            if do_sample:
                gen_kwargs["temperature"] = temperature
                gen_kwargs["top_p"] = top_p
            if json_array_only:
                gen_kwargs["prefix_allowed_tokens_fn"] = (
                    self._json_array_prefix_constraint(inputs["input_ids"].shape[1])
                )

            with torch.no_grad():
                outputs = self.model.generate(**inputs, **gen_kwargs)

            responses = []
            prefix_len = inputs["input_ids"].shape[1]
            for i, output in enumerate(outputs):
                res = self.tokenizer.decode(output[prefix_len:], skip_special_tokens=True)
                responses.append(res.strip())

            self.tokenizer.padding_side = old_padding_side
            return responses
        except Exception as e:
            print(f"[LLM] Batch generation error ({e}), falling back to single generation...")
            responses = []
            for msgs in batch_messages:
                responses.append(self.generate_response(
                    msgs,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    do_sample=do_sample,
                    json_array_only=json_array_only,
                ))
            return responses

    def _get_json_array_token_ids(self) -> List[int]:
        """Return tokenizer IDs whose decoded text is valid JSON-array syntax.

        The schema reconciler emits only arrays containing non-negative integer
        indices and ``null``. Restricting decoding to that alphabet prevents
        Markdown and explanatory prose while the reconciler's parser continues
        to enforce length, range, type, and uniqueness constraints.
        """
        if self._json_array_token_ids is not None:
            return self._json_array_token_ids
        if self.tokenizer is None:
            raise RuntimeError("Tokenizer must be loaded before constrained decoding")

        allowed_chars = frozenset("[]0123456789,null \t\r\n")
        allowed_ids: List[int] = []
        vocab_size = len(self.tokenizer)
        special_ids = {
            token_id
            for token_id in (
                self.tokenizer.eos_token_id,
                self.tokenizer.pad_token_id,
            )
            if token_id is not None
        }
        for token_id in range(vocab_size):
            if token_id in special_ids:
                continue
            piece = self.tokenizer.decode(
                [token_id],
                skip_special_tokens=False,
                clean_up_tokenization_spaces=False,
            )
            if piece and all(char in allowed_chars for char in piece):
                allowed_ids.append(token_id)
        if not allowed_ids:
            raise RuntimeError("Tokenizer exposes no JSON-array-compatible tokens")
        self._json_array_token_ids = allowed_ids
        return allowed_ids

    def _json_array_prefix_constraint(self, prompt_length: int):
        """Stop only after the outer JSON array's closing bracket.

        Structured schema mappings may contain nested ``[source, target]``
        pairs.  Stopping at the first ``]`` truncates such output after one
        pair, so completion must be based on balanced bracket depth.
        """
        allowed_ids = self._get_json_array_token_ids()
        terminal_ids = list(dict.fromkeys(
            token_id
            for token_id in (
                self.tokenizer.eos_token_id,
                self.tokenizer.pad_token_id,
            )
            if token_id is not None
        ))
        if not terminal_ids:
            raise RuntimeError("Tokenizer has no terminal token for JSON decoding")

        token_pieces = {
            token_id: self.tokenizer.decode(
                [token_id],
                skip_special_tokens=False,
                clean_up_tokenization_spaces=False,
            )
            for token_id in allowed_ids
        }

        def constrain(_batch_id, input_ids):
            suffix_ids = input_ids[prompt_length:].tolist()
            suffix = ""
            if suffix_ids:
                suffix = self.tokenizer.decode(
                    suffix_ids,
                    skip_special_tokens=False,
                    clean_up_tokenization_spaces=False,
                )
                if suffix.lstrip().startswith("[[") and self._json_array_complete(suffix):
                    return terminal_ids
            # The canonical mapping grammar is an outer array containing
            # [source_index, target_index] pairs.  Prevent a small model from
            # omitting the outer bracket and producing ``[0,2],[1,1],...``.
            stripped = suffix.lstrip()
            if not stripped.startswith("[["):
                constrained = []
                for token_id, piece in token_pieces.items():
                    prospective = (suffix + piece).lstrip()
                    if "[[".startswith(prospective) or prospective.startswith("[["):
                        constrained.append(token_id)
                if constrained:
                    return constrained
            return allowed_ids

        return constrain

    @staticmethod
    def _json_array_complete(text: str) -> bool:
        """Return true once the first outer array is bracket-balanced."""
        depth = 0
        started = False
        for char in text:
            if char == "[":
                started = True
                depth += 1
            elif char == "]" and started:
                depth -= 1
                if depth == 0:
                    return True
                if depth < 0:
                    return False
        return False

    def generate_stream(
        self,
        messages: List[Dict[str, str]],
        max_new_tokens: Optional[int] = None,
        temperature: float = 0.1,
        top_p: float = 0.8,
    ) -> Iterator[str]:
        if not self.is_loaded:
            if not self.load():
                yield ""
                return

        try:
            import torch
            from transformers import TextStreamer

            prompt = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self.tokenizer(prompt, return_tensors="pt")
            if self.device in ("cuda", "mps"):
                inputs = {k: v.to(self.model.device) for k, v in inputs.items()}

            streamer = TextStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)

            gen_kwargs: Dict[str, Any] = {
                "max_new_tokens": max_new_tokens or 256,
                "temperature": temperature,
                "top_p": top_p,
                "do_sample": True,
                "pad_token_id": self.tokenizer.pad_token_id,
                "eos_token_id": self.tokenizer.eos_token_id,
                "streamer": streamer,
            }

            import threading as _thr
            result = {"done": False}

            def _run():
                with torch.no_grad():
                    self.model.generate(**inputs, **gen_kwargs)
                result["done"] = True

            _thr.Thread(target=_run, daemon=True).start()
            while not result["done"]:
                yield ""
        except Exception as e:
            print(f"[LLM] Stream error: {e}")
            yield ""

    def reset_kv_cache(self) -> None:
        if self.is_loaded and hasattr(self.model, "reset"):
            self.model.reset()

    def unload(self) -> None:
        if self.is_loaded:
            self.reset_kv_cache()
            import torch
            if hasattr(self.model, "cpu"):
                self.model.cpu()
            self.model = None
            self.tokenizer = None
            self.is_loaded = False
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print(f"[LLM] Model unloaded: {self.model_id}")

    @classmethod
    def unload_all(cls) -> None:
        with cls._lock:
            for key in list(cls._instances.keys()):
                cls._instances[key].unload()
            cls._instances.clear()


def generate_response(messages: List[Dict[str, str]], model_id: Optional[str] = None, **kwargs) -> str:
    manager = LLMManager(model_id=model_id, lazy=False)
    return manager.generate_response(messages, **kwargs)
