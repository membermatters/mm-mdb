import threading

import netifaces
import rel
import websocket
from websocket import WebSocket, WebSocketException
import mm
import config
import logging
from queue import Queue
import pymultidropbus
from pywiegand import WiegandReader

from pymultidropbus import helpers

logger = logging.getLogger("mm-mdb")
logger.setLevel(config.LOG_LEVEL)

interface_name = 'wlan0'
mac_address = str(netifaces.ifaddresses(interface_name)[netifaces.AF_LINK][0]['addr'])
ip_address = str(netifaces.ifaddresses(interface_name)[netifaces.AF_INET][0]['addr'])
serial_number = mac_address.replace(':', '')
logger.info("Device serial: " + serial_number)
logger.info("Device IP: " + ip_address)

PORTAL_WS_URL = config.PORTAL_WS_URL + serial_number


def on_error(ws: WebSocket, error: WebSocketException) -> None:
    logger.error(error)


def on_close(ws: WebSocket, close_status_code, close_msg: str) -> None:
    logger.info("WS closed with status code: " + str(close_status_code) + " and message: " + close_msg)


class CommandQueueThread(threading.Thread):
    def __init__(self, queue: Queue, mm_client: mm.MM, mdb_client: pymultidropbus.MDB, wiegandreader: WiegandReader):
        super().__init__()
        self._stop_event = threading.Event()
        self.queue = queue
        self.mm = mm_client
        self.mdb = mdb_client
        self.wiegandreader = wiegandreader

        logging.basicConfig(level=config.LOG_LEVEL)
        self.logger = logging.getLogger("mm-mdb:command_queue_thread")

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    def run(self):
        while True:
            command = self.queue.get()
            print(command)

            if command.get("command") == "VEND_REQUEST":
                item_price = command.get("data").get("price")
                item_number = command.get("data").get("item_number")

                # TODO: wait for RFID swipe or timeout
                rfid_card_number = "1234"

                self.mm.send_debit_request(item_price, rfid_card_number, item_number)
            if command.get("command") == "DEBIT_RESULT":
                success = command.get("data").get("success")
                balance = command.get("data").get("balance")
                balance = int(float(balance) * 100)  # convert dollars to cents

                # TODO: (maybe) update to be actual price not balance
                if success:
                    self.mdb.approve_vend(balance)
                else:
                    self.mdb.deny_vend()


if __name__ == "__main__":
    commands_queue = Queue()
    mdb = pymultidropbus.MDB(commands_queue)
    mm = mm.MM(config.API_SECRET, ip_address)
    wr = WiegandReader(6, 5)
    websocket_client = websocket.WebSocketApp(PORTAL_WS_URL,
                                              on_open=mm.ws_on_open,
                                              on_message=mm.ws_on_message,
                                              on_error=mm.ws_on_error,
                                              on_close=mm.ws_on_close)
    queue_thread = CommandQueueThread(commands_queue, mm, mdb, wr)
    queue_thread.start()

    # Set dispatcher to automatic reconnection, 5 second reconnect delay if connection closed unexpectedly
    websocket_client.run_forever(dispatcher=rel, reconnect=5)
    rel.signal(2, rel.abort)  # Keyboard Interrupt
    rel.dispatch()
