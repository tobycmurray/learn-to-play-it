def fmt_time(secs):
    m, s = divmod(secs, 60)
    return f"{int(m)}:{s:05.2f}"


def fmt_pitch(cents):
    c = round(cents)
    if c == 0:
        return "0c"
    elif abs(c) < 100:
        return f"{c:+}c"
    else:
        st = int(c / 100)
        rem = c - st * 100
        return f"{st:+}st" if rem == 0 else f"{st:+}st{rem:+}c"
