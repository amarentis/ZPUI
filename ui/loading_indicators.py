from __future__ import division

from math import cos
from time import time

import math
from PIL import ImageDraw
from luma.core.render import canvas
from ui import Refresher
from ui.utils import clamp, Counter
from threading import Thread

"""
These classes subclass `Refresher` to show an animated screen.
Those screens are used to show the user something is happening in the background.

There are two possibility : either you know how much work is happening in the background, or you don't.

Vocabulary:
*Idle* word is used for classes that don't know how much processing is left to do
Example : throbber, dotted loading screen
*Progress* word is used for classes that know how much work is done and how much work is left.
Progress classes have a property `progress` that is used by the app programmer to indicate the advancement
of the task. (range [0-1])

"""


class CenteredTextRenderer(object):
    def draw_centered_text(self, draw, content, device_size):
        # type: (ImageDraw, str, tuple) -> None
        w, h = draw.textsize(content)
        dw, dh = device_size
        coords = (dw / 2 - w / 2, dh / 2 - h / 2)
        draw.text(coords, content, fill=True)


class LoadingIndicator(Refresher):

    def __init__(self, i, o, *args, **kwargs):
        Refresher.__init__(self, self.on_refresh, i, o)
        self._progress = 0
        Refresher.__init__(self, self.on_refresh, i, o, *args, **kwargs)
        self.t = None

    def on_refresh(self):
        pass

    def run_in_background(self):
        if self.t is not None or self.in_foreground:
            raise Exception("LoadingIndicator already running!")
        self.t = Thread(target=self.activate)
        self.t.daemon = True
        self.t.start()


class ProgressIndicator(LoadingIndicator):

    @property
    def progress(self):
        return float(self._progress)

    @progress.setter
    def progress(self, value):
        self._progress = clamp(value, 0, 1)
        self.refresh()  # doesn't work ? todo : check out why


# =========================concrete classes=========================
class IdleCircular(LoadingIndicator):

    def __init__(self, i, o, *args, **kwargs):
        LoadingIndicator.__init__(self, i, o, *args, **kwargs)
        self.refresh_interval = 0.01
        self._current_angle = 0
        self._current_range = 0  # range or width of the throbber
        self.rotation_speed = 360  # degree per second
        self.counter = Counter()  # We use a counter to make the animation independent of the refresh-rate
        self.start_time = 0

    def activate(self):
        self.start_time = time()
        self.counter.start()
        return Refresher.activate(self)

    def refresh(self):
        self.update_throbber_angle()
        c = canvas(self.o.device)
        c.__enter__()
        x, y = c.device.size
        radius = min(x, y) / 4
        draw = c.draw
        draw.arc(
            (
                x / 2 - radius, y / 2 - radius,
                x / 2 + 1 + radius, y / 2 + radius
            ),
            start=(self._current_angle - self._current_range / 2) % 360,
            end=(self._current_angle + self._current_range / 2) % 360,
            fill=True
        )
        self.o.display_image(c.image)

    def update_throbber_angle(self):
        self.counter.update()
        self._current_angle += self.rotation_speed * self.counter.elapsed
        time_since_activation = time() - self.start_time
        self._current_range = cos(time_since_activation * math.pi) / 2 + 0.5
        self._current_range = (self._current_range * 170) + 10
        self.counter.restart()


class IdleDottedMessage(LoadingIndicator):

    def __init__(self, i, o, *args, **kwargs):
        LoadingIndicator.__init__(self, i, o, *args, **kwargs)
        self.message = kwargs.pop("message") if "message" in kwargs else "Loading".center(o.cols).rstrip()
        self.dot_count = 0

    def on_refresh(self):
        LoadingIndicator.on_refresh(self)
        self.dot_count = (self.dot_count + 1) % 4
        return self.message + '.' * self.dot_count


class ProgressCircular(ProgressIndicator, CenteredTextRenderer):

    def __init__(self, i, o, *args, **kwargs):
        self.show_percentage = kwargs.pop("show_percentage") if "show_percentage" in kwargs else True
        LoadingIndicator.__init__(self, i, o, *args, **kwargs)

    def refresh(self):
        c = canvas(self.o.device)
        c.__enter__()
        x, y = c.device.size
        radius = min(x, y) / 4
        draw = c.draw
        center_coordinates = (x / 2 - radius, y / 2 - radius, x / 2 + radius, y / 2 + radius)
        draw.arc(center_coordinates, start=0, end=360 * self.progress, fill=True)
        if self.show_percentage:
            self.draw_centered_text(draw, "{:.0%}".format(self.progress), self.o.device.size)

        self.o.display_image(c.image)


class ProgressTextBar(ProgressIndicator):
    def __init__(self, i, o, *args, **kwargs):
        # We need to pop() these arguments instead of using kwargs.get() because they
        # have to be removed from kwargs to prevent TypeErrors
        self.message = kwargs.pop("message") if "message" in kwargs else "Loading"
        self.fill_char = kwargs.pop("fill_char") if "fill_char" in kwargs else "="
        self.empty_char = kwargs.pop("empty_char") if "empty_char" in kwargs else " "
        self.border_chars = kwargs.pop("border_chars") if "border_chars" in kwargs else "[]"
        self.show_percentage = kwargs.pop("show_percentage") if "show_percentage" in kwargs else False
        self.percentage_offset = kwargs.pop("percentage_offset") if "percentage_offset" in kwargs else 4
        LoadingIndicator.__init__(self, i, o, *args, **kwargs)
        self._progress = 0  # 0-1 range

    def get_progress_percentage(self):
        return '{}%'.format(self.progress * 100)

    @property
    def progress(self):
        return float(self._progress)

    @progress.setter
    def progress(self, value):
        self._progress = clamp(value, 0, 1)
        self.refresh()

    def get_progress_percentage_string(self):
        return '{}%'.format(int(self.progress * 100))

    def get_bar_str(self, size):
        size -= len(self.border_chars)  # to let room for the border chars and/or percentage string
        bar_end = self.border_chars[1]
        if self.show_percentage:
            percentage = self.get_progress_percentage_string()
            # Leaving room for the border chars and/or percentage string
            size -= self.percentage_offset if self.percentage_offset > 0 else len(percentage)
            bar_end += percentage.rjust(self.percentage_offset)

        filled_col_count = int(size * self.progress)
        unfilled_col_count = size - filled_col_count
        fill_str = self.fill_char * int(filled_col_count) + self.empty_char * int(unfilled_col_count)

        bar = '{s}{bar}{e}'.format(
            bar=fill_str,
            s=self.border_chars[0],
            e=bar_end
        )
        return bar

    def on_refresh(self):
        LoadingIndicator.on_refresh(self)
        bar = self.get_bar_str(self.o.cols)
        return [self.message.center(self.o.cols), bar]
