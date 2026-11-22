import logging
import Levenshtein
from typing import List

logger = logging.getLogger(__name__)

def clean(text: str, blocklist: List[str]) -> str:
    """
    Apply blocklist scanning, repetition detection, and whitespace cleanup to the transcript.
    """
    if not text:
        return ""

    # 1. BLOCKLIST SCAN
    lines = text.split("\n")
    cleaned_lines = []
    
    for line in lines:
        stripped_line = line.strip()
        # Remove common punctuation/formatting when checking blocklist matches
        normalized_line = "".join(ch for ch in stripped_line if ch.isalnum() or ch.isspace()).lower().strip()
        
        matched = False
        for entry in blocklist:
            normalized_entry = "".join(ch for ch in entry if ch.isalnum() or ch.isspace()).lower().strip()
            if normalized_line == normalized_entry:
                logger.info(f"Filtered hallucination: {stripped_line}")
                matched = True
                break
                
        if not matched:
            cleaned_lines.append(line)
            
    text = "\n".join(cleaned_lines)

    # 2. REPETITION DETECTOR
    # Split into segments by double newline (paragraphs)
    segments = [s.strip() for s in text.split("\n\n") if s.strip()]
    if not segments:
        return ""

    cleaned_segments = []
    i = 0
    while i < len(segments):
        current_segment = segments[i]
        
        # Look ahead at the next segments (sliding window of 3)
        # Check if the next segment is highly similar
        is_repetition = False
        if i > 0:
            prev_segment = cleaned_segments[-1]
            max_len = max(len(prev_segment), len(current_segment), 1)
            dist = Levenshtein.distance(prev_segment, current_segment)
            similarity = 1.0 - (dist / max_len)
            
            if similarity > 0.85:
                logger.info(f"Removed repeated segment: '{current_segment[:60]}...' (similarity: {similarity:.2f})")
                is_repetition = True
                
        if not is_repetition:
            cleaned_segments.append(current_segment)
            
        i += 1

    text = "\n\n".join(cleaned_segments)

    # 3. WHITESPACE CLEANUP
    # Collapse 3+ consecutive newlines -> 2
    import re
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Strip trailing whitespace on each line, but preserve single/double newlines
    lines = text.split("\n")
    lines = [l.rstrip() for l in lines]
    text = "\n".join(lines)
    
    return text.strip()
