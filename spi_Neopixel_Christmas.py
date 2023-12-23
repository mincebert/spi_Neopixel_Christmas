# spi_Neopixel_Christmas.py
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


# overall brightness for display (0-255)
BRIGHTNESS = 15

# effect time range
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



def grb_to_hex(grb):
    """Convert a 0GRB format colour into a text string giving the colour in
    RGB hex format for printing.
    """

    return ("0x%06x"
                % (((grb & 0xff00) << 8)
                   | ((grb & 0xff0000) >> 8)
                   | (grb & 0xff)))



def grb_list(grbs):
    """Converts a list of colours in 0GRB format into a comma-separated
    list for printing.
    """

    return '[' + ", ".join(grb_to_hex(c) for c in grbs) + ']'



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

    def clear(self, color=0):
        "Clear the display buffer to a particular color, default black."

        for pos in range(self._min, self._max + 1):
            self._display[pos] = color

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



class NeopixelPoint(object):
    """Abstract class for representing a point with a colour along a
    Neopixel strip.
    """


    def __init__(self, pos, color):
        super().__init__()
        self.pos = pos
        self.color = color



# TRAINS EFFECT



MAX_TRAINS = 4
TRAIN_FALLOFF = 2
NEW_TRAIN_PROBABILITY_PCT = 80
TRAIN_WIDTH_MIN = 8
TRAIN_WIDTH_MAX = 24



