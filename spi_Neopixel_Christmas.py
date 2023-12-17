# spi_Neopixel_Christmas3.py
# 2023-12-12


from array import array
from math import ceil, floor
from utime import sleep_ms
from machine import Pin
from rp2 import PIO, StateMachine, asm_pio
from random import choice, randint, uniform
from time import time



# --- constants ---



# NEOPIXEL STRIP PARAMETERS


# total number of visible LEDs
VISIBLE_LEDS = 288

# number of overscan LEDs when building affects (so things slide onto
# the end nicely)
OVERSCAN_LEDS = 10



# LED INDICATORS


# LED to flash rapidly whilst script is running
led_running = Pin("LED", Pin.OUT)

# LED to flash when current effect is expiring and solid when expired
led_expired = Pin(15, Pin.OUT)


MAX_TRAINS = 3
TRAIN_FALLOFF = 2
BRIGHTNESS = 15
MIN_TIME = 10
MAX_TIME = 20



# --- functions ---



@asm_pio(sideset_init=PIO.OUT_LOW, out_shiftdir=PIO.SHIFT_LEFT, autopull=True,
         pull_thresh=24)

def ws2812():
    """Programmed IO (PIO) function for signalling WS2812 Neopixel strip
    over SPI bus.
    """

    # timings for various steps
    T1 = 2
    T2 = 5
    T3 = 3

    label("bitloop")
    out(x, 1)               .side(0)   [T3 - 1]
    jmp(not_x, "do_zero")   .side(1)   [T1 - 1]
    jmp("bitloop")          .side(1)   [T2 - 1]
    label("do_zero")
    nop()                   .side(0)   [T2 - 1]



def grb(r, g, b):
    """Calculate and return 32-bit value for RGB Neopixel colour in
    format 0GRB.
    """

    return (g << 16) | (r << 8) | b



def grb_to_rgb(grb):
    """Convert a 0GRB format colour into RGB format for printing in a
    more conventional format.
    """

    return ((grb & 0xff00) << 8) | ((grb & 0xff0000) >> 8) | (grb & 0xff)



