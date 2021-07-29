from datetime import datetime
from enum import Enum


class Emojis(Enum):
    Unscheduled = '<:unscheduled:863827574806151185>'
    Stopped = '<:stopped:863827574768533545>'
    Scheduled = '<:scheduled:863827574798286878>'
    Notice = '<:notice:863827574906945556>'
    Next = '<:next:863827574740221985>'
    Info = '<:info:863827574681632790>'
    ElapsedDone = '<:elapsednone:863827574428925974>'
    Elapsed = '<:elapsed:863827574634053713>'
    Cancelled = '<:cancelled:863827574677569536>'
    Alert = '<:alert:863827574697099284>'


class SlotKey(Enum):
    Reset = 'Reset'
    Unscheduled = 'Unscheduled'


class MVPTimes:
    """
    Class for storing a key: rows mapping where several time slots fall under a single ch/map
    """

    def __init__(self, key='', single_time=None):
        self.key: str = key
        self.discord: str = ''
        self.ign: str = ''
        self.single_time = single_time
        self.mvp_times = []

    def add(self, mvp_row, calculated_datetime):
        self.mvp_times.append({'row': mvp_row, 'dt': calculated_datetime})


class MVPGap:
    """
    Class for storing a the start, end time, and timedelta of gaps between mvps
    """

    def __init__(self, start_date=None, last_date=None):
        self.key: str = SlotKey.Unscheduled.value
        self.start_date: datetime = start_date
        self.last_date: datetime = last_date
        self.gap_size: int = 0
