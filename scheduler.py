"""Optional standalone scheduler; use a process supervisor for continuous operation."""
import logging
import signal
import threading

from app import scheduler_tick, DB, now
from notifications import process_outbox


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    stop = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stop.set())
    def deliver_notifications():
        while not stop.is_set():
            try:
                process_outbox(DB, clock=now)
            except Exception:
                logging.exception('Notification worker failed; retrying')
            stop.wait(5)
    worker = threading.Thread(target=deliver_notifications, daemon=True)
    worker.start()
    while not stop.is_set():
        try:
            result = scheduler_tick()
            logging.info('Schedule reconciled at %s', result['last_tick'])
        except Exception:
            logging.exception('Scheduler reconciliation failed; retrying')
        stop.wait(5)
    worker.join(timeout=20)


if __name__ == '__main__':
    main()
