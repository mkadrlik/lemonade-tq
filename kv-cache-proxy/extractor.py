"""
Partial Response Extractor

Scans interrupted model output for clues, information, and structure.
Extracts key facts, incomplete thoughts, code blocks, and formatting
that can be preserved when resuming the conversation.

This enables the resumed generation to pick up where it left off
without losing the model's train of thought.
"""

import re
from typing import Dict, List, Any, Optional


class PartialExtractResult:
    """Result of extracting information from a partial response."""
    def __init__(
        self,
        topics: List[str] = None,
        incomplete_thoughts: List[str] = None,
        code_blocks: List[Dict[str, str]] = None,
        key_facts: List[str] = None,
        structure: str = "",
        truncation_point: str = "",
        estimated_completeness: float = 0.0,
    ):
        self.topics = topics or []
        self.incomplete_thoughts = incomplete_thoughts or []
        self.code_blocks = code_blocks or []
        self.key_facts = key_facts or []
        self.structure = structure
        self.truncation_point = truncation_point
        self.estimated_completeness = estimated_completeness
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "topics": self.topics,
            "incomplete_thoughts": self.incomplete_thoughts,
            "code_blocks": self.code_blocks,
            "key_facts": self.key_facts,
            "structure": self.structure,
            "truncation_point": self.truncation_point,
            "estimated_completeness": self.estimated_completeness,
        }
    
    def summary(self) -> str:
        """Human-readable summary of extracted info."""
        lines = []
        if self.topics:
            lines.append(f"Topics: {', '.join(self.topics)}")
        if self.incomplete_thoughts:
            lines.append(f"Incomplete: {'; '.join(self.incomplete_thoughts)}")
        if self.code_blocks:
            lines.append(f"Code blocks: {len(self.code_blocks)}")
        if self.key_facts:
            lines.append(f"Key facts: {len(self.key_facts)}")
        if self.truncation_point:
            lines.append(f"Truncated at: {self.truncation_point[:80]}...")
        return "\n".join(lines) if lines else "(no extractable info)"


