import json
import config
import logging
import time
import threading
from queue import Queue
from websocket import WebSocketApp, WebSocket, WebSocketConnectionClosedException
import pymultidropbus.protocol

# This is meant to be a more generic implementation of the MM websocket protocol that will hopefully one day be used
# across both the mm-mdb code and the beepbeep-mainboard firmware code.

logging.basicConfig()
logger = logging.getLogger("mm")
logger.setLevel(config.MM_LOG_LEVEL)


def build_packet(command: str, data=None) -> str:
    if data is None:
        data = {}
    command_object = {
        "command": command,
        **data
    }
    command_packet = json.dumps(command_object)
    logger.debug(f"Built command:\n{command_packet}")
    return command_packet


def get_command_object(command: str, data: object = None):
    return {
        "command": command,
        "data": data
    }


class MM:
    def __init__(self, websocket_secret: str, ip_address: str, ws_command_queue: Queue, mdb_command_queue: Queue):
        logger.debug("Initializing MM module")
        self.ws: WebSocket = None
        self.api_secret = websocket_secret
        self.ip_address = ip_address
        self.ws_command_queue = ws_command_queue
        self.mdb_command_queue = mdb_command_queue
        self.last_pong = 0
        self.device_locked_out = False

    def _ws_send(self, message: str):
        if self.ws:
            self.ws.send(message)
        else:
            logger.warning(f"Tried to send message but no websocket connection! {message}")

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

            elif command_object.get("command") == "balance":
                logger.debug("Received balance: " + json.dumps(command_object))
                success = command_object.get("success", True)
                balance = command_object.get("balance")

                success_string = "successful" if success else "unsuccessful"
                balance_string = (
                    f"${str(balance/100)}"
                    if balance
                    else "Unknown"
                )
                logger.info(f"Balance request was {success_string}, balance is {balance_string}.")

                data = {
                    "success": success,
                    "balance": balance,
                }
                self.ws_command_queue.put(get_command_object("BALANCE_RESULT", data))

            elif command_object.get("command") == "debit":
                logger.debug("Received debit request: " + json.dumps(command_object))
                success = command_object.get("success")
                balance = command_object.get("balance")

                success_string = "successful" if success else "unsuccessful"
                balance_string = (
                    f"${str(balance/100)}"
                    if balance
                    else "Unknown"
                )
                logger.info(f"Debit was {success_string}, balance remaining is {balance_string}.")

                data = {
                    "success": success,
                    "balance": balance,
                }
                self.ws_command_queue.put(get_command_object("DEBIT_RESULT", data))
            else:
                logger.warning("Unknown websocket packet!")
                logger.warning(command_object)

        except Exception as e:
            logger.error("Error parsing JSON websocket packet: " + message)
            logger.error(str(e))

    def send_authentication(self):
        logger.debug("Sending authentication packet")
        auth_packet = build_packet("authenticate", {"secret_key": self.api_secret})
        self._ws_send(auth_packet)

    def send_ip(self):
        logger.debug("Sending IP packet")
        ip_packet = build_packet("ip_address", {"ip_address": self.ip_address})
        self._ws_send(ip_packet)

    def send_ping(self):
        logger.debug("Sending ping packet")
        self._ws_send(build_packet("ping"))

    def send_pong(self):
        logger.debug("Sending pong packet")
        self._ws_send(build_packet("pong"))

    def send_debit_request(self, amount: pymultidropbus.protocol.Money, card_id: str, item_number: int = None):
        logger.info(f"Sending debit request for {amount} cents.")
        debit_object = {
            "card_id": card_id,
            "amount": amount.dollars,  # api expects dollars
        }
        if item_number:
            debit_object["product_external_id"] = item_number
        debit_packet = build_packet("debit", debit_object)
        self._ws_send(debit_packet)

    def send_balance_request(self, card_id: str):
        logger.info(f"Sending balance request for card_id: {card_id}.")
        command_object = {
            "card_id": card_id,
        }
        debit_packet = build_packet("balance", command_object)
        self._ws_send(debit_packet)
