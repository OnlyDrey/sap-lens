"""Anchored SAP identifier matching; catalogue patterns are never assignments."""

from dataclasses import dataclass


def normalize_role(value):
    return "".join(value.split()).upper()


def role_scope(value):
    name = normalize_role(value)
    return (
        "business"
        if name.startswith("ZC:")
        else "release" if name.startswith("ZO:") else "other"
    )


@dataclass(frozen=True)
class Match:
    status: str
    candidates: tuple[str, ...] = ()


class RoleMatcher:
    def __init__(self, names):
        self.exact = {}
        self.prefixes = {}
        self.invalid_patterns = []
        for original in names:
            key = normalize_role(original)
            if not key or len(key) > 512 or any(c in key for c in "?[]\\"):
                self.invalid_patterns.append(original)
                continue
            if "*" in key:
                # Literal-prefix wildcard syntax only: no regex, glob classes or interior stars.
                if key.count("*") != 1 or not key.endswith("*") or len(key) == 1:
                    self.invalid_patterns.append(original)
                    continue
                self.prefixes.setdefault(key[:-1], []).append(original)
            else:
                self.exact.setdefault(key, []).append(original)

    def match(self, assigned):
        key = normalize_role(assigned)
        if not key or "*" in key or len(key) > 512:
            return Match("unmapped")
        exact = self.exact.get(key)
        if exact:
            return Match(
                "exact" if len(exact) == 1 else "ambiguous", tuple(sorted(exact))
            )
        for length in range(len(key), 0, -1):
            candidates = self.prefixes.get(key[:length])
            if candidates:
                return Match(
                    "wildcard" if len(candidates) == 1 else "ambiguous",
                    tuple(sorted(candidates)),
                )
        return Match("unmapped")