class Train(object):
    def __init__(self, rgb, width=4, speed=1, pos=0):
        self._rgb = rgb
        self._halfwidth = width // 2
        self._speed = speed
        self._pos = pos

    def __repr__(self):
        return ("Train(color=%s, pos=%d, halfwidth=%d)"
                    % (grb_to_hex(self._rgb), self._pos, self._halfwidth))

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
        return f"NeopixelTrains(colors={grb_list(self._colors)})"

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
        # move the trains
        for train in self._trains:
            train.move()

        # if a train has reached the end, remove it
        self._trains = [train for train in self._trains
                            if train.min() <= self._max]

        # if we have fewer than the maximum number of trains and not expired...
        if (not self._expired) and (self.num_trains() < self._max_trains):
            # ... there's a 2 in 11 chance we create a new train
            if randint(1, 100) <= NEW_TRAIN_PROBABILITY_PCT:
                width = randint(TRAIN_WIDTH_MIN, TRAIN_WIDTH_MAX)
                self._trains.append(Train(choice(self._colors), width=width,
                                          speed=choice([0.5, 1, 2]),
                                          pos=-width // 2))

    def num_trains(self):
        return len(self._trains)



# STRIPES EFFECT



STRIPES_WIDTH_MIN = 6
STRIPES_WIDTH_MAX = 16
STRIPES_WAIT_MIN = 20
STRIPES_WAIT_MAX = 80



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

    def __repr__(self):
        return ("NeopixelStripes(%s, %s)"
                    % (grb_to_hex(self._color1), grb_to_hex(self._color2)))

    def reinit(self):
        super().reinit()
        self._width = (
            self._init_width or randint(STRIPES_WIDTH_MIN, STRIPES_WIDTH_MAX))
        self._wait = (
            self._init_wait or randint(STRIPES_WAIT_MIN, STRIPES_WAIT_MAX))
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



# RAIN EFFECT



NEW_RAIN_DROP_PCT = 15
RAIN_MAX_DROPS = 8
RAIN_MAX_SIZE = 12



class RainDrop(NeopixelPoint):
    "Class for representing a coloured raindrop splashing."


    def __init__(self, pos, color, max_size):
        super().__init__(pos, color)
        self.max_size = max_size

        self.current_size = 0
        self.target_size = self.max_size


    def __repr__(self):
        return (
            "RainDrop(%d, %s, %d, %d)"
                % (self.pos, grb_to_hex(self.color), self.target_size,
                   self.current_size))


    def move(self):
        # if we're smaller than target size, get bigger
        if self.current_size < self.target_size:
            self.current_size += 1

            # if we're reached the largest size, the new target is 0
            if self.current_size >= self.target_size:
                self.target_size = 0

        # the target is smaller - do that if we're bigger than 0
        elif self.current_size > 0:
            self.current_size -= 1


    def finished(self):
        # this drop is finished is we're shrinking and have reached 0
        return (self.current_size == 0) and (self.target_size == 0)


    def color_at_offset(self, offset):
        intensity = int(((max(self.current_size - offset, 0) / self.max_size)
                    ** TRAIN_FALLOFF) * 255)
        return color_at_luma(self.color, intensity)


class NeopixelRain(NeopixelStrip):
    """Rain is expanding and contracting bars of water meant to mimic
    rain falling into a puddle.
    """

    def __init__(self, sm, colors, *args, **kwargs):
        super().__init__(sm, *args, **kwargs)
        self._colors = colors

    def __repr__(self):
        return f"NeopixelRain({grb_list(self._colors)})"

    def reinit(self):
        super().reinit()
        self._drops = []

    def move(self):
        # animate the drops we have
        for drop in self._drops:
            drop.move()

        # remove any drops that have finished
        self._drops = [ d for d in self._drops if not d.finished() ]

        # if we have fewer than max drops, add one if not expired
        if ((not self._expired)
            and (len(self._drops) < RAIN_MAX_DROPS)
            and (randint(1, 100) < NEW_RAIN_DROP_PCT)):

            self._drops.append(RainDrop(
                pos=randint(self._min, self._max),
                color=choice(self._colors),
                max_size=randint(5, RAIN_MAX_SIZE)))

    def render(self):
        for led in range(0, self._len):
            self._display[led] = 0

        for drop in self._drops:
            for offset in range(0, drop.current_size - 1):
                color = drop.color_at_offset(offset)
                if (drop.pos - offset) >= self._min:
                    self._display[drop.pos - offset] |= color
                if (drop.pos + offset) <= self._max:
                    self._display[drop.pos + offset] |= color


    def is_finished(self):
        return not self._drops


    def wait(self):
        sleep_ms(20)



# STARS EFFECT



STAR_MIN_LUMA = 0
STAR_MAX_LUMA = 191
STAR_LUMA_DELTA = 16
STARS_MIN = 10
STARS_MAX = 25



class Star(NeopixelPoint):
    "Class for a single twinkling star."

    def __init__(self, pos, color):
        super().__init__(pos, color)

        # always start getting brighter
        self.luma_delta = STAR_LUMA_DELTA

        # current luma is random between minimum and maximum so each
        # star is at a different brightness
        self.luma = randint(STAR_MIN_LUMA, STAR_MAX_LUMA - 1)


    def __repr__(self):
        return (f"Star(pos={self.pos}, color={grb_to_hex(self.color)}, luma={self.luma}, "
                + f"luma_delta={self.luma_delta})")


    def pos_and_color(self):
        return self.pos, color_at_luma(self.color, self.luma)


    def twinkle(self):
        # stars bounce between minimum and maximum luma by luma_delta
        # each frame
        self.luma = max(min(self.luma + self.luma_delta, STAR_MAX_LUMA), STAR_MIN_LUMA)
        if ((self.luma <= STAR_MIN_LUMA)
            or (self.luma >= STAR_MAX_LUMA)):
            self.luma_delta = -self.luma_delta


class NeopixelStars(NeopixelStrip):
    "Effect class for twinkling random points along the strip."


    def __init__(self, sm, colors, **kwargs):
        super().__init__(sm, **kwargs)
        self._colors = colors
        self._num_stars = randint(STARS_MIN, STARS_MAX)


    def __repr__(self):
        return (f"NeopixelStars(colors={grb_list(self._colors)}, "
                + f"num_stars={self._num_stars})")


    def reinit(self):
        self._stars = []
        for _ in range(0, self._num_stars):
            self._stars.append(Star(pos=randint(self._min, self._max),
                                    color=choice(self._colors)))

    def render(self):
        self.clear()
        for star in self._stars:
            pos, color = star.pos_and_color()
            self._display[pos] = color


    def move(self):
        for star in self._stars:
            star.twinkle()


    def wait(self):
        sleep_ms(50)




# --- colour constants ---



# named colour values

BLACK = grb(0, 0, 0)
BLUE = grb(0, 0, 255)
WHITE = grb(255, 255, 255)
RED = grb(255, 0, 0)
GREEN = grb(0, 255, 0)
CYAN = grb(0, 255, 255)
YELLOW = grb(255, 255, 0)
MAGENTA = grb(255, 0, 255)
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
]

trains_effects = [
    NeopixelTrains(sm, colors=colors, brightness=191)
        for colors in TRAINS_COLORS]


STRIPES_COLORS = [
    [WHITE, BLUE],
    [GREEN, RED],
    [RED, WHITE],
    [DARK_GREEN, YELLOW],
]

stripes_effects = [
    NeopixelStripes(sm, color1=c1, color2=c2, brightness=31)
        for c1, c2 in STRIPES_COLORS]


RAIN_COLORS = [
    [CYAN],
    [BLUE, CYAN],
    [WHITE, CYAN],
    [RED, YELLOW, DARK_GREEN, BLUE, CYAN, MAGENTA],
]

rain_effects = [
    NeopixelRain(sm, brightness=191, colors=c) for c in RAIN_COLORS]


STARS_COLORS = [
    [CYAN, WHITE],
    [BLUE, CYAN, WHITE],
    [YELLOW, WHITE],
]

stars_effects = [
    NeopixelStars(sm, brightness=191, colors=c) for c in STARS_COLORS]


# the strip effects we want to use are all of the ones set up
effects = trains_effects + stripes_effects + rain_effects


print("spi_Neopixel_Christmas starting...")

while True:
    led_expired.value(0)
    effect = choice(effects)
    print("Displaying effect:", effect)
    effect.reinit()
    effect_time = randint(MIN_TIME, MAX_TIME)
    print("Running for %ds." % effect_time)
    expire_at = time() + effect_time

    last_remain = None
    while True:
        remain = expire_at - time()

        if remain < 0:
            # this effect has expired - has it also finished
            if effect.is_finished():
                break
            else:
                led_expired.value(1)
                effect.set_expired()

        elif remain < 5:
            if (last_remain is None) or (remain < last_remain):
                # less than 5s remaining - flash the LED
                print("Expiring in %ds." % remain)
                led_expired.value(not remain % 2)
                last_remain = remain

        led_running.toggle()

        effect.cycle()
