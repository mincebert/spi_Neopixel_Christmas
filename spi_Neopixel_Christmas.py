# spi_Neopixel_Christmas3.py
# 2023-12-12


from array import array
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


MAX_BARS = 3
BAR_FALLOFF = 2
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



def rgb(r, g, b):
    """Calculate and return 32-bit value for RGB Neopixel colour in
    format 0GRB.
    """

    return (g << 16) | (r << 8) | b



def rgb_at_luma(rgb, luma):
    """Return an RGB value (as returned by rgb()) with the brightness
    scaled to the specified luma value in the range 0-255.
    """

    return ((int((rgb & 0xff0000) * luma // 255) & 0xff0000)
            | (int((rgb & 0xff00) * luma // 255) & 0xff00)
            | (int((rgb & 0xff) * luma // 255) & 0xff))



# --- classes ---



class NeopixelStrip(object):
    """Represents a Neopixel strip.
    """

    def __init__(self, sm, leds=VISIBLE_LEDS, overscan=OVERSCAN_LEDS,
                 brightness=BRIGHTNESS):
        self._sm = sm
        self._leds = leds
        self._brightness = brightness
        self._min = overscan
        self._max = leds + overscan
        self._bars = []
        self._len = leds + overscan * 2
        self._display = array("I", [0 for _ in range(self._len)])

    def __repr__(self):
        print("NeopixelStrip()")

    def reinit(self):
        self._finish = False

    def render(self):
        pass

    def move(self):
        pass

    def set_finish(self):
        self._finish = True

    def is_finished(self):
        return True

    def wait(self):
        pass

    def display(self):
        self._sm.put(self._display[self._min:self._max], 8)

    def cycle(self):
        self.render()
        self.display()
        self.move()
        self.wait()



# bar effect classes



class Bar(object):
    def __init__(self, rgb, width=4, speed=1, pos=0):
        self._rgb = rgb
        self._halfwidth = width // 2
        self._speed = speed
        self._pos = pos

    def move(self):
        self._pos += self._speed

    def color_at(self, p):
        distance = abs(int(self._pos) - p)
        if distance > self._halfwidth:
            return 0    # =BLACK
        intensity = int(((max(self._halfwidth - distance, 0) / self._halfwidth)
                         ** BAR_FALLOFF) * 255)
        return rgb_at_luma(self._rgb, intensity)

    def min(self):
        return self._pos - self._halfwidth



class NeopixelBars(NeopixelStrip):
    """Bars are short lines which whizz along the strip in different
    colours and at different speeds.  When they overlap the colours are
    added together.
    """

    def __init__(self, sm, colors, max_bars=MAX_BARS, **kwargs):
        super().__init__(sm, **kwargs)
        self._colors = colors
        self._max_bars = max_bars
        self.reinit()

    def __repr__(self):
        return ("NeopixelBars(%s)"
                % ", ".join(("0x%06x" % c) for c in self._colors))

    def reinit(self):
        super().reinit()
        self._bars = []

    def is_finished(self):
        return len(self._bars) == 0

    def render(self):
        for led in range(self._min, self._max):
            color = 0
            for bar in self._bars:
                color |= bar.color_at(led - self._min)
            self._display[led] = rgb_at_luma(color, self._brightness)
        return self._display

    def move(self):
        for bar in self._bars:
            bar.move()
        self._bars = [bar for bar in self._bars if bar.min() <= self._max]
        if (not self._finish) and (self.num_bars() < self._max_bars):
            if randint(0, 10) > 8:
                width = randint(8, 16)
                self.add_bar(Bar(choice(self._colors), width=width, speed=choice([0.5, 1, 2]), pos=-width // 2))

    def num_bars(self):
        return len(self._bars)

    def add_bar(self, bar):
        self._bars.append(bar)



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
        return "NeopixelStripes(0x%06x, 0x%06x)" % (self._color1, self._color2)

    def reinit(self):
        super().reinit()
        self._width = self._init_width or randint(6, 16)
        self._wait = self._init_wait or randint(20, 80)
        self._offset = 0
        for led in range(0, self._len):
            self._display[led] = self._next_color()

    def _next_color(self):
        if self._offset < self._width:
            color = rgb_at_luma(self._color1, self._brightness)
        else:
            color = rgb_at_luma(self._color2, self._brightness)
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

BLACK = rgb(0, 0, 0)
BLUE = rgb(0, 0, 255)
WHITE = rgb(255, 255, 255)
RED = rgb(255, 0, 0)
GREEN = rgb(0, 255, 0)
CYAN = rgb(0, 255, 255)
YELLOW = rgb(255, 255, 0)
DARK_GREEN = rgb(0, 63, 0)



# --- main ---



# create the StateMachine with ws2812 program, outputting on Pin(0)
sm = StateMachine(0, ws2812, freq=8000000, sideset_base=Pin(0))
sm.active(1)

BARS_COLORS = [
    [BLUE, WHITE, CYAN],
    [RED, WHITE],
    [RED, GREEN],
    [RED, WHITE, BLUE],
    # [DARK_GREEN, YELLOW],
    # [RED, GREEN, BLUE],
    ]

bars_strips = [
    NeopixelBars(sm, colors=colors, brightness=191) for colors in BARS_COLORS]

STRIPES_COLORS = [
    [WHITE, BLUE],
    [GREEN, RED],
    # [WHITE, BLACK],
    [RED, WHITE],
    [DARK_GREEN, YELLOW]
    ]

stripes_strips = [
    NeopixelStripes(sm, color1=c1, color2=c2, brightness=31) for c1, c2 in STRIPES_COLORS]

displays = bars_strips + stripes_strips

while True:
    led_expired.value(0)
    display = choice(displays)
    print("Displaying:", display)
    display.reinit()
    expire_at = time() + randint(MIN_TIME, MAX_TIME)
    while True:
        remain = expire_at - time()
        if remain < 0:
            if display.is_finished():
                break
            else:
                led_expired.value(1)
                display.set_finish()
        elif remain < 5:
            led_expired.value(not remain % 2)
        led_running.toggle()
        display.cycle()