import pigpio


class Decoder:
    def __init__(self, pi, gpio_0, gpio_1, callback, bit_timeout=5, wiegand_32bit_mode=False, raw_mode=False):
        """
        The callback is passed the code length in bits and the card uid/value.
        """

        self.pi = pi
        self.gpio_0 = gpio_0
        self.gpio_1 = gpio_1
        self.raw_mode = raw_mode
        self.wiegand_32bit_mode = wiegand_32bit_mode

        self.callback = callback
        self.bit_timeout = bit_timeout
        self.receiving_bits = False

        self.pi.set_mode(gpio_0, pigpio.INPUT)
        self.pi.set_mode(gpio_1, pigpio.INPUT)
        self.pi.set_pull_up_down(gpio_0, pigpio.PUD_UP)
        self.pi.set_pull_up_down(gpio_1, pigpio.PUD_UP)

        self.cb_0 = self.pi.callback(gpio_0, pigpio.FALLING_EDGE, self._cb)
        self.cb_1 = self.pi.callback(gpio_1, pigpio.FALLING_EDGE, self._cb)

    def _cb(self, gpio, level, tick):
        """
        Accumulate bits until both gpios 0 and 1 timeout.
        """

        if level < pigpio.TIMEOUT:
            if not self.receiving_bits:
                self.bits = 1
                self.num = 0

                self.receiving_bits = True
                self.receiving_bits_timeout = 0
                self.pi.set_watchdog(self.gpio_0, self.bit_timeout)
                self.pi.set_watchdog(self.gpio_1, self.bit_timeout)
            else:
                self.bits += 1
                self.num = self.num << 1

            if gpio == self.gpio_0:
                self.receiving_bits_timeout = self.receiving_bits_timeout & 2  # clear gpio 0 timeout
            else:
                self.receiving_bits_timeout = self.receiving_bits_timeout & 1  # clear gpio 1 timeout
                self.num = self.num | 1

        else:
            if self.receiving_bits:
                if gpio == self.gpio_0:
                    self.receiving_bits_timeout = self.receiving_bits_timeout | 1  # timeout gpio 0
                else:
                    self.receiving_bits_timeout = self.receiving_bits_timeout | 2  # timeout gpio 1

                if self.receiving_bits_timeout == 3:  # both gpios timed out
                    self.pi.set_watchdog(self.gpio_0, 0)
                    self.pi.set_watchdog(self.gpio_1, 0)
                    self.receiving_bits = False

                    if self.raw_mode:
                        self.callback(self.bits, self.num)
                    else:
                        # get only the bits we're interested in
                        card_mask_26bit = 0b0_00000000_11111111_11111111_11111111_0
                        card_mask_34bit = 0b0_11111111_11111111_11111111_11111111_0
                        card_mask = card_mask_34bit if self.wiegand_32bit_mode else card_mask_26bit
                        card_uid = self.num & card_mask >> 1  # strip off the remaining parity bit
                        self.callback(self.bits, card_uid)

    def cancel(self):
        """
        Cancel the Wiegand decoder.
        """

        self.cb_0.cancel()
        self.cb_1.cancel()
