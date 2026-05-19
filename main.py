PREDICTIONS = 10


def predict_digits(recent_digits, n=10):
    if len(recent_digits) < 20:
        return []

    window = recent_digits[-50:] if len(recent_digits) >= 50 else recent_digits
    counts = Counter(window)

    freq_top = [d for d, _ in counts.most_common(10)]

    last10 = recent_digits[-10:]
    gap_digits = [d for d in range(10) if d not in last10]

    current = recent_digits[-1]

    next_digits = []
    for i in range(len(recent_digits) - 1):
        if recent_digits[i] == current:
            next_digits.append(recent_digits[i + 1])

    pattern_top = []
    if next_digits:
        pattern_counts = Counter(next_digits)
        pattern_top = [d for d, _ in pattern_counts.most_common(10)]

    last5 = recent_digits[-5:]
    streak_digit = None

    if len(set(last5)) == 1:
        streak_digit = last5[0]

    scores = {d: 0 for d in range(10)}

    for i, d in enumerate(freq_top[:10]):
        scores[d] += (10 - i)

    for d in gap_digits[:10]:
        scores[d] += 2

    for i, d in enumerate(pattern_top[:10]):
        scores[d] += (10 - i)

    if streak_digit is not None:
        scores[streak_digit] -= 5

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    return [d for d, s in ranked[:n]]