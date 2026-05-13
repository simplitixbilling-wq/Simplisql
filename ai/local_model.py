"""
Local LLM Module for SimpliSQL
================================
Loads and runs GGUF models directly in Python via llama-cpp-python.
No external services (Ollama, APIs) required.

Downloads models automatically from HuggingFace on first use.

Usage:
    from ai.local_model import LocalModelClient

    client = LocalModelClient()
    client.load_model()  # downloads + loads on first call
    response = client.generate("Write a SQL query to ...")
"""

import os
import sys
import logging
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# ── PyInstaller frozen-bundle fix for llama_cpp native DLLs ──────────
# When running as a packaged .exe, sys._MEIPASS points to the _internal
# folder.  llama_cpp expects its DLLs in a 'lib' sub-directory relative
# to the package, so we add that path to os.add_dll_directory() (Win10+)
# and to PATH so LoadLibrary can resolve them.
def _fix_llama_dll_path():
    if not getattr(sys, 'frozen', False):
        return
    base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    lib_dir = os.path.join(base, 'llama_cpp', 'lib')
    if os.path.isdir(lib_dir):
        os.environ['PATH'] = lib_dir + os.pathsep + os.environ.get('PATH', '')
        try:
            os.add_dll_directory(lib_dir)   # Python 3.8+ Windows
        except (AttributeError, OSError):
            pass
        logger.info(f"llama_cpp DLL path registered: {lib_dir}")
    else:
        logger.warning(f"llama_cpp lib dir not found in bundle: {lib_dir}")

_fix_llama_dll_path()

# Model registry: repo_id, filename, description
AVAILABLE_MODELS = {
    "tinyllama": {
        "repo_id": "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
        "filename": "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        "description": "TinyLlama 1.1B (Very Fast, ~0.7 GB)",
        "context_length": 2048,
    },
    "gemma-2b": {
        "repo_id": "bartowski/gemma-2-2b-it-GGUF",
        "filename": "gemma-2-2b-it-Q4_K_M.gguf",
        "description": "Gemma 2 2B (Fast, ~1.5 GB)",
        "context_length": 4096,
    },
    "phi-2": {
        "repo_id": "TheBloke/phi-2-GGUF",
        "filename": "phi-2.Q4_K_M.gguf",
        "description": "Phi-2 2.7B (Good quality, ~1.6 GB)",
        "context_length": 2048,
    },
    "gemma-4-4b": {
        "repo_id": "unsloth/gemma-4-E4B-it-GGUF",
        "filename": "gemma-4-E4B-it-Q3_K_M.gguf",
        "description": "Gemma 4 4B (Best quality, ~4 GB)",
        "context_length": 8192,
        "flash_attn": True,
    },
    "sqlcoder-7b": {
        "repo_id": "TheBloke/sqlcoder-7B-GGUF",
        "filename": "sqlcoder-7b.Q4_K_M.gguf",
        "description": "SQLCoder 7B (SQL-specialized, ~4.1 GB)",
        "context_length": 8192,
    },
}

DEFAULT_MODEL = "gemma-2b"


def get_models_dir() -> Path:
    """Get the directory where models are stored."""
    models_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "models"
    models_dir.mkdir(exist_ok=True)
    return models_dir


