# spi_Neopixel_Christmas2.py
# 2022-12-19

from array import array
from utime import sleep_ms
from machine import Pin
from rp2 import PIO, StateMachine, asm_pio
from random import choice, randint, uniform
from time import time

led_onboard = Pin("LED", Pin.OUT)	# onboard LED flashes whilst cycling
led_expired = Pin(15, Pin.OUT)		# flashes when sequence has expired

# Configure the number of WS2812 LEDs
LEDS = 288		# number of LEDs in strip (reduce to save power)
OVERSCAN = 10
MAX_BARS = 3
WIDTH = 8
FALLOFF = 2
BRIGHTNESS = 15
MIN_TIME = 10
MAX_TIME = 20

@asm_pio(sideset_init=PIO.OUT_LOW, out_shiftdir=PIO.SHIFT_LEFT, autopull=True, pull_thresh=24)
def ws2812():
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
    return (g << 16) | (r << 8) | b

def rgb_at_luma(rgb, luma):
    return ((int((rgb & 0xff0000) * luma // 255) & 0xff0000)
            | (int((rgb & 0xff00) * luma // 255) & 0xff00)
            | (int((rgb & 0xff) * luma // 255) & 0xff))

class RGB(object):
    def __init__(self, r, g, b):
        self._r, self._g, self._b = int(r), int(g), int(b)
        
    def __int__(self):
        return (self._g << 16) | (self._r << 8) | self._b

    def __repr__(self):
        return "<R%02X/G%02X/B%02X>" % (self._r, self._g, self._b)

    def __or__(self, value):
        return RGB(self._r or value._r, self._g or value._g, self._b or value._b)

    def at_luma(self, l):
        return RGB(self._r * l // 255, self._g * l // 255, self._b * l // 255)

BLACK = rgb(0, 0, 0)
BLUE = rgb(0, 0, 255)
WHITE = rgb(255, 255, 255)
RED = rgb(255, 0, 0)
GREEN = rgb(0, 255, 0)
CYAN = rgb(0, 255, 255)
YELLOW = rgb(255, 255, 0)
DARK_GREEN = rgb(0, 63, 0)

class Bar(object):
    def __init__(self, rgb=WHITE, width=4, speed=1, pos=0):
        self._rgb = rgb
        self._halfwidth = width // 2
        self._speed = speed
        self._pos = pos

    def move(self):
        self._pos += self._speed

    def color_at(self, p):
        distance = abs(int(self._pos) - p)
        if distance > self._halfwidth:
            return BLACK
        intensity = int(((max(self._halfwidth - distance, 0) / self._halfwidth) ** FALLOFF) * 255)
        #intensity = max(self._halfwidth - distance, 0) * 255 // self._halfwidth
        return rgb_at_luma(self._rgb, intensity) # .at_luma(intensity)
    
    def min(self):
        return self._pos - self._halfwidth

class Display(object):
    def __init__(self, sm, leds=LEDS, overscan=OVERSCAN, brightness=BRIGHTNESS):
        self._sm = sm
        self._leds = leds
        self._brightness = brightness
        self._min = overscan
        self._max = leds + overscan
        self._bars = []
        self._len = leds + overscan * 2
        self._display = array("I", [0 for _ in range(self._len)])

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

class BarsDisplay(Display):
    """Bars are short lines which whizz along the strip in different
    colours and at different speeds.  When they overlap the colours are
    added together.
    """

    def __init__(self, sm, colors=[[WHITE, BLACK]], max_bars=MAX_BARS, **kwargs):
        super().__init__(sm, **kwargs)
        self._colors = colors
        self._max_bars = max_bars
        self.reinit()

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

class StripesDisplay(Display):
    """Stripes are alternating patterns of solid colour that slide
    along.
    """

    def __init__(self, sm, color1=RED, color2=WHITE, width=None, wait=None, **kwargs):
        super().__init__(sm, **kwargs)
        self._color1 = color1
        self._color2 = color2
        self._init_width = width
        self._init_wait = wait
        self.reinit()
        
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

# Create the StateMachien with ws2812 program, outputting on Pin(0).
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
bars_displays = [
    BarsDisplay(sm, colors=colors, brightness=191) for colors in BARS_COLORS]

STRIPES_COLORS = [
    [WHITE, BLUE],
    [GREEN, RED],
    # [WHITE, BLACK],
    [RED, WHITE],
    [DARK_GREEN, YELLOW]
    ]
stripes_displays = [
    StripesDisplay(sm, color1=c1, color2=c2, brightness=31) for c1, c2 in STRIPES_COLORS]

displays = bars_displays + stripes_displays
#displays = displays[-1:]

while True:
    led_expired.value(0)
    display = choice(displays)
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
        led_onboard.toggle()
        display.cycle()
