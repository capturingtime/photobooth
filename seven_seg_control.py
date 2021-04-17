# Built for use with a Common Cathode (CC) 7 Segment Display
# http://ee.hawaii.edu/~sasaki/EE361/Fall06/Lab/7disp.html#:~:text=The%20difference%20between%20the%20two,anode%20segments%20are%20connected%20together.

import RPi.GPIO as GPIO

"""
7-Segment display
 _
|_|
|_|.

"""
# Set which GPIO pin number is connected to which segment
# Comments denote the connection mapping for an NTE3079 Single Digit CC 7 Segment Display
# GPIO  # Anode / Pin
gpio_pins = {
    "top": 6,  # A / 7
    "t_left": 12,  # F / 9
    "t_right": 13,  # B / 6
    "center": 19,  # G / 10
    "b_left": 16,  # E / 1
    "b_right": 26,  # C / 4
    "bot": 20,  # D / 2
    "d_point": 21  # D.P. / 5
}


def init_gpio():
    """ Initializes the GPIO pins according to the dict mapping in gpio_pins
    """
    mode = GPIO.BCM
    GPIO.setmode(mode)

    for seg, pin in gpio_pins.items():
        GPIO.setup(pin, GPIO.OUT)  # Set this pin to be an output when on (True)
        GPIO.output(pin, False)  # Set the pin to off (False)

    # Set the Display to the number 0
    set_digit(digit=0)


def set_digit(digit: int = 0) -> bool:
    """ Sets the digit of the 7seg
    """

    if not isinstance(digit, int):
        print(f'digit is not type: int for set_digit(). Received: {digit} ({type(digit)})')
        return None

    # (top, t_left, t_right, center, b_left, b_right, bot, d_point)
    digit_map = {
        0: (True, True, True, False, True, True, True, False),
        1: (False, False, True, False, False, True, False, False),
        2: (True, False, True, True, True, True, False, True, False),
        3: (True, False, True, True, False, True, True, False),
        4: (False, True, True, True, False, True, False, False),
        5: (True, True, False, True, False, True, True, False),
        6: (True, True, False, True, True, True, True, True),
        7: (True, False, True, False, False, True, False, False),
        8: (True, True, True, True, True, True, True, False),
        9: (True, True, True, True, False, True, True, True)
    }

    for seg, pin in gpio_pins.items():
        for state in digit_map[digit]:
            GPIO.output(pin, state)

            cur_state = GPIO.input(pin)
            if state is not cur_state:
                print(f'Failed to set pin {pin} ({seg}) state. Attempted: {state} Current: {cur_state}')  # noqa: E501
                return False
    print(f'7 Segment display set to digit: {digit}')
    return True
