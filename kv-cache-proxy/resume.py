"""
Resume Handler

Orchestrates the interrupt → extract → resume flow:
1. On interruption: save KV cache checkpoint + partial output
2. On resume: restore KV cache, extract info from partial, append to context
3. Continue generation from checkpoint with new prompt

The key insight: we restore the KV cache (avoiding full reprocessing of
the conversation context), then append the partial response + new prompt
as new tokens. The model continues from where it left off.
"""

import time
import json
from typing import Optional, Dict, Any, List, Callable, Awaitable
from dataclasses import dataclass, field

from checkpoint import CheckpointManager, KVCacheCheckpoint
from extractor import PartialResponseExtractor, PartialExtractResult


@dataclass
class InterruptionState:
    """State captured when a generation is interrupted."""
    checkpoint_id: str
    partial_response: str
    conversation_history: List[Dict[str, str]]
    t_interrupted: float = field(default_factory=time.time)
    n_tokens_generated: int = 0
    extract_result: Optional[PartialExtractResult] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "partial_response": self.partial_response,
            "conversation_history": self.conversation_history,
            "t_interrupted": self.t_interrupted,
            "n_tokens_generated": self.n_tokens_generated,
            "extract_result": self.extract_result.to_dict() if self.extract_result else None,
        }


@dataclass
class ResumeResult:
    """Result of a resume operation."""
    success: bool
    checkpoint_id: str
    extracted_info: Optional[PartialExtractResult] = None
    conversation_history: Optional[List[Dict[str, str]]] = None
    new_prompt_position: int = 0
    message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "checkpoint_id": self.checkpoint_id,
            "extracted_info": self.extracted_info.to_dict() if self.extracted_info else None,
            "conversation_history": self.conversation_history,
            "new_prompt_position": self.new_prompt_position,
            "message": self.message,
        }


class ResumeHandler:
    """
    Orchestrates KV cache checkpointing and conversation resumption.
    
    Workflow:
    1. Chat request arrives → save KV cache checkpoint before generation
    2. Generation in progress → stream tokens to client
    3. Client disconnects → capture partial output, save checkpoint
    4. New chat request → restore KV cache, append partial+new prompt, continue
    """
    
    def __init__(
        self,
        checkpoint_mgr: CheckpointManager,
        extractor: Optional[PartialResponseExtractor] = None,
    ):
        self.checkpoint_mgr = checkpoint_mgr
        self.extractor = extractor or PartialResponseExtractor()
        
        # Active interruptions: model_hash → InterruptionState
        self._interruptions: Dict[str, InterruptionState] = {}
        
        # Model registry: model_hash → (model_path, ctx)
        self._models: Dict[str, Any] = {}
    
    def register_model(self, model_hash: str, model_path: str, ctx):
        """Register a loaded model with its context."""
        self._models[model_hash] = {
            "model_path": model_path,
            "ctx": ctx,
        }
    
    def unregister_model(self, model_hash: str):
        """Unregister a model and clean up its checkpoints."""
        self._models.pop(model_hash, None)
        # Note: checkpoints are kept in case the model is reloaded
    
    def on_generation_start(self, model_hash: str) -> Optional[str]:
        """
        Called before generation starts. Saves KV cache checkpoint.
        
        Returns:
            checkpoint_id if saved, None if no model registered
        """
        model = self._models.get(model_hash)
        if not model:
            return None
        
        checkpoint_id, n_tokens = self.checkpoint_mgr.save(
            ctx=model["ctx"],
            model_path=model["model_path"],
        )
        
        return checkpoint_id
    
    def on_interruption(
        self,
        model_hash: str,
        partial_response: str,
        conversation_history: List[Dict[str, str]],
        checkpoint_id: str,
        n_tokens_generated: int = 0,
    ) -> InterruptionState:
        """
        Called when a generation is interrupted.
        
        Captures the partial output and extracts key information.
        """
        # Extract information from partial response
        extract_result = self.extractor.extract(partial_response)
        
        state = InterruptionState(
            checkpoint_id=checkpoint_id,
            partial_response=partial_response,
            conversation_history=conversation_history,
            n_tokens_generated=n_tokens_generated,
            extract_result=extract_result,
        )
        
        self._interruptions[model_hash] = state
        
        return state
    
    def on_resume(
        self,
        model_hash: str,
        new_prompt: str,
        new_conversation_history: List[Dict[str, str]],
    ) -> ResumeResult:
        """
        Called when resuming after an interruption.
        
        Restores KV cache, appends partial response + new prompt,
        and returns the state needed to continue generation.
        """
        state = self._interruptions.get(model_hash)
        if not state:
            return ResumeResult(
                success=False,
                checkpoint_id="",
                message="No interruption state found for this model",
            )
        
        model = self._models.get(model_hash)
        if not model:
            return ResumeResult(
                success=False,
                checkpoint_id="",
                message="Model not registered",
            )
        
        # Restore KV cache
        success, n_tokens = self.checkpoint_mgr.restore(
            ctx=model["ctx"],
            checkpoint_id=state.checkpoint_id,
        )
        
        if not success:
            return ResumeResult(
                success=False,
                checkpoint_id=state.checkpoint_id,
                message="Failed to restore KV cache checkpoint",
            )
        
        # Build new conversation history:
        # [original history] + [assistant: partial response] + [user: new prompt]
        resumed_history = list(state.conversation_history)
        
        # Append partial response as assistant message
        if state.partial_response.strip():
            resumed_history.append({
                "role": "assistant",
                "content": state.partial_response,
            })
        
        # Append new prompt as user message
        resumed_history.append({
            "role": "user",
            "content": new_prompt,
        })
        
        # Clean up interruption state
        del self._interruptions[model_hash]
        
        return ResumeResult(
            success=True,
            checkpoint_id=state.checkpoint_id,
            extracted_info=state.extract_result,
            conversation_history=resumed_history,
            message=f"Resumed from checkpoint {state.checkpoint_id[:8]} "
                    f"({len(state.partial_response)} chars partial, "
                    f"{len(resumed_history)} total history entries)",
        )
    
    def get_interruption_info(self, model_hash: str) -> Optional[Dict[str, Any]]:
        """Get info about a pending interruption."""
        state = self._interruptions.get(model_hash)
        if not state:
            return None
        return state.to_dict()
    
    def cleanup(self):
        """Clean up all interruption states and checkpoints."""
        self._interruptions.clear()
        self.checkpoint_mgr.cleanup()
