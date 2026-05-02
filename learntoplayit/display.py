import os
import sys
import tty
import termios
import select

from .player import (
    SPEED_STEP, PITCH_STEP, SEEK_SECONDS, NUDGE_SECONDS,
)
from .fmt import fmt_time, fmt_pitch

WAVEFORM_BLOCKS = " ▁▂▃▄▅▆▇█"
WAVEFORM_ROWS = 8
DISPLAY_LINES = 1 + WAVEFORM_ROWS + 1


def _read_key(timeout=0.1):
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        if select.select([sys.stdin], [], [], timeout)[0]:
            return sys.stdin.read(1)
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


class TerminalDisplay:

    def __init__(self, player):
        self.player = player

    def run(self):
        p = self.player
        print(f"Playing: {p.part} ({p.mode})")
        print("Controls: SPACE=play/pause  W/S=speed  E/D=pitch  Z/X/C/V=seek  H=hold")
        print("          [/]=loop start/end  L=loop  B=click  N=count-in  1/2/3=solo/backing/mix  0=restart  Q=quit")
        print()

        p.start()
        try:
            while not p.quit:
                self._print_status()
                key = _read_key()
                if key is not None:
                    self._handle_key(key)
        finally:
            p.stop()
            print()

    def _status_text(self):
        p = self.player

        if p.hold is not None:
            state = "⏺"
        elif p.playing:
            state = "▶"
        else:
            state = "⏸"
        speed_pct = int(round(p.speed * 100))

        bounds = p.loop_bounds
        if bounds is not None and (bounds[0] is not None or bounds[1] is not None):
            ls_str = fmt_time(bounds[0]) if bounds[0] is not None else "?"
            le_str = fmt_time(bounds[1]) if bounds[1] is not None else "?"
            loop_str = f"loop: {'ON' if bounds[2] else 'OFF'} {ls_str}-{le_str}"
        else:
            loop_str = "loop: OFF"

        click_str = "click: ON" if p.click_active else "click: OFF"
        count_in_str = "count-in: ON" if p.count_in_enabled else "count-in: OFF"

        return (
            f"  {state} {fmt_time(p.playback_position)} / {fmt_time(p.song_duration)}  |  "
            f"speed: {speed_pct}%  |  pitch: {fmt_pitch(p.cents)}  |  "
            f"{loop_str}  |  "
            f"{click_str}  |  {count_in_str}  |  "
            f"mode: {p.mode}  |  part: {p.part}"
        )

    @staticmethod
    def _bins_to_rows(bins):
        levels = len(WAVEFORM_BLOCKS) - 1
        rows = []
        for row in range(WAVEFORM_ROWS - 1, -1, -1):
            threshold = row / WAVEFORM_ROWS
            next_threshold = (row + 1) / WAVEFORM_ROWS
            line = []
            for v in bins:
                if v >= next_threshold:
                    line.append(WAVEFORM_BLOCKS[-1])
                elif v > threshold:
                    frac = (v - threshold) / (next_threshold - threshold)
                    line.append(WAVEFORM_BLOCKS[max(1, int(frac * levels))])
                else:
                    line.append(" ")
            rows.append("".join(line))
        return rows

    @staticmethod
    def _marker_line(waveform_data, width):
        markers = [" "] * width
        markers[waveform_data.cursor_col] = "↑"
        if waveform_data.loop_start_col is not None:
            markers[waveform_data.loop_start_col] = "["
        if waveform_data.loop_end_col is not None:
            markers[waveform_data.loop_end_col] = "]"
        return "  " + "".join(markers)

    def _print_status(self):
        p = self.player
        term_width = os.get_terminal_size().columns
        status = self._status_text()[:term_width].ljust(term_width)

        show_waveform = not p.playing and p.hold is None
        waveform_width = term_width - 4

        if show_waveform and waveform_width >= 10:
            wd = p.waveform_bins(waveform_width)
            rows = self._bins_to_rows(wd.bins)
            markers = self._marker_line(wd, waveform_width)
            body = [f"  {row}"[:term_width] for row in rows] + [markers[:term_width]]
        else:
            if show_waveform:
                hint = "  (widen terminal to see waveform)"
            elif p.hold is not None:
                hint = "  (hold active — H to release)"
            else:
                hint = "  (SPACE to pause and show waveform)"
            blank = "".ljust(term_width)
            body = [blank] * (DISPLAY_LINES - 1)
            body[WAVEFORM_ROWS // 2] = hint[:term_width].ljust(term_width)

        assert len(body) == DISPLAY_LINES - 1
        lines = [status] + body
        print("\r" + "\n".join(lines), end="", flush=True)
        print(f"\033[{DISPLAY_LINES - 1}A\r", end="", flush=True)

    def _handle_key(self, key):
        p = self.player
        if key == " ":
            p.toggle_play()
        elif key.lower() == "q":
            p.quit = True
        elif key == "0":
            p.restart()
        elif key.lower() == "w":
            p.change_speed(SPEED_STEP)
        elif key.lower() == "s":
            p.change_speed(-SPEED_STEP)
        elif key.lower() == "e":
            p.change_pitch(PITCH_STEP)
        elif key.lower() == "d":
            p.change_pitch(-PITCH_STEP)
        elif key.lower() == "z":
            p.seek(-SEEK_SECONDS)
        elif key.lower() == "x":
            p.seek(-NUDGE_SECONDS)
        elif key.lower() == "c":
            p.seek(NUDGE_SECONDS)
        elif key.lower() == "v":
            p.seek(SEEK_SECONDS)
        elif key == "1":
            p.set_mode("solo")
        elif key == "2":
            p.set_mode("backing")
        elif key == "3":
            p.set_mode("mix")
        elif key.lower() == "h":
            p.toggle_hold()
        elif key == "[":
            p.set_loop_start()
        elif key == "]":
            p.set_loop_end()
        elif key.lower() == "l":
            p.toggle_loop()
        elif key.lower() == "b":
            p.toggle_click()
        elif key.lower() == "n":
            p.toggle_count_in()
