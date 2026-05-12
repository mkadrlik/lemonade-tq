"""
KV Cache Proxy Server

HTTP server that wraps llama-cpp-python with KV cache checkpointing.
Provides a drop-in replacement for llama.cpp's chat completions API
with interruption/resume support.

Endpoints:
  POST /v1/chat/completions  - Standard chat completion (with checkpointing)
  POST /v1/models            - List/load models
  GET  /v1/models            - List loaded models
  POST /checkpoint/save      - Manually save KV cache checkpoint
  POST /checkpoint/restore   - Restore KV cache checkpoint
  GET  /health               - Health check
  GET  /status               - Server status (active interruptions, etc.)

Usage:
  python server.py --model path/to/model.gguf --port 13307
  
  # Or with config file:
  python server.py --config config.yaml
"""

import os
import sys
import json
import time
import uuid
import asyncio
import argparse
import signal
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List

from aiohttp import web, ClientSession
import llama_cpp

# Import our modules
sys.path.insert(0, str(Path(__file__).parent))
from checkpoint import CheckpointManager
from extractor import PartialExtractor
from resume import ResumeHandler, InterruptionState


# --- Configuration ---

class Config:
    """Server configuration."""
    
    def __init__(
        self,
        model_path: str = "",
        port: int = 13307,
        host: str = "0.0.0.0",
        ctx_size: int = 8192,
        n_gpu_layers: int = 35,
        tensor_split: Optional[List[float]] = None,
        chat_template: Optional[str] = None,
        checkpoint_dir: str = "/tmp/kv-cache-checkpoints",
        max_checkpoints: int = 10,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.95,
    ):
        self.model_path = model_path
        self.port = port
        self.host = host
        self.ctx_size = ctx_size
        self.n_gpu_layers = n_gpu_layers
        self.tensor_split = tensor_split
        self.chat_template = chat_template
        self.checkpoint_dir = checkpoint_dir
        self.max_checkpoints = max_checkpoints
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p


# --- Server ---

