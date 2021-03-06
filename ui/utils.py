from collections import namedtuple, Sequence
from functools import wraps
from time import time, sleep

from PIL import ImageOps

from helpers import setup_logger

logger = setup_logger(__name__, "info")


def to_be_foreground(func):
    """ A safety check wrapper so that certain functions can't possibly be called
    if UI element is not the one active"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if self.in_foreground:
            return func(self, *args, **kwargs)
        else:
            return False

    return wrapper


def clamp(value, _min, _max):
    """
    Returns a value clamped between two bounds (inclusive)
    >>> clamp(17, 0, 100)
    17
    >>> clamp(-89, 0, 100)
    0
    >>> clamp(65635, 0, 100)
    100
    """
    return max(_min, min(value, _max))


def is_sequence_not_string(value):
    """
    Checks if the value passed is a sequence, like a list or tuple - except strings.
    """
    return isinstance(value, Sequence) and not isinstance(value, basestring)


def modulo_list_index(value, _list):
    """
    Returns an always valid list index. Repeats the list circularly.
    >>> robots=['R2D2', 'C3PO', 'HAL9000']
    >>> robots[modulo_list_index(0, robots)]
    'R2D2'
    >>> robots[modulo_list_index(3, robots)]
    'R2D2'
    >>> [robots[modulo_list_index(i, robots)] for i in range(10)]
    ['R2D2', 'C3PO', 'HAL9000', 'R2D2', 'C3PO', 'HAL9000', 'R2D2', 'C3PO', 'HAL9000', 'R2D2']
    """
    return value % len(_list)


def clamp_list_index(value, _list):
    """
    Returns a list index clamped to the bounds of the list.
    Useful to prevent iterating out of bounds, repeats the bounds values.
    >>> astronauts = ['Collins', 'Armstrong', 'Aldrin']
    >>> astronauts[clamp_list_index(0, astronauts)]
    'Collins'
    >>> astronauts[clamp_list_index(2, astronauts)]
    'Aldrin'
    >>> astronauts[clamp_list_index(9000, astronauts)]
    'Aldrin'
    >>> astronauts[clamp_list_index(-666, astronauts)]
    'Collins'
    """
    return clamp(value, 0, len(_list) - 1)


def check_value_lock(func):
    """ A safety check wrapper so that there's no race conditions
    between functions that are able to change position/value"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        assert self.value_lock, "Class has no member self.value_lock"  # todo:maybe we should create it here ?
        # Value-changing code is likely to run in concurrent thread and therefore we need a lock
        if self.__locked_name__ is not None:
            logger.warning(
                "Another function already working with the value! Name is {}, current is {}".format(
                    self.__locked_name__,
                    func.__name__
                )
            )
        with self.value_lock:
            self.__locked_name__ = func.__name__
            logger.debug("Locked function {}".format(func.__name__))
            result = func(self, *args, **kwargs)
        logger.debug("Unlocked function {}".format(func.__name__))
        self.__locked_name__ = None
        return result

    return wrapper


class Chronometer(object):
    """
    This object measures time.
    >>> cron = Chronometer()
    >>> cron.active
    False
    >>> cron.start()
    >>> cron.active
    True
    >>> sleep(1)
    >>> cron.update()
    >>> round(cron.elapsed)
    1.0
    >>> cron.pause()
    >>> sleep(1)
    >>> round(cron.elapsed)
    1.0
    >>> cron.toggle()  # or cron.resume()
    >>> sleep(1)
    >>> cron.update()
    >>> round(cron.elapsed)
    2.0
    >>> cron.restart()
    >>> sleep(1)
    >>> cron.update()
    >>> round(cron.elapsed)
    1.0
    """
    def __init__(self):
        self.__active = False
        self.__cron = Ticker()
        self.__elapsed = 0

    @property
    def active(self):
        # type: () -> bool
        """whether the Chronometer is counting time"""
        return self.__active

    @property
    def elapsed(self):
        # type: () -> float
        """returns the elapsed time"""
        return self.__elapsed

    def update(self):
        # type: () -> None
        """Updates the chronometer with the current time"""
        if not self.__active:
            return
        self.__elapsed += self.__cron.tick()

    def stop(self):
        # type: () -> None
        """Stop and resets the Chronometer"""
        self.__cron.tick()
        self.__elapsed = 0
        self.__active = False

    def pause(self):
        # type: () -> None
        """Pauses the Chronometer, but keeps the measured time so far"""
        self.__active = False

    def resume(self):
        # type: () -> None
        """Resumes measuring time after a pause"""
        self.__cron.tick()
        self.__active = True

    def start(self):
        # type: () -> None
        """Starts measuring time"""
        self.stop()
        self.resume()

    def toggle(self):
        # type: () -> None
        """Toggles between pause and resume"""
        self.pause() if self.active else self.resume()

    def restart(self):
        # type: () -> None
        """Resets the Chronometer and starts a new measure immediatly"""
        self.start()


class Ticker(object):
    """
    This object returns the time elapsed between two calls to it's `tick()` function
    >>> ticker = Ticker()
    >>> sleep(1)
    >>> elapsed = ticker.tick()
    >>> round(elapsed)  #rounded because time.sleep() is not that precise
    1.0
    """
    def __init__(self):
        self.__active = False
        self.__last_call = time()

    def tick(self):
        """
        :rtype: int
        :return: the time elapsed since the previous tick
        """
        now = time()
        elapsed = now - self.__last_call
        self.__last_call = now
        return elapsed


Rect = namedtuple('Rect', ['left', 'top', 'right', 'bottom'])
