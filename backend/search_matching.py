"""Literal, case-insensitive text search with anchored SAP '*' patterns.

No regular expressions or fnmatch character classes are interpreted. Plain searches
retain contains matching. Explicit patterns are anchored to the complete field.
"""
def text_matches(value, query):
    text, pattern = str(value or '').lower(), str(query or '').strip().lower()
    if '*' not in pattern:
        return pattern in text
    parts = pattern.split('*')
    if not text.startswith(parts[0]):
        return False
    position = len(parts[0])
    for part in parts[1:-1]:
        found = text.find(part, position)
        if found < 0:
            return False
        position = found + len(part)
    return text.endswith(parts[-1]) and len(text) - len(parts[-1]) >= position



def search_fields(query, *fields):
    return any(text_matches(field, query) for field in fields) if '*' in query else text_matches(' '.join(str(field or '') for field in fields), query)
