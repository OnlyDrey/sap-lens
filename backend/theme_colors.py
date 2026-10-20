"""WCAG relative luminance for sRGB theme validation."""

def luminance(color):
    channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
    return sum(value * weight for value, weight in zip(linear, [.2126, .7152, .0722]))


def contrast(first, second):
    light, dark = sorted([luminance(first), luminance(second)], reverse=True)
    return (light + .05) / (dark + .05)