class KVCacheProxyServer:
    """
    HTTP server wrapping llama-cpp-python with KV cache checkpointing.
    
    When a generation is interrupted (client disconnects), the KV cache
    is saved and the partial output is captured. On the next request,
    the KV cache is restored and the conversation continues from where
    it left off.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.app = web.Application()
        
        # Core components
        self.checkpoint_mgr = CheckpointManager(
            cache_dir=config.checkpoint_dir,
            max_checkpoints=config.max_checkpoints,
        )
        self.extractor = PartialExtractor()
        self.resume_handler = ResumeHandler(self.checkpoint_mgr, self.extractor)
        
        # Model state
        self.llama: Optional[llama_cpp.Llama] = None
        self.model_hash: Optional[str] = None
        self._model_loaded = False
        
        # Active generation tracking
        self._active_generations: Dict[str, Dict[str, Any]] = {}
        
        # Request tracking for interruption detection
        self._active_requests: Dict[str, web.Request] = {}
        
        # Setup routes
        self._setup_routes()
    
    def _setup_routes(self):
        """Register HTTP routes."""
        self.app.router.add_post("/v1/chat/completions", self.handle_chat)
        self.app.router.add_post("/v1/models", self.handle_model_load)
        self.app.router.add_get("/v1/models", self.handle_model_list)
        self.app.router.add_post("/checkpoint/save", self.handle_checkpoint_save)
        self.app.router.add_post("/checkpoint/restore", self.handle_checkpoint_restore)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/status", self.handle_status)
        self.app.router.add_get("/interrupted", self.handle_get_interruption)
        
        # Cleanup on shutdown
        self.app.on_shutdown.append(self._on_shutdown)
    
    async def _on_shutdown(self, app):
        """Clean up on shutdown."""
        if self.llama:
            del self.llama
        self.checkpoint_mgr.cleanup()
    
    # --- Model Management ---
    
    async def handle_model_load(self, request: web.Request) -> web.Response:
        """Load a model."""
        try:
            body = await request.json()
            model_path = body.get("model_path", self.config.model_path)
            
            if not model_path or not Path(model_path).exists():
                return web.json_response(
                    {"error": f"Model not found: {model_path}"},
                    status=404,
                )
            
            # Compute model hash
            self.model_hash = hashlib.md5(model_path.encode()).hexdigest()[:12]
            
            # Load model
            print(f"[server] Loading model: {model_path}")
            self.llama = llama_cpp.Llama(
                model_path=model_path,
                n_ctx=self.config.ctx_size,
                n_gpu_layers=self.config.n_gpu_layers,
                tensor_split=self.config.tensor_split,
                chat_template=self.config.chat_template,
            )
            self._model_loaded = True
            
            # Register with resume handler
            self.resume_handler.register_model(
                self.model_hash,
                model_path,
                self.llama.ctx,
            )
            
            return web.json_response({
                "status": "loaded",
                "model_path": model_path,
                "model_hash": self.model_hash,
                "ctx_size": self.config.ctx_size,
            })
        
        except Exception as e:
            return web.json_response(
                {"error": str(e)},
                status=500,
            )
    
    async def handle_model_list(self, request: web.Request) -> web.Response:
        """List loaded models."""
        models = []
        if self._model_loaded and self.llama:
            models.append({
                "id": self.model_hash,
                "model_path": self.llama.model_path,
                "ctx_size": self.config.ctx_size,
                "n_gpu_layers": self.config.n_gpu_layers,
                "status": "loaded",
            })
        
        return web.json_response({"models": models})
    
    # --- Chat Completions ---
    
    async def handle_chat(self, request: web.Request) -> web.Response:
        """
        Handle chat completion requests with KV cache checkpointing.
        
        Request body:
        {
            "model": "hash",           # Model hash (optional, uses loaded model)
            "messages": [...],         # Conversation history
            "stream": true/false,      # Streaming mode
            "max_tokens": 512,         # Max tokens to generate
            "temperature": 0.7,        # Sampling temperature
            "top_p": 0.95,             # Top-p sampling
            "resume_from": "checkpoint_id",  # Resume from checkpoint
            "partial_response": "...", # Partial response from interrupted generation
        }
        """
        try:
            body = await request.json()
            stream = body.get("stream", False)
            messages = body.get("messages", [])
            max_tokens = body.get("max_tokens", self.config.max_tokens)
            temperature = body.get("temperature", self.config.temperature)
            top_p = body.get("top_p", self.config.top_p)
            resume_from = body.get("resume_from")
            partial_response = body.get("partial_response")
            
            if not self._model_loaded or not self.llama:
                return web.json_response(
                    {"error": "No model loaded. POST to /v1/models first."},
                    status=503,
                )
            
            model_hash = body.get("model", self.model_hash)
            
            # Check if resuming from an interruption
            if resume_from and partial_response:
                return await self._handle_resume(
                    model_hash, messages, stream, max_tokens,
                    temperature, top_p, resume_from, partial_response,
                )
            
            # Normal generation with checkpointing
            return await self._handle_normal_chat(
                model_hash, messages, stream, max_tokens,
                temperature, top_p, request,
            )
        
        except Exception as e:
            return web.json_response(
                {"error": str(e)},
                status=500,
            )
    
    async def _handle_normal_chat(
        self,
        model_hash: str,
        messages: List[Dict[str, str]],
        stream: bool,
        max_tokens: int,
        temperature: float,
        top_p: float,
        request: web.Request,
    ) -> web.Response:
        """Handle a normal chat completion with KV cache checkpointing."""
        generation_id = uuid.uuid4().hex[:8]
        
        # Save KV cache checkpoint before generation
        checkpoint_id = self.resume_handler.on_generation_start(model_hash)
        
        # Track active generation
        self._active_generations[generation_id] = {
            "checkpoint_id": checkpoint_id,
            "messages": messages,
            "model_hash": model_hash,
            "partial_response": "",
            "n_tokens_generated": 0,
        }
        
        if stream:
            return self._stream_response(
                generation_id, messages, max_tokens, temperature, top_p,
            )
        else:
            return self._non_stream_response(
                generation_id, messages, max_tokens, temperature, top_p,
            )
    
    def _stream_response(
        self,
        generation_id: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> web.StreamResponse:
        """Return a streaming SSE response."""
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        
        async def event_stream():
            try:
                gen = self.llama.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    stream=True,
                )
                
                generation = self._active_generations[generation_id]
                
                for chunk in gen:
                    # Check if client is still connected
                    if not response.writer.can_write:
                        # Client disconnected - capture interruption
                        generation["interrupted"] = True
                        break
                    
                    choice = chunk["choices"][0]
                    delta = choice.get("delta", {})
                    content = delta.get("content", "")
                    
                    if content:
                        generation["partial_response"] += content
                        generation["n_tokens_generated"] += 1
                    
                    yield f"data: {json.dumps(chunk)}\n\n"
                
                # Send final event
                final_chunk = {
                    "id": f"chatcmpl-{generation_id}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": self.model_hash,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop" if not generation.get("interrupted") else "interrupted",
                    }],
                }
                yield f"data: {json.dumps(final_chunk)}\n\n"
                yield "data: [DONE]\n\n"
                
            except Exception as e:
                print(f"[server] Generation error: {e}")
                error_chunk = {"error": str(e)}
                yield f"data: {json.dumps(error_chunk)}\n\n"
            finally:
                # Handle interruption
                generation = self._active_generations.get(generation_id)
                if generation and generation.get("interrupted"):
                    self._handle_interruption(generation_id)
                
                # Cleanup
                self._active_generations.pop(generation_id, None)
        
        response.enable_chunked_encoding()
        response.prepare()
        
        # Start the streaming coroutine
        asyncio.create_task(event_stream())
        
        return response
    
    def _non_stream_response(
        self,
        generation_id: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> web.Response:
        """Return a non-streaming response."""
        try:
            completion = self.llama.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                stream=False,
            )
            
            generation = self._active_generations.get(generation_id)
            if generation:
                content = completion["choices"][0]["message"]["content"]
                generation["partial_response"] = content
            
            return web.json_response(completion)
        
        except Exception as e:
            return web.json_response(
                {"error": str(e)},
                status=500,
            )
    
    def _handle_interruption(self, generation_id: str):
        """Handle a generation interruption."""
        generation = self._active_generations.get(generation_id)
        if not generation:
            return
        
        model_hash = generation["model_hash"]
        checkpoint_id = generation["checkpoint_id"]
        partial_response = generation["partial_response"]
        messages = generation["messages"]
        n_tokens = generation["n_tokens_generated"]
        
        # Record interruption state
        self.resume_handler.on_interruption(
            model_hash=model_hash,
            partial_response=partial_response,
            conversation_history=messages,
            checkpoint_id=checkpoint_id,
            n_tokens_generated=n_tokens,
        )
        
        print(f"[server] Interruption captured: {len(partial_response)} chars, "
              f"{n_tokens} tokens generated")
    
    async def _handle_resume(
        self,
        model_hash: str,
        messages: List[Dict[str, str]],
        stream: bool,
        max_tokens: int,
        temperature: float,
        top_p: float,
        resume_from: str,
        partial_response: str,
    ) -> web.Response:
        """Handle a resume request after interruption."""
        # The resume is handled by building the conversation history
        # with the partial response appended, then generating normally
        # from the restored KV cache.
        
        # Build resumed conversation history
        resumed_messages = list(messages)
        
        # Append partial response as assistant message
        if partial_response.strip():
            resumed_messages.append({
                "role": "assistant",
                "content": partial_response,
            })
        
        # The new prompt is the last message
        new_prompt = resumed_messages[-1]["content"] if resumed_messages else ""
        
        # Restore KV cache and get extracted info
        resume_result = self.resume_handler.on_resume(
            model_hash=model_hash,
            new_prompt=new_prompt,
            new_conversation_history=messages,
        )
        
        if not resume_result.success:
            return web.json_response({
                "error": resume_result.message,
                "resume": False,
            }, status=400)
        
        # Generate with resumed history
        generation_id = uuid.uuid4().hex[:8]
        self._active_generations[generation_id] = {
            "checkpoint_id": resume_from,
            "messages": resume_result.conversation_history,
            "model_hash": model_hash,
            "partial_response": "",
            "n_tokens_generated": 0,
            "resumed": True,
        }
        
        if stream:
            return self._stream_response(
                generation_id,
                resume_result.conversation_history,
                max_tokens,
                temperature,
                top_p,
            )
        else:
            return self._non_stream_response(
                generation_id,
                resume_result.conversation_history,
                max_tokens,
                temperature,
                top_p,
            )
    
    # --- Checkpoint Management ---
    
    async def handle_checkpoint_save(self, request: web.Request) -> web.Response:
        """Manually save KV cache checkpoint."""
        try:
            body = await request.json() or {}
            model_hash = body.get("model", self.model_hash)
            
            model = self.resume_handler._models.get(model_hash)
            if not model:
                return web.json_response(
                    {"error": f"Model not found: {model_hash}"},
                    status=404,
                )
            
            checkpoint_id, n_tokens = self.checkpoint_mgr.save(
                ctx=model["ctx"],
                model_path=model["model_path"],
            )
            
            return web.json_response({
                "status": "saved",
                "checkpoint_id": checkpoint_id,
                "n_tokens": n_tokens,
            })
        
        except Exception as e:
            return web.json_response(
                {"error": str(e)},
                status=500,
            )
    
    async def handle_checkpoint_restore(self, request: web.Request) -> web.Response:
        """Manually restore KV cache checkpoint."""
        try:
            body = await request.json() or {}
            model_hash = body.get("model", self.model_hash)
            checkpoint_id = body.get("checkpoint_id")
            
            if not checkpoint_id:
                return web.json_response(
                    {"error": "checkpoint_id required"},
                    status=400,
                )
            
            model = self.resume_handler._models.get(model_hash)
            if not model:
                return web.json_response(
                    {"error": f"Model not found: {model_hash}"},
                    status=404,
                )
            
            success, n_tokens = self.checkpoint_mgr.restore(
                ctx=model["ctx"],
                checkpoint_id=checkpoint_id,
            )
            
            return web.json_response({
                "status": "restored" if success else "failed",
                "checkpoint_id": checkpoint_id,
                "n_tokens": n_tokens,
                "success": success,
            })
        
        except Exception as e:
            return web.json_response(
                {"error": str(e)},
                status=500,
            )
    
    # --- Status & Health ---
    
    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check."""
        return web.json_response({
            "status": "healthy",
            "model_loaded": self._model_loaded,
            "active_generations": len(self._active_generations),
            "active_interruptions": len(self.resume_handler._interruptions),
        })
    
    async def handle_status(self, request: web.Request) -> web.Response:
        """Server status."""
        interruptions = {}
        for model_hash, state in self.resume_handler._interruptions.items():
            interruptions[model_hash] = {
                "checkpoint_id": state.checkpoint_id,
                "partial_length": len(state.partial_response),
                "n_tokens_generated": state.n_tokens_generated,
                "extracted_info": state.extract_result.to_dict() if state.extract_result else None,
            }
        
        return web.json_response({
            "model_loaded": self._model_loaded,
            "model_hash": self.model_hash,
            "active_generations": len(self._active_generations),
            "active_interruptions": len(interruptions),
            "interruptions": interruptions,
            "checkpoint_dir": self.config.checkpoint_dir,
            "active_checkpoints": self.checkpoint_mgr.list_active(),
        })
    
    async def handle_get_interruption(self, request: web.Request) -> web.Response:
        """Get info about pending interruptions."""
        model_hash = request.query.get("model")
        if model_hash:
            info = self.resume_handler.get_interruption_info(model_hash)
            if info is None:
                return web.json_response({"error": "No interruption found"}, status=404)
            return web.json_response({"interruption": info})
        
        # Return all interruptions
        interruptions = {}
        for mh, state in self.resume_handler._interruptions.items():
            interruptions[mh] = state.to_dict()
        
        return web.json_response({"interruptions": interruptions})
    
    # --- Run ---
    
    def run(self):
        """Start the server."""
        print(f"[server] Starting KV Cache Proxy on {self.config.host}:{self.config.port}")
        print(f"[server] Checkpoint dir: {self.config.checkpoint_dir}")
        web.run_app(self.app, host=self.config.host, port=self.config.port)