def color_at_luma(color, luma):
    """Return a colour value (in GRB or RGB format) with the brightness
    scaled to the specified luma value in the range 0-255.
    """

    return ((int((color & 0xff0000) * luma // 255) & 0xff0000)
            | (int((color & 0xff00) * luma // 255) & 0xff00)
            | (int((color & 0xff) * luma // 255) & 0xff))



# --- classes ---



class NeopixelStrip(object):
    """Abstract class for a Neopixel strip.
    """

    def __init__(self, sm, leds=VISIBLE_LEDS, overscan=OVERSCAN_LEDS,
                 brightness=BRIGHTNESS):
        self._sm = sm
        self._leds = leds
        self._brightness = brightness
        self._min = overscan
        self._max = leds + overscan
        self._len = leds + overscan * 2
        self._display = array("I", [0 for _ in range(self._len)])

    def __repr__(self):
        "Method for debugging to print out the strip effect type."
        print("NeopixelStrip()")

    def reinit(self):
        """Reset the effect for a new display.  This method must also
        be called before an effect is used for the first time.
        """
        self._expired = False

    def render(self):
        "Renders the current state of the effect into the display buffer."
        pass

    def move(self):
        "Animate the display by one 'frame'."
        pass

    def set_expired(self):
        """Mark that the effect has expired, which means we want it to
        clear down, ready for the next effect.  This could indicate
        that no new items are to be created on the display, for
        example.
        """
        self._expired = True

    def is_finished(self):
        """Returns if we can move onto the next effect.  Some effects
        may return False here for a few frames to allow something to
        move out of the visible area.
        """
        return True

    def wait(self):
        "Called between frames to add on any required delay."
        pass

    def display(self):
        "Render the current display buffer onto the Neopixel strip."
        self._sm.put(self._display[self._min:self._max], 8)

    def cycle(self):
        """Process a complete frame cycle of the effect: render it,
        display it, move onto the next frame and then wait.
        """
        self.render()
        self.display()
        self.move()
        self.wait()



# TRAINS EFFECT



class Train(object):
    def __init__(self, rgb, width=4, speed=1, pos=0):
        self._rgb = rgb
        self._halfwidth = width // 2
        self._speed = speed
        self._pos = pos

    def __repr__(self):
        return ("Train(0x%06x,%d,%d)"
                    % (grb_to_rgb(self._rgb), self._pos, self._halfwidth))

    def move(self):
        self._pos += self._speed

    def color_at(self, p):
        distance = abs(int(self._pos) - p)
        if distance > self._halfwidth:
            return 0    # =BLACK
        intensity = int(((max(self._halfwidth - distance, 0) / self._halfwidth)
                         ** TRAIN_FALLOFF) * 255)
        return color_at_luma(self._rgb, intensity)

    def min(self):
        return self._pos - self._halfwidth

    def max(self):
        return self._pos + self._halfwidth



class NeopixelTrains(NeopixelStrip):
    """Trains are short lines which whizz along the strip in different
    colours and at different speeds.  When they overlap the colours are
    added together.
    """

    def __init__(self, sm, colors, max_trains=MAX_TRAINS, **kwargs):
        super().__init__(sm, **kwargs)
        self._colors = colors
        self._max_trains = max_trains

    def __repr__(self):
        return ("NeopixelTrains(%s)"
                    % ", ".join(("0x%06x" % grb_to_rgb(c))
                                    for c in self._colors))

    def reinit(self):
        super().reinit()
        self._trains = []

    def is_finished(self):
        return len(self._trains) == 0

    def render(self):
        for led in range(0, self._len):
            self._display[led] = 0

        for train in self._trains:
            for led in range(max(floor(train.min()), 0),
                             min(ceil(train.max()), self._len - 1)):
                self._display[led] |= (
                    color_at_luma(train.color_at(led), self._brightness))

    def move(self):
        for train in self._trains:
            train.move()
        self._trains = [train for train in self._trains
                            if train.min() <= self._max]
        if (not self._expired) and (self.num_trains() < self._max_trains):
            if randint(0, 10) > 8:
                width = randint(8, 16)
                self._trains.append(Train(choice(self._colors), width=width,
                                          speed=choice([0.5, 1, 2]),
                                          pos=-width // 2))

    def num_trains(self):
        return len(self._trains)



# STRIPES EFFECT



class NeopixelStripes(NeopixelStrip):
    """Stripes are alternating patterns of solid colour that move along
    the Neopixel strip.
    """

    def __init__(self, sm, color1, color2, width=None, wait=None, **kwargs):
        super().__init__(sm, **kwargs)
        self._color1 = color1
        self._color2 = color2
        self._init_width = width
        self._init_wait = wait
        self.reinit()

    def __repr__(self):
        return ("NeopixelStripes(0x%06x, 0x%06x)"
                    % (grb_to_rgb(self._color1), grb_to_rgb(self._color2)))

    def reinit(self):
        super().reinit()
        self._width = self._init_width or randint(6, 16)
        self._wait = self._init_wait or randint(20, 80)
        self._offset = 0
        for led in range(0, self._len):
            self._display[led] = self._next_color()

    def _next_color(self):
        if self._offset < self._width:
            color = color_at_luma(self._color1, self._brightness)
        else:
            color = color_at_luma(self._color2, self._brightness)
        self._offset += 1
        if self._offset >= self._width * 2:
            self._offset = 0
        return color

    def move(self):
        self._display[:-1] = self._display[1:]
        self._display[-1] = self._next_color()

    def wait(self):
        sleep_ms(self._wait)



# --- colour constants ---



# named colour values

BLACK = grb(0, 0, 0)
BLUE = grb(0, 0, 255)
WHITE = grb(255, 255, 255)
RED = grb(255, 0, 0)
GREEN = grb(0, 255, 0)
CYAN = grb(0, 255, 255)
YELLOW = grb(255, 255, 0)
DARK_GREEN = grb(0, 63, 0)



# --- main ---



# create the StateMachine with ws2812 program, outputting on Pin(0)
sm = StateMachine(0, ws2812, freq=8000000, sideset_base=Pin(0))
sm.active(1)


TRAINS_COLORS = [
    [BLUE, WHITE, CYAN],
    [RED, WHITE],
    [RED, GREEN],
    [RED, WHITE, BLUE],
    # [DARK_GREEN, YELLOW],
    # [RED, GREEN, BLUE],
    ]

trains_strips = [
    NeopixelTrains(sm, colors=colors, brightness=191)
        for colors in TRAINS_COLORS]


STRIPES_COLORS = [
    [WHITE, BLUE],
    [GREEN, RED],
    # [WHITE, BLACK],
    [RED, WHITE],
    [DARK_GREEN, YELLOW]
    ]

stripes_strips = [
    NeopixelStripes(sm, color1=c1, color2=c2, brightness=31)
        for c1, c2 in STRIPES_COLORS]


# the strip effects we want to use are all of the ones set up
strips = trains_strips + stripes_strips


print("spi_Neopixel_Christmas starting...")

while True:
    led_expired.value(0)
    strip = choice(strips)
    print("Displaying:", strip)
    strip.reinit()
    expire_at = time() + randint(MIN_TIME, MAX_TIME)
    while True:
        remain = expire_at - time()
        if remain < 0:
            if strip.is_finished():
                break
            else:
                led_expired.value(1)
                strip.set_expired()
        elif remain < 5:
            led_expired.value(not remain % 2)
        led_running.toggle()
        strip.cycle()
