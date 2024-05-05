import netifaces
import rel
import websocket
from websocket import WebSocket, WebSocketException
import mm
import config
import logging

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


if __name__ == "__main__":
    mm = mm.MM(config.API_SECRET, ip_address)
    websocket_client = websocket.WebSocketApp(PORTAL_WS_URL,
                                              on_open=mm.ws_on_open,
                                              on_message=mm.ws_on_message,
                                              on_error=mm.ws_on_error,
                                              on_close=mm.ws_on_close)

    # Set dispatcher to automatic reconnection, 5 second reconnect delay if connection closed unexpectedly
    websocket_client.run_forever(dispatcher=rel, reconnect=5)
    rel.signal(2, rel.abort)  # Keyboard Interrupt
    rel.dispatch()