# --- Main ---

def parse_args():
    parser = argparse.ArgumentParser(description="KV Cache Proxy Server")
    parser.add_argument("--model", type=str, default="", help="Path to GGUF model")
    parser.add_argument("--port", type=int, default=13307, help="Server port")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Server host")
    parser.add_argument("--ctx-size", type=int, default=8192, help="Context size")
    parser.add_argument("--n-gpu-layers", type=int, default=35, help="GPU layers")
    parser.add_argument("--max-tokens", type=int, default=512, help="Max tokens per generation")
    parser.add_argument("--temperature", type=float, default=0.7, help="Sampling temperature")
    parser.add_argument("--top-p", type=float, default=0.95, help="Top-p sampling")
    parser.add_argument("--checkpoint-dir", type=str, default="/tmp/kv-cache-checkpoints", help="Checkpoint storage dir")
    parser.add_argument("--max-checkpoints", type=int, default=10, help="Max checkpoints to keep")
    parser.add_argument("--chat-template", type=str, default=None, help="Chat template string")
    return parser.parse_args()


def main():
    args = parse_args()
    
    config = Config(
        model_path=args.model,
        port=args.port,
        host=args.host,
        ctx_size=args.ctx_size,
        n_gpu_layers=args.n_gpu_layers,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        checkpoint_dir=args.checkpoint_dir,
        max_checkpoints=args.max_checkpoints,
        chat_template=args.chat_template,
    )
    
    server = KVCacheProxyServer(config)
    server.run()


if __name__ == "__main__":
    main()
