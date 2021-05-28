from typing import List

import intervaltree


class IdentifiedInterval(intervaltree.Interval):

    def __eq__(self, other):
        return id(self) == id(other)

    def __hash__(self):
        return hash(id(self))


class IntervalWithTimestamp:
    __slots__ = ('interval', 'creation_time')

    def __init__(self, interval: intervaltree.Interval, timestamp: int):
        self.interval = interval
        self.creation_time = timestamp

    def __repr__(self):
        return f'{self.__class__.__name__}({repr(self.interval)}, {self.creation_time})'


class EvictedIntervalTree(intervaltree.IntervalTree):
    def __init__(self, intervals=None):
        super().__init__(intervals)
        self.intervals_time_index: List[IntervalWithTimestamp] = []

    def __setitem__(self, index, value):
        raise NotImplementedError()

    def add(self, interval):
        raise NotImplementedError()

    def addi(self, begin, end, data=None):
        raise NotImplementedError()

    def add_and_remember(self, begin, end, data, timestamp):
        """
        Remember the created interval and it's creation time
        """
        new_interval = IdentifiedInterval(begin, end, data)
        self.intervals_time_index.append(IntervalWithTimestamp(new_interval, timestamp))
        return super().add(new_interval)

    def remove(self, interval):
        raise NotImplementedError

    def discard(self, interval):
        raise NotImplementedError

    def evict(self, older_than_timestamp: float):
        if not self.intervals_time_index:
            return
        for idx, interval_with_timestamp in enumerate(self.intervals_time_index):
            if interval_with_timestamp.creation_time > older_than_timestamp:
                break
            super().discard(interval_with_timestamp.interval)
        if idx:
            self.intervals_time_index = self.intervals_time_index[idx:]

