import logging

MDB_LOG_LEVEL = logging.INFO
MDB_LOG_ACK = False
MM_LOG_LEVEL = logging.INFO
PING_PERIOD = 5
PROCESS_AFFINITY = 3
MIN_CARD_SCAN_VALUE = 100  # ignore all card scans with an ID lower than this amount (useful if you occasionally get noise on your Wiegand line resulting in erronous scans with low values)
WIEGAND_32BIT_MODE = True
API_SECRET = "xyz.xyzabc"
PORTAL_WS_URL = "wss://portal.blah.blah/ws/access/memberbucks/"