class PartialExtractor:
    """
    Extracts key information from a partial (interrupted) model response.
    
    Scans for:
    - Topics being discussed
    - Incomplete sentences/thoughts
    - Code blocks (preserved for context)
    - Key factual statements
    - Structural markers (lists, headings, etc.)
    - Truncation point (where the interruption happened)
    """
    
    # Patterns for detecting incomplete thoughts
    INCOMPLETE_PATTERNS = [
        r"\b(?:and|but|however|therefore|moreover|furthermore|additionally)\s+\S+\s*$",  # Conjunctions
        r"\S+\s*[,;:]\s*$",  # Trailing punctuation without completion
        r"\b(?:is|are|was|were|be|been|being)\s+\S+\s*$",  # Verb phrases
        r"\b(?:the|a|an|this|that|these|those)\s+\S+\s*$",  # Noun phrases
        r"\b(?:to|for|with|from|by|at|on|in)\s+\S+\s*$",  # Prepositional
        r"[a-zA-Z]\s*$",  # Single word at end
    ]
    
    # Patterns for detecting code blocks
    CODE_BLOCK_PATTERN = re.compile(
        r"```(?P<lang>\w*)\n(?P<code>.*?)(?:```|$)",
        re.DOTALL,
    )
    
    # Patterns for detecting list items
    LIST_PATTERN = re.compile(
        r"^(\s*[-*]\s+|\s*\d+\.\s+)(.+)$",
        re.MULTILINE,
    )
    
    # Patterns for detecting headings
    HEADING_PATTERN = re.compile(
        r"^(#{1,6}\s+.+)$",
        re.MULTILINE,
    )
    
    def extract(self, partial_response: str) -> PartialExtractResult:
        """
        Extract information from a partial response.
        
        Args:
            partial_response: The text that was generated before interruption
            
        Returns:
            PartialExtractResult with extracted information
        """
        if not partial_response or not partial_response.strip():
            return PartialExtractResult()
        
        result = PartialExtractResult()
        
        # 1. Detect truncation point (last 100 chars)
        result.truncation_point = partial_response[-100:] if len(partial_response) > 100 else partial_response
        
        # 2. Detect incomplete thoughts
        result.incomplete_thoughts = self._find_incomplete_thoughts(partial_response)
        
        # 3. Extract code blocks
        result.code_blocks = self._extract_code_blocks(partial_response)
        
        # 4. Detect topics (simple: look for repeated/noun-like words)
        result.topics = self._detect_topics(partial_response)
        
        # 5. Extract key facts (simple: look for statements with specific patterns)
        result.key_facts = self._extract_key_facts(partial_response)
        
        # 6. Detect structure
        result.structure = self._detect_structure(partial_response)
        
        # 7. Estimate completeness
        result.estimated_completeness = self._estimate_completeness(partial_response)
        
        return result
    
    def _find_incomplete_thoughts(self, text: str) -> List[str]:
        """Find sentences/thoughts that appear incomplete."""
        incomplete = []
        
        # Get the last paragraph/sentence
        sentences = re.split(r'(?<=[.!?])\s+', text)
        if sentences:
            last_sentence = sentences[-1].strip()
            
            # Check if it matches incomplete patterns
            for pattern in self.INCOMPLETE_PATTERNS:
                if re.search(pattern, last_sentence):
                    incomplete.append(last_sentence)
                    break
            
            # If no pattern matched but it's short and ends mid-word, it's incomplete
            if not incomplete and len(last_sentence) < 50 and not last_sentence.endswith(('.', '!', '?', '"', ')', '```')):
                # Check if it ends mid-word
                if re.search(r'[a-zA-Z]\s*$', last_sentence):
                    incomplete.append(last_sentence)
        
        return incomplete
    
    def _extract_code_blocks(self, text: str) -> List[Dict[str, str]]:
        """Extract code blocks from the text."""
        blocks = []
        for match in self.CODE_BLOCK_PATTERN.finditer(text):
            blocks.append({
                "language": match.group("lang") or "text",
                "code": match.group("code"),
            })
        return blocks
    
    def _detect_topics(self, text: str) -> List[str]:
        """Detect topics being discussed (simple heuristic)."""
        # Look for capitalized words that might be topic indicators
        words = re.findall(r'\b[A-Z][a-z]{2,}\b', text)
        # Filter to most common
        from collections import Counter
        counts = Counter(words)
        topics = [word for word, _ in counts.most_common(5)]
        return topics
    
    def _extract_key_facts(self, text: str) -> List[str]:
        """Extract key factual statements (simple heuristic)."""
        facts = []
        # Look for lines with specific patterns (numbers, dates, technical terms)
        fact_patterns = [
            r'\b\d{4}\b',  # Years
            r'\b\d+\.?\d*\s*(?:MB|GB|TB|MHz|GHz|fps|tokens?)\b',  # Measurements
            r'\b(?:https?://|www\.)\S+\b',  # URLs
            r'\b[A-Z]{2,}\b',  # Acronyms
        ]
        
        for line in text.split('\n'):
            line = line.strip()
            if len(line) > 10 and len(line) < 200:
                for pattern in fact_patterns:
                    if re.search(pattern, line):
                        facts.append(line)
                        break
        
        return facts[:10]  # Limit to 10 facts
    
    def _detect_structure(self, text: str) -> str:
        """Detect structural elements in the text."""
        structures = []
        
        # Check for lists
        list_items = self.LIST_PATTERN.findall(text)
        if list_items:
            structures.append(f"list({len(list_items)} items)")
        
        # Check for headings
        headings = self.HEADING_PATTERN.findall(text)
        if headings:
            structures.append(f"headings({len(headings)})")
        
        # Check for code blocks
        code_blocks = self.CODE_BLOCK_PATTERN.findall(text)
        if code_blocks:
            structures.append(f"code({len(code_blocks)} blocks)")
        
        return ", ".join(structures) if structures else "plain text"
    
    def _estimate_completeness(self, text: str) -> float:
        """
        Estimate how complete the response is (0.0 = truncated early, 1.0 = complete).
        
        Heuristic: check if the text ends with a complete sentence/paragraph.
        """
        if not text.strip():
            return 0.0
        
        text = text.strip()
        
        # Complete endings
        complete_endings = ['.', '!', '?', '"', ')', '```', '\n\n']
        if any(text.endswith(e) for e in complete_endings):
            return 0.9  # Likely complete or near-complete
        
        # Incomplete endings
        incomplete_endings = [' ', '\n', ',', ';', ':', '-', '(', '[', '{']
        if any(text.endswith(e) for e in incomplete_endings):
            return 0.3  # Likely truncated
        
        # Mid-word
        if re.search(r'[a-zA-Z]\s*$', text):
            return 0.2  # Definitely truncated
        
        return 0.5  # Unknown
