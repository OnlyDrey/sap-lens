"""WCAG relative luminance for sRGB theme validation."""

def luminance(color):
    channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
    return sum(value * weight for value, weight in zip(linear, [.2126, .7152, .0722]))


def contrast(first, second):
    light, dark = sorted([luminance(first), luminance(second)], reverse=True)
    return (light + .05) / (dark + .05)


def mix(first, second, amount):
    """Blend two #rrggbb colors; amount is the share of the first."""
    channels = [round(int(first[i:i + 2], 16) * amount + int(second[i:i + 2], 16) * (1 - amount)) for i in (1, 3, 5)]
    return '#' + ''.join(f'{value:02x}' for value in channels)


def derive_secondary(palette):
    """Secondary color for a palette saved before it existed: a soft accent tint of the card color that keeps text readable."""
    import re
    keys = ('accent', 'surface', 'text')
    if not all(isinstance(palette.get(key), str) and re.fullmatch(r'#[0-9a-fA-F]{6}', palette[key]) for key in keys):
        return '#2a3156'
    for source, amount in ((palette['accent'], .18), (palette['text'], .10), (palette['text'], .05)):
        candidate = mix(source, palette['surface'], amount)
        if contrast(palette['text'], candidate) >= 4.5:
            return candidate
    return palette['surface']