class LocalModelClient:
    """
    Client that loads GGUF models via llama-cpp-python.
    Downloads from HuggingFace automatically if not cached.
    """

    def __init__(self):
        self.llm = None
        self.model_name: Optional[str] = None
        self.model_path: Optional[str] = None
        self.context_length: int = 4096
        self._loading = False
        logger.info("LocalModelClient initialized")

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    @staticmethod
    def list_available_models() -> list[dict]:
        """Return metadata for registered + any custom .gguf files in models/ folder."""
        result = []
        seen_files = set()

        # 1. Registered models
        for key, info in AVAILABLE_MODELS.items():
            local_path = get_models_dir() / info["filename"]
            seen_files.add(info["filename"].lower())
            result.append({
                "key": key,
                "description": info["description"],
                "downloaded": local_path.exists(),
                "path": str(local_path),
            })

        # 2. Auto-detect any .gguf files manually placed in models/ folder
        models_dir = get_models_dir()
        for f in sorted(models_dir.glob("*.gguf")):
            if f.name.lower() not in seen_files:
                # Derive a readable name from the filename
                stem = f.stem.replace("-", " ").replace("_", " ")
                size_mb = f.stat().st_size / (1024 * 1024)
                if size_mb >= 1024:
                    size_str = f"{size_mb / 1024:.1f} GB"
                else:
                    size_str = f"{size_mb:.0f} MB"
                result.append({
                    "key": f"custom:{f.name}",
                    "description": f"{stem} (Custom, ~{size_str})",
                    "downloaded": True,
                    "path": str(f),
                })

        return result

    def download_model(self, model_key: str = DEFAULT_MODEL, progress_callback=None, disable_ssl: bool = False) -> str:
        """
        Download a GGUF model from HuggingFace Hub.

        Args:
            model_key: Key from AVAILABLE_MODELS
            progress_callback: Optional callable(status_text)
            disable_ssl: If True, disable SSL verification (for corporate firewalls)

        Returns:
            Local file path to the downloaded model.
        """
        if model_key not in AVAILABLE_MODELS:
            raise ValueError(f"Unknown model: {model_key}. Choose from {list(AVAILABLE_MODELS)}")

        info = AVAILABLE_MODELS[model_key]
        local_path = get_models_dir() / info["filename"]

        if local_path.exists():
            logger.info(f"Model already downloaded: {local_path}")
            if progress_callback:
                progress_callback(f"Model already available: {info['description']}")
            return str(local_path)

        logger.info(f"Downloading {info['filename']} from {info['repo_id']} ...")
        if progress_callback:
            progress_callback(f"Downloading {info['description']}...")

        # Handle SSL certificate issues in corporate environments
        ssl_disabled = disable_ssl or os.environ.get("SIMPLISQL_DISABLE_SSL", "").lower() in ("1", "true", "yes")
        if ssl_disabled:
            import ssl
            import urllib.request
            # Backup original context
            _original_context = ssl._create_default_https_context
            ssl._create_default_https_context = ssl._create_unverified_context
            logger.warning("SSL verification disabled for download")
            if progress_callback:
                progress_callback("⚠️ SSL verification disabled (corporate network)")

        try:
            from huggingface_hub import hf_hub_download

            path = hf_hub_download(
                repo_id=info["repo_id"],
                filename=info["filename"],
                local_dir=str(get_models_dir()),
            )
            logger.info(f"Download complete: {path}")
            if progress_callback:
                progress_callback("Download complete!")
            return path
        except Exception as e:
            # If SSL error, suggest the workaround
            err_str = str(e).lower()
            if "ssl" in err_str or "certificate" in err_str:
                logger.error(f"SSL error during download: {e}")
                if progress_callback:
                    progress_callback("❌ SSL certificate error. Set SIMPLISQL_DISABLE_SSL=1 or use 'Skip SSL' option.")
                raise RuntimeError(
                    f"SSL certificate error. To bypass, set environment variable SIMPLISQL_DISABLE_SSL=1 "
                    f"or manually download the model to: {get_models_dir()}"
                ) from e
            raise
        finally:
            # Restore SSL context if we changed it
            if ssl_disabled:
                ssl._create_default_https_context = _original_context

    def load_model(self, model_key: str = DEFAULT_MODEL, progress_callback=None) -> bool:
        """
        Download (if needed) and load a model into memory.

        Supports registered models (by key) and custom .gguf files
        placed in the models/ folder (key starts with 'custom:').

        Returns True on success, False on failure.
        """
        if self._loading:
            return False

        self._loading = True
        try:
            # Handle custom models (manually placed .gguf files)
            if model_key.startswith("custom:"):
                filename = model_key[len("custom:"):]
                model_path = str(get_models_dir() / filename)
                if not os.path.exists(model_path):
                    logger.error(f"Custom model file not found: {model_path}")
                    return False
                ctx_length = 4096  # sensible default for unknown models
                if progress_callback:
                    progress_callback(f"Loading custom model: {filename}...")
            else:
                info = AVAILABLE_MODELS.get(model_key)
                if info is None:
                    logger.error(f"Unknown model key: {model_key}")
                    return False
                # Download if necessary
                model_path = self.download_model(model_key, progress_callback)
                ctx_length = info["context_length"]

            if progress_callback:
                progress_callback("Loading model into memory...")

            from llama_cpp import Llama

            use_flash_attn = AVAILABLE_MODELS.get(model_key, {}).get("flash_attn", False)
            self.llm = Llama(
                model_path=model_path,
                n_ctx=0,
                n_threads=os.cpu_count() or 4,
                flash_attn=use_flash_attn,
                verbose=False,
            )
            self.model_name = model_key
            self.model_path = model_path
            self.context_length = int(ctx_length)
            logger.info(f"Model loaded: {model_key}")
            if progress_callback:
                desc = AVAILABLE_MODELS.get(model_key, {}).get("description", model_key)
                progress_callback(f"Model ready: {desc}")
            return True

        except Exception as e:
            logger.error(f"Failed to load model {model_key}: {e}")
            if progress_callback:
                progress_callback(f"Error: {e}")
            return False
        finally:
            self._loading = False

    def is_loaded(self) -> bool:
        """Check if a model is currently loaded."""
        return self.llm is not None

    def unload_model(self):
        """Free model from memory."""
        self.llm = None
        self.model_name = None
        self.model_path = None
        logger.info("Model unloaded")

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7,
                 top_p: float = 0.9, stop: Optional[list[str]] = None) -> str:
        """
        Generate text from the loaded model.

        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Nucleus sampling parameter
            stop: Stop sequences

        Returns:
            Generated text string
        """
        if not self.is_loaded():
            raise RuntimeError("No model loaded. Call load_model() first.")

        try:
            if max_tokens is None or max_tokens <= 0:
                max_tokens = min(512, max(128, self.context_length // 4))
            max_tokens = min(max_tokens, max(128, self.context_length - 256))

            result = self.llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                stop=stop or [],
                echo=False,
            )
            text = result["choices"][0]["text"].strip()
            logger.info(f"Generated {len(text)} chars")
            return text
        except Exception as e:
            logger.error(f"Generation failed: {e}")
            raise

    def chat_streaming(self, messages: list[dict], max_tokens: int = 512,
                       temperature: float = 0.7, token_callback=None) -> str:
        """
        Streaming chat generation – calls token_callback(chunk: str) for each token.
        Returns the full concatenated text when done.
        Falls back to non-streaming chat() if streaming is unsupported.
        """
        if not self.is_loaded():
            raise RuntimeError("No model loaded. Call load_model() first.")

        if max_tokens is None or max_tokens <= 0:
            max_tokens = min(512, max(128, self.context_length // 4))
        max_tokens = min(max_tokens, max(128, self.context_length - 256))

        cleaned = []
        system_parts = []
        for msg in messages:
            if msg["role"] == "system":
                system_parts.append(msg["content"])
            else:
                cleaned.append(msg)

        if system_parts and cleaned:
            for i, msg in enumerate(cleaned):
                if msg["role"] == "user":
                    prefix = "\n".join(system_parts)
                    cleaned[i] = {
                        "role": "user",
                        "content": f"[Instructions: {prefix}]\n\n{msg['content']}",
                    }
                    break

        try:
            full_text = []
            stream = self.llm.create_chat_completion(
                messages=cleaned,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content", "")
                if token:
                    full_text.append(token)
                    if token_callback:
                        token_callback(token)
            result = "".join(full_text).strip()
            logger.info(f"Streaming chat response: {len(result)} chars")
            return result
        except Exception as e:
            logger.warning(f"Streaming failed ({e}), falling back to non-streaming chat()")
            # Fall back – collect full response then emit it as one chunk
            result = self.chat(messages, max_tokens=max_tokens, temperature=temperature)
            if token_callback:
                token_callback(result)
            return result

    def chat(self, messages: list[dict], max_tokens: int = 512,
             temperature: float = 0.7) -> str:
        """
        Chat-style generation using message list.

        Args:
            messages: List of {"role": "user"/"assistant"/"system", "content": "..."}
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            Assistant response text
        """
        if not self.is_loaded():
            raise RuntimeError("No model loaded. Call load_model() first.")

        try:
            if max_tokens is None or max_tokens <= 0:
                max_tokens = min(512, max(128, self.context_length // 4))
            max_tokens = min(max_tokens, max(128, self.context_length - 256))

            # Some models (e.g. Gemma) don't support the 'system' role.
            # Merge any system messages into the first user message.
            cleaned = []
            system_parts = []
            for msg in messages:
                if msg["role"] == "system":
                    system_parts.append(msg["content"])
                else:
                    cleaned.append(msg)

            if system_parts and cleaned:
                # Prepend system context to the first user message
                for i, msg in enumerate(cleaned):
                    if msg["role"] == "user":
                        prefix = "\n".join(system_parts)
                        cleaned[i] = {
                            "role": "user",
                            "content": f"[Instructions: {prefix}]\n\n{msg['content']}",
                        }
                        break

            result = self.llm.create_chat_completion(
                messages=cleaned,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = result["choices"][0]["message"]["content"].strip()
            logger.info(f"Chat response: {len(text)} chars")
            return text
        except Exception as e:
            err_str = str(e).lower()
            if "not supported" in err_str or "system" in err_str or "role" in err_str:
                # Fallback for models (e.g. Gemma) whose jinja2 template rejects
                # create_chat_completion even after system-role merging.
                # Re-format all messages into a single raw prompt and use generate().
                logger.warning(f"create_chat_completion failed ({e}), falling back to raw generate()")
                try:
                    prompt_parts = []
                    if system_parts:
                        prompt_parts.append("[Context]\n" + "\n\n".join(system_parts))
                    for m in cleaned:
                        role_label = "User" if m["role"] == "user" else "Assistant"
                        prompt_parts.append(f"{role_label}: {m['content']}")
                    prompt_parts.append("Assistant:")
                    raw_prompt = "\n\n".join(prompt_parts)
                    fallback = self.llm(
                        prompt=raw_prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        echo=False,
                    )
                    text = fallback["choices"][0]["text"].strip()
                    logger.info(f"Fallback generate response: {len(text)} chars")
                    return text
                except Exception as fe:
                    logger.error(f"Fallback generate also failed: {fe}")
                    raise fe
            logger.error(f"Chat generation failed: {e}")
            raise
