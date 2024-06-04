import mm
import config

import threading
import netifaces
import rel
import websocket
from websocket import WebSocket, WebSocketException
import logging
import time
from queue import Queue
import pymultidropbus
import pywiegandpi
import pymultidropbus.protocol as protocol
import pymultidropbus.protocol.peripherals.Cashless as Cashless

logging.basicConfig()
logger = logging.getLogger("mm-mdb")
logger.setLevel(config.MDB_LOG_LEVEL)


interface_name = 'wlan0'
mac_address = str(netifaces.ifaddresses(interface_name)[netifaces.AF_LINK][0]['addr'])
ip_address = str(netifaces.ifaddresses(interface_name)[netifaces.AF_INET][0]['addr'])
serial_number = mac_address.replace(':', '')
logger.info("Device serial: " + serial_number)
logger.info("Device IP: " + ip_address)

PORTAL_WS_URL = config.PORTAL_WS_URL + serial_number

CURRENT_SESSION_CARD_ID: str = ""


class WsCommandQueueThread(threading.Thread):
    def __init__(self, queue: Queue, mm_client: mm.MM, mdb_client: pymultidropbus.CashlessPeripheral):
        super().__init__()
        self._stop_event = threading.Event()
        self.queue = queue
        self.mm = mm_client
        self.mdb = mdb_client

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    def run(self):
        global CURRENT_SESSION_CARD_ID
        while self._stop_event.is_set() is False:
            command = self.queue.get()
            logger.debug(command)

            if command.get("command") == "BALANCE_RESULT":
                success = command.get("data").get("success")

                if success:
                    balance_cents = int(command.get("data").get("balance"))
                    logger.debug("Balance request successful: " + str(balance_cents))
                    self.mdb.start_cashless_session(balance_cents)
                else:
                    logger.warning("Balance request failed!")
                    CURRENT_SESSION_CARD_ID = ""

            if command.get("command") == "DEBIT_RESULT":
                success = command.get("data").get("success")
                # balance_dollars = float(command.get("data").get("balance"))
                # balance_cents = int(balance_dollars * 100)  # convert dollars to cents
                amount = command.get("data").get("amount") or 0

                if success:
                    self.mdb.approve_vend(amount)
                else:
                    self.mdb.deny_vend()


class CommandQueueThread(threading.Thread):
    def __init__(self, queue: Queue, mm_client: mm.MM, mdb_client: pymultidropbus.CashlessPeripheral):
        super().__init__()
        self._stop_event = threading.Event()
        self.queue = queue
        self.mm = mm_client
        self.mdb = mdb_client

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    def run(self):
        global CURRENT_SESSION_CARD_ID
        while self._stop_event.is_set() is False:
            command: protocol.MdbCommandEvent = self.queue.get()
            logger.debug("Got command: " + str(command.command))

            if command.command == Cashless.MdbCommand.SETUP_CONFIG_DATA:
                # reader config data
                self.mdb._send_cmd("01 01 10 36 01 02 07 0D")  # TODO: make this a function and not a call to _send_cmd

            elif command.command == Cashless.MdbCommand.SETUP_PRICE_DATA:
                min_price = command.min_price
                max_price = command.max_price
                logger.debug(f"Got min price: {min_price} and max price: {max_price}")
                # ack already sent

            elif command.command == Cashless.MdbCommand.EXPANSION_REQUEST_ID:
                manufacturer_code = command.manufacturer_code
                vmc_serial_number = command.serial_number
                model_number = command.model_number
                software_version = command.software_version
                logger.debug(f"Got expansion request id: {manufacturer_code}, {vmc_serial_number}, {model_number}, {software_version}")

                # reader peripheral id data
                # TODO: document and generate this dynamically
                self.mdb._send_cmd(
                    "09 42 4D 53 30 30 30 30 30 30 30 30 30 30 30 31 30 30 30 30 30 30 30 30 30 30 30 31 01 01")

            elif command.command == Cashless.MdbCommand.RESET:
                logger.info("Cashless reader reset!")

            elif command.command == Cashless.MdbCommand.READER_DISABLE:
                # ack already sent
                logger.info("Cashless reader disabled!")

            elif command.command == Cashless.MdbCommand.READER_ENABLE:
                # ack already sent
                # self.mdb.start_cashless_session(420)
                logger.info("Cashless reader enabled!")

            if command.command == Cashless.MdbCommand.VEND_REQUEST:
                # ack already sent
                item_price = command.item_price
                item_number = command.item_number

                if not item_price:
                    logger.warning("Item price not provided!")
                    item_price = 0

                if not item_number:
                    logger.warning("Item number not provided!")

                logger.debug(f"Got vend request for item {item_number} with price {item_price} cents")

                rfid_card_number = CURRENT_SESSION_CARD_ID
                self.mm.send_debit_request(item_price, rfid_card_number, item_number)

            elif command.command == Cashless.MdbCommand.VEND_CANCEL:
                # deny_vend() already sent
                logger.debug("Vend cancelled!")

            elif command.command == Cashless.MdbCommand.VEND_SUCCESS:
                # ack already sent
                item_number = command.item_number
                logger.info(f"Vend success for item {item_number}")

            elif command.command == Cashless.MdbCommand.VEND_FAILURE:
                # TODO: handle refunds
                logger.warning("Vend failure!")
                refund_success = True
                if refund_success:
                    self.mdb.send_ack()
                else:
                    self.mdb.send_ack()
                    # TODO: send MALFUNCTION ERROR code 1100yyyy

            elif command.command == Cashless.MdbCommand.VEND_SESSION_COMPLETE:
                # reader_session_ended already sent
                logger.info("Vend session complete!")
                CURRENT_SESSION_CARD_ID = ""

            elif command.command == Cashless.MdbCommand.READER_CANCEL:
                # reader_cancelled already sent
                logger.debug("Reader cancelled!")


