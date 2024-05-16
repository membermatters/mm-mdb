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
import pigpio
import wiegand
import os

logger = logging.getLogger("mm-mdb")
logger.setLevel(config.MDB_LOG_LEVEL)

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
    def __init__(self, queue: Queue, mm_client: mm.MM, mdb_client: pymultidropbus.MDB):
        super().__init__()
        self.max_price = None
        self.min_price = None
        self._stop_event = threading.Event()
        self.queue = queue
        self.mm = mm_client
        self.mdb = mdb_client

        logging.basicConfig(level=config.MDB_LOG_LEVEL)
        self.logger = logging.getLogger("mm-mdb:command_queue_thread")

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    def run(self):
        while self._stop_event.is_set() is False:
            command = self.queue.get()

            if command.get("command") == "CSH_RESET":
                # reader config data
                self.mdb._send_cmd("01 01 10 36 0A 02 07 0D")  # TODO: make this a function and not a call to _send_cmd

            elif command.get("command") == "CSH_SETUP":
                self.min_price = command.get("data").get("min_price")
                self.max_price = command.get("data").get("max_price")
                # ack already sent

            elif command.get("command") == "VEND_REQUEST":
                # ack already sent
                item_price = command.get("data").get("item_price")
                item_number = command.get("data").get("item_number")

                if not item_price:
                    logger.warning("Item price not provided!")
                    item_number = 0

                if not item_number:
                    logger.warning("Item number not provided!")
                    item_number = 0

                # TODO: wait for RFID swipe or timeout
                rfid_card_number = "5486440"

                self.mm.send_debit_request(item_price, rfid_card_number, item_number)

            elif command.get("command") == "VEND_CANCELLED":
                # deny_vend() already sent
                pass

            elif command.get("command") == "VEND_SUCCESS":
                # ack already sent
                item_number = command.get("data").get("item_number")

            elif command.get("command") == "VEND_FAILURE":
                # TODO: handle refunds
                refund_success = True
                if refund_success:
                    self.mdb.send_ack()
                else:
                    self.mdb.send_ack()
                    # TODO: send MALFUNCTION ERROR code 1100yyyy
                    # self.mdb._send_cmd("")

            elif command.get("command") == "VEND_SESSION_COMPLETE":
                # reader_session_ended already sent
                pass
                # self.mdb.start_cashless_session(420)

            elif command.get("command") == "CSH_READER_DISABLED":
                # ack already sent
                pass

            elif command.get("command") == "CSH_READER_ENABLED":
                # ack already sent
                pass
                # self.mdb.start_cashless_session(420)

            elif command.get("command") == "CSH_READER_CANCEL":
                # reader_cancelled already sent
                pass

            elif command.get("command") == "CSH_EXPANSION":
                manufacturer_code = command.get("data").get("manufacturer_code")
                vmc_serial_number = command.get("data").get("serial_number")
                model_number = command.get("data").get("model_number")
                software_version = command.get("data").get("software_version")

                # reader peripheral id data
                # TODO: document and generate this dynamically
                self.mdb._send_cmd(
                    "09 42 4D 53 30 30 30 30 30 30 30 30 30 30 30 31 30 30 30 30 30 30 30 30 30 30 30 31 01 01")

            elif command.get("command") == "DEBIT_RESULT":
                success = command.get("data").get("success")
                balance_dollars = float(command.get("data").get("balance"))
                balance_cents = int(balance_dollars * 100)  # convert dollars to cents
                amount = command.get("data").get("amount") or 0

                if success:
                    self.mdb.approve_vend(amount)
                else:
                    self.mdb.deny_vend()


if __name__ == "__main__":
    if config.PROCESS_AFFINITY:
        affinity_mask = {config.PROCESS_AFFINITY}  # The third core is used by default
        pid = 0  # 0 is the current process
        os.sched_setaffinity(pid, affinity_mask)

    commands_queue = Queue()
    mdb = pymultidropbus.MDB(commands_queue, log_level=config.MDB_LOG_LEVEL)
    mm = mm.MM(config.API_SECRET, ip_address, commands_queue)
    queue_thread = CommandQueueThread(commands_queue, mm, mdb)


    def callback(bits, value):
        print("bits={} value={}".format(bits, value))
        mdb.start_cashless_session(420)


    pi = pigpio.pi()
    wiegand_reader = wiegand.Decoder(pi, 6, 5, callback)
    websocket_client = websocket.WebSocketApp(PORTAL_WS_URL,
                                              on_open=mm.ws_on_open,
                                              on_message=mm.ws_on_message,
                                              on_error=mm.ws_on_error,
                                              on_close=mm.ws_on_close)

    queue_thread.start()

    # Set dispatcher to automatic reconnection, 5 second reconnect delay if connection closed unexpectedly
    websocket_client.run_forever(dispatcher=rel, reconnect=5)
    rel.signal(2, rel.abort)  # Keyboard Interrupt
    rel.dispatch()
