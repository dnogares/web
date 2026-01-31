import re

def parse_referencias(text: str) -> list:
    if not text: return []
    
    # Logic from catastro_exp.py
    pattern = r'\b[0-9A-Z]{14}(?:[0-9A-Z]{6})?\b'
    matches = re.findall(pattern, text.upper())
    
    # Normalized search
    text_limpio = text.upper().replace(" ", "").replace("-", "").replace(".", "").replace(",", "")
    matches_limpios = re.findall(pattern, text_limpio)
    
    all_matches = set(matches + matches_limpios)
    return sorted(list(all_matches))

# Test cases
test_cases = [
    "8484102VK3788S0001IA", # Valid 20 chars
    "8484102VK3788S",       # Valid 14 chars
    "Ref: 1234567AA1234A",  # Valid in context
    "1234567 AA 1234 A 0001 AB", # Common user format with spaces
    "8484102vk3788s0001ia", # Lowercase
    "8484102-VK3788S-0001IA", # With dashes
    "8484102 VK3788S 0001 IA", # Spaces
    "ABC12345678901", # 13 chars (invalid)
    "ABC123456789012345", # 18 chars (invalid)
]

print("--- Testing current parse_referencias ---")
for tc in test_cases:
    result = parse_referencias(tc)
    print(f"Input: '{tc}' -> Matches: {result}")