if __name__ == "__main__":
    mdb_commands_queue = Queue()
    ws_commands_queue = Queue()
    mdb = pymultidropbus.CashlessPeripheral(mdb_commands_queue, log_level=config.MDB_LOG_LEVEL, process_affinity=config.PROCESS_AFFINITY)
    mm = mm.MM(config.API_SECRET, ip_address, ws_commands_queue, mdb_commands_queue)
    queue_thread = CommandQueueThread(mdb_commands_queue, mm, mdb)
    ws_queue_thread = WsCommandQueueThread(ws_commands_queue, mm, mdb)

    def wiegand_callback(bits: int, value: int):
        global CURRENT_SESSION_CARD_ID
        if config.MIN_CARD_SCAN_VALUE and value > config.MIN_CARD_SCAN_VALUE:
            CURRENT_SESSION_CARD_ID = str(value)
            logger.info("Card scanned: " + CURRENT_SESSION_CARD_ID)
            mm.send_balance_request(CURRENT_SESSION_CARD_ID)

        else:
            logger.info("Ignoring card scan with value: " + str(value))
            return


    wiegand_reader = pywiegandpi.WiegandDecoder(5, 6, wiegand_callback)

    def ws_on_open(ws: WebSocket) -> None:
        global CURRENT_SESSION_CARD_ID
        logger.info("MemberMatters Connected")
        CURRENT_SESSION_CARD_ID = ""
        mm.ws_on_open(ws)

    def ws_on_close(ws: WebSocket, status_code, msg) -> None:
        global CURRENT_SESSION_CARD_ID
        logger.warning(f"WS Disconnected: {status_code} ({msg or 'no message'})")
        mm.ws_on_close(ws, status_code, msg)
        CURRENT_SESSION_CARD_ID = ""
        time.sleep(5)
        websocket_client.run_forever(dispatcher=rel, reconnect=5)

    def ws_on_error(ws, error) -> None:
        logger.error(f"WS Error: {error}")
        mm.ws_on_error(ws, error)


    def ws_on_message(ws: WebSocket, message: str):
        logger.debug("Got message: " + message)
        mm.ws_on_message(ws, message)


    websocket_client = websocket.WebSocketApp(PORTAL_WS_URL,
                                              on_open=ws_on_open,
                                              on_message=ws_on_message,
                                              on_error=ws_on_error,
                                              on_close=ws_on_close)

    queue_thread.start()
    ws_queue_thread.start()

    # Set dispatcher to automatic reconnection, 5 second reconnect delay if connection closed unexpectedly
    websocket_client.run_forever(dispatcher=rel, reconnect=5)
    rel.signal(2, rel.abort)  # Keyboard Interrupt
    rel.dispatch()
    logger.warning("Exiting main thread")