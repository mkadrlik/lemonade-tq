"""
KV Cache Checkpoint Manager

Saves and restores llama.cpp KV cache state to enable resumption after
interruptions without reprocessing the entire conversation context.

Data flow:
  1. Before generation: save KV cache → checkpoint_id
  2. On interruption: partial output + checkpoint_id stored
  3. On resume: restore KV cache → append partial+new prompt → continue
"""

import os
import json
import time
import uuid
import shutil
import pickle
from pathlib import Path
from typing import Optional, Tuple, Dict, Any


class KVCacheCheckpoint:
    """Represents a single KV cache checkpoint with metadata."""
    def __init__(
        self,
        checkpoint_id: str,
        cache_data: bytes,
        n_tokens: int,
        t_start: float,
        t_end: float,
        n_sent: int = 0,
        model_path: str = "",
    ):
        self.checkpoint_id = checkpoint_id
        self.cache_data = cache_data
        self.n_tokens = n_tokens
        self.t_start = t_start
        self.t_end = t_end
        self.n_sent = n_sent
        self.model_path = model_path
        self.duration = t_end - t_start


class CheckpointManager:
    """
    Manages KV cache checkpoints for conversation resumption.
    
    Each checkpoint captures the KV cache state at a specific point in the
    conversation. On interruption, the checkpoint is saved. On resume, it's
    restored and new tokens (partial response + new prompt) are appended.
    """
    
    def __init__(self, cache_dir: str = "/tmp/kv-cache-checkpoints", max_checkpoints: int = 10):
        self.cache_dir = Path(cache_dir)
        self.max_checkpoints = max_checkpoints
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # In-memory cache of recent checkpoints (for fast access)
        self._memory_cache: Dict[str, KVCacheCheckpoint] = {}
    
    def save(
        self,
        ctx,  # llama_cpp.llama_cpp.LlamaContext
        model_path: str = "",
    ) -> Tuple[str, int]:
        """
        Save the current KV cache state.
        
        Args:
            ctx: llama.cpp context object (must have kv_cache_save method)
            model_path: Path to the model file (stored for resume reference)
            
        Returns:
            (checkpoint_id, n_tokens_in_cache)
        """
        checkpoint_id = uuid.uuid4().hex[:12]
        t_start = time.time()
        
        # Save state - returns LlamaState object, pickle for storage
        state_obj = ctx.save_state()
        cache_data = pickle.dumps(state_obj)
        n_tokens = state_obj.n_tokens
        
        t_end = time.time()
        
        checkpoint = KVCacheCheckpoint(
            checkpoint_id=checkpoint_id,
            cache_data=cache_data,
            n_tokens=n_tokens,
            t_start=t_start,
            t_end=t_end,
            model_path=model_path,
        )
        
        # Store in memory
        self._memory_cache[checkpoint_id] = checkpoint
        
        # Persist to disk
        self._persist(checkpoint)
        
        # Evict old checkpoints if over limit
        self._evict_old()
        
        return checkpoint_id, n_tokens
    
    def restore(
        self,
        ctx,  # llama_cpp.llama_cpp.LlamaContext
        checkpoint_id: str,
    ) -> Tuple[bool, int]:
        """
        Restore a KV cache checkpoint.
        
        Args:
            ctx: llama.cpp context object (must have kv_cache_restore method)
            checkpoint_id: ID of the checkpoint to restore
            
        Returns:
            (success, n_tokens_restored)
        """
        checkpoint = self._memory_cache.get(checkpoint_id)
        if checkpoint is None:
            # Try loading from disk
            checkpoint = self._load(checkpoint_id)
            if checkpoint is None:
                return False, 0
        
        # Restore KV cache - unpickle LlamaState and pass to load_state
        state_obj = pickle.loads(checkpoint.cache_data)
        ctx.load_state(state_obj)
        
        # Update memory cache
        self._memory_cache[checkpoint_id] = checkpoint
        
        return True, checkpoint.n_tokens
    
    def get(self, checkpoint_id: str) -> Optional[KVCacheCheckpoint]:
        """Get a checkpoint by ID (from memory or disk)."""
        checkpoint = self._memory_cache.get(checkpoint_id)
        if checkpoint is None:
            checkpoint = self._load(checkpoint_id)
        return checkpoint
    
    def clear(self, checkpoint_id: Optional[str] = None):
        """Clear one or all checkpoints."""
        if checkpoint_id:
            self._memory_cache.pop(checkpoint_id, None)
            self._remove_file(checkpoint_id)
        else:
            self._memory_cache.clear()
            self._clear_disk()
    
    def list_active(self) -> list:
        """List all active checkpoint IDs."""
        return list(self._memory_cache.keys())
    
    def cleanup(self):
        """Remove all checkpoints and clear disk."""
        self.clear()
        self._clear_disk()
    
    # --- Private methods ---
    
    def _persist(self, checkpoint: KVCacheCheckpoint):
        """Save checkpoint to disk."""
        path = self.cache_dir / f"{checkpoint.checkpoint_id}.bin"
        with open(path, "wb") as f:
            f.write(checkpoint.cache_data)
        
        # Save metadata
        meta_path = self.cache_dir / f"{checkpoint.checkpoint_id}.meta"
        with open(meta_path, "w") as f:
            json.dump({
                "checkpoint_id": checkpoint.checkpoint_id,
                "n_tokens": checkpoint.n_tokens,
                "t_start": checkpoint.t_start,
                "t_end": checkpoint.t_end,
                "n_sent": checkpoint.n_sent,
                "model_path": checkpoint.model_path,
            }, f)
    
    def _load(self, checkpoint_id: str) -> Optional[KVCacheCheckpoint]:
        """Load checkpoint from disk."""
        cache_path = self.cache_dir / f"{checkpoint_id}.bin"
        meta_path = self.cache_dir / f"{checkpoint_id}.meta"
        
        if not cache_path.exists() or not meta_path.exists():
            return None
        
        with open(cache_path, "rb") as f:
            cache_data = f.read()
        
        with open(meta_path, "r") as f:
            meta = json.load(f)
        
        checkpoint = KVCacheCheckpoint(
            checkpoint_id=checkpoint_id,
            cache_data=cache_data,
            n_tokens=meta["n_tokens"],
            t_start=meta["t_start"],
            t_end=meta["t_end"],
            n_sent=meta.get("n_sent", 0),
            model_path=meta.get("model_path", ""),
        )
        
        self._memory_cache[checkpoint_id] = checkpoint
        return checkpoint
    
    def _remove_file(self, checkpoint_id: str):
        """Remove checkpoint files from disk."""
        for suffix in [".bin", ".meta"]:
            path = self.cache_dir / f"{checkpoint_id}{suffix}"
            if path.exists():
                path.unlink()
    
    def _clear_disk(self):
        """Remove all checkpoint files from disk."""
        shutil.rmtree(self.cache_dir, ignore_errors=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _evict_old(self):
        """Remove oldest checkpoints if over limit."""
        while len(self._memory_cache) > self.max_checkpoints:
            oldest_id = next(iter(self._memory_cache))
            self._remove_file(oldest_id)
            del self._memory_cache[oldest_id]
