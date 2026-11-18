"""Exact SAP username lists for the User Directory.

One parser serves the listing, the counts, the CSV export and the feedback shown to the user, so every consumer sees the same effective list.
Matching is exact and case-insensitive (SAP user names are case-insensitive); entries are never matched as substrings."""
import re

from user_access import normalize_username

MAX_USERNAMES = 500
SEPARATORS = re.compile(r'[\s,;]+')
# SAP user names are short identifiers. Anything with an at-sign (an e-mail), a control character or a very long token is reported, not matched.
VALID = re.compile(r'^[^\s@,;<>"\x00-\x1f]{1,40}$')


def parse_usernames(text):
    """-> dict(requested=[display names, first spelling, de-duplicated, in input order], duplicates=int, invalid=[entries])."""
    seen, requested, invalid, duplicates = {}, [], [], 0
    for token in SEPARATORS.split(text or ''):
        token = token.strip()
        if not token:
            continue
        if not VALID.match(token):
            if token not in invalid:
                invalid.append(token)
            continue
        key = normalize_username(token)
        if key in seen:
            duplicates += 1
            continue
        seen[key] = token
        requested.append(token)
    return dict(requested=requested, duplicates=duplicates, invalid=invalid)


def looks_like_username_list(text):
    """Deliberate rule for the search box: two or more entries separated by a newline, comma, semicolon or tab, or two or more whitespace-separated tokens that all look like SAP user names
    (no at-sign, no lower-case-only words of ordinary prose are excluded here: the box offers the switch, so the rule only decides what is *suggested*)."""
    parts = [part for part in re.split(r'[\n\r,;\t]+', text or '') if part.strip()]
    if len(parts) >= 2 and all(len(part.split()) == 1 for part in parts):
        return True
    tokens = (text or '').split()
    return len(tokens) >= 3 and all(VALID.match(token) and token.upper() == token and '@' not in token for token in tokens)


def apply(parsed, users):
    """-> (matched user keys in request order, unmatched display names)."""
    keys = {normalize_username(name): name for name in parsed['requested']}
    present = {key for key in keys if key in users}
    return [key for key in keys if key in present], [keys[key] for key in keys if key not in present]
