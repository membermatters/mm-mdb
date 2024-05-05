import json
import config
import logging
import time
import threading
from queue import Queue
from websocket import WebSocketApp, WebSocket

# This is meant to be a more generic implementation of the MM websocket protocol that will hopefully one day be used
# across both the mm-mdb code and the beepbeep-mainboard firmware code.

logger = logging.getLogger("mm")
logger.setLevel(config.LOG_LEVEL)


def build_packet(command: str, data=None) -> str:
    if data is None:
        data = {}
    command_object = {
        "command": command,
        **data
    }
    command_packet = json.dumps(command_object)
    # logger.debug(f"Built command:\n{command_packet}")
    return command_packet


def get_command_object(command: str, data: object = None):
    return {
        "command": command,
        "data": data
    }


class MM:
    def __init__(self, websocket_secret: str, ip_address: str, command_queue: Queue):
        logger.debug("Initializing MM module")
        self.ws: WebSocketApp or None = None
        self.api_secret = websocket_secret
        self.ip_address = ip_address
        self.command_queue = command_queue
        self.last_pong = 0
        self.device_locked_out = False
        self._thread_for_ping = None

    def ws_on_open(self, ws: WebSocket) -> None:
        logger.info("WS Connected")
        self.ws = ws
        self.last_pong = time.time()
        self.send_authentication()

        # create a new ping thread and start it
        self._thread_for_ping = PingThread(self)
        self._thread_for_ping.start()

    def ws_on_close(self, ws: WebSocket) -> None:
        logger.info("WS Disconnected")
        self.ws = None
        if not self._thread_for_ping.stopped():
            self._thread_for_ping.stop()
            self._thread_for_ping.join()
            logger.debug("Ping thread stopped.")

    def ws_on_error(self, ws: WebSocket, error: Exception) -> None:
        logger.error(f"WS Error: {error}")

    def ws_on_message(self, ws: WebSocket, message: str) -> None:
        try:
            command_object = json.loads(message)

            if command_object.get("authorised") is not None:
                logger.info("Got authorisation packet.")
                self.send_ip()

            elif command_object.get("command") == "pong":
                logger.debug("Got pong packet.")
                self.last_pong = time.time()

            elif command_object.get("command") == "ping":
                logger.debug("Got ping packet.")
                self.send_pong()

            elif command_object.get("command") == "reboot":
                logger.warning("Rebooting device!")
                import os
                os.system('sudo shutdown -r now')

            elif command_object.get("command") == "update_device_locked_out":
                locked_out = command_object.get("locked_out")
                logger.info(f"Updating device locked out to {locked_out}!")
                self.device_locked_out = locked_out

            elif command_object.get("command") == "bump":
                # we can safely ignore this command if we're not a door
                logger.debug("Received bump request but not a door!")

            elif command_object.get("command") == "sync":
                # we can safely ignore this command if we're not a door
                logger.debug("Received sync request but not a door!")

            elif command_object.get("command") == "unlock":
                # we can safely ignore this command if we're not a door
                logger.debug("Received unlock request but not a door!")

            elif command_object.get("command") == "lock":
                # we can safely ignore this command if we're not a door
                logger.debug("Received lock request but not a door!")

            elif command_object.get("command") == "interlock_session_start":
                # we can safely ignore this command if we're not an interlock
                logger.debug("Received interlock session_start request but not an interlock!")

            elif command_object.get("command") == "interlock_session_rejected":
                # we can safely ignore this command if we're not an interlock
                logger.debug("Received interlock session_rejected request but not an interlock!")

            elif command_object.get("command") == "interlock_session_update":
                # we can safely ignore this command if we're not an interlock
                logger.debug("Received interlock session_update request but not an interlock!")

            elif command_object.get("command") == "debit":
                success = command_object.get("success")
                balance = command_object.get("balance")

                success_string = "successful" if success else "unsuccessful"
                balance_string = (
                    f"${str(round(float(balance) / 100, 2))}"
                    if balance
                    else "Unknown"
                )
                logger.info(f"Debit was {success_string}, balance remaining is {balance_string}.")

                data = {
                    "success": success,
                    "balance": balance,
                }
                self.command_queue.put(get_command_object("DEBIT_RESULT", data))
            else:
                logger.warning("Unknown websocket packet!")
                logger.warning(command_object)

        except Exception as e:
            logger.error("Error parsing JSON websocket packet: " + message)
            logger.error(str(e))

    def send_authentication(self):
        logger.info("Sending authentication packet")
        auth_packet = build_packet("authenticate", {"secret_key": self.api_secret})
        self.ws.send(auth_packet)

    def send_ip(self):
        logger.info("Sending IP packet")
        ip_packet = build_packet("ip_address", {"ip_address": self.ip_address})
        self.ws.send(ip_packet)

    def send_ping(self):
        logger.debug("Sending ping packet")
        self.ws.send(build_packet("ping"))

    def send_pong(self):
        logger.debug("Sending pong packet")
        self.ws.send(build_packet("pong"))

    def send_debit_request(self, amount: int, card_id: str, item_number: str):
        logger.info(f"Sending debit request for {amount} cents.")
        debit_object = {
            "card_id": card_id,
            "amount": amount/100,  # the API expects dollars, not cents
            "item_number": item_number
        }
        debit_packet = build_packet("debit", debit_object)
        self.ws.send(debit_packet)


class PingThread(threading.Thread):
    def __init__(self, mm: MM):
        super().__init__()
        self._stop_event = threading.Event()
        self.mm = mm

        logging.basicConfig(level=config.LOG_LEVEL)
        self.logger = logging.getLogger("mm:ping_thread")

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    def run(self):
        while not self._stop_event.wait(config.PING_PERIOD):
            if self.mm.last_pong < time.time() - config.PING_PERIOD * 3:
                self.logger.warning("Ping thread detected websocket connection failure!")
                self.mm.ws.close()
                self.stop()
            else:
                self.mm.send_ping()
