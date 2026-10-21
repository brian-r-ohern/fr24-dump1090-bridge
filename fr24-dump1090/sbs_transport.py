"""Recover TCP sessions that remain established but stop delivering bytes."""
import socket
import time

class MessageWatchdog:
    """Track successfully parsed aircraft messages, independently of status bytes."""
    def __init__(self, seconds=60, clock=time.monotonic):
        self.clock=clock;self.seconds=seconds;self.last_message=clock()
    def accepted(self):self.last_message=self.clock()
    def check(self):
        if self.clock()-self.last_message>=self.seconds:
            raise TimeoutError(f'SBS valid MSG idle for {self.seconds:g}s; reconnecting')

def received_chunks(sock, idle_seconds=60, clock=time.monotonic, watchdog=None):
    last_byte=clock()
    while True:
        if watchdog:watchdog.check()
        try:chunk=sock.recv(65536)
        except socket.timeout:
            if clock()-last_byte>=idle_seconds:
                raise TimeoutError(f'SBS input idle for {idle_seconds:g}s; reconnecting')
            continue
        if not chunk:raise ConnectionError('receiver closed TCP/30003 connection')
        last_byte=clock()
        yield chunk
