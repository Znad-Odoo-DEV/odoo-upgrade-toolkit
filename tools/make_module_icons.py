"""The application icons, drawn rather than downloaded.

    python tools/make_module_icons.py

Runs on plain Python with Pillow. No Odoo, no database.

Odoo shows static/description/icon.png on the Apps screen, and a module
without one gets a grey placeholder that says the module was assembled rather
than made. Ours are drawn here, in code, for two reasons: they can be redrawn
identically when a colour or a glyph changes, and a binary nobody can
regenerate is a file that rots in the repository.

The design is deliberately plain - a rounded square, one colour per family,
and a mark that says what the module is for. It has to read at 64 pixels on
the Apps screen, which is where these are actually looked at, so there are no
gradients, no thin strokes and no more than two shapes.

Colours are Odoo's own family hues so the applications sit beside the standard
ones without shouting: purple for the request desk, teal for the projects and
planning side.
"""
import os

from PIL import Image, ImageDraw, ImageFont

SIZE = 256
HERE = os.path.dirname(os.path.dirname(os.path.abspath(
    __file__ if '__file__' in dir() else '.')))

# module -> (background, accent, the mark)
ICONS = {
    'ssc_requests': ((113, 75, 103), (255, 255, 255), 'clipboard'),
    'ssc_progress_planning': ((0, 122, 118), (255, 255, 255), 'chart'),
    'ssc_subcontract': ((32, 79, 122), (255, 255, 255), 'handshake'),
}


def rounded(colour):
    image = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=56,
                           fill=colour + (255,))
    return image, draw


def clipboard(draw, accent):
    """A request is a sheet somebody signs, so: a clipboard with lines."""
    draw.rounded_rectangle([64, 62, 192, 206], radius=12, fill=accent + (255,))
    draw.rounded_rectangle([100, 44, 156, 76], radius=10, fill=accent + (255,))
    draw.rounded_rectangle([100, 50, 156, 70], radius=8, fill=(90, 60, 82, 255))
    for index, y in enumerate((104, 132, 160)):
        width = 96 if index < 2 else 60
        draw.rounded_rectangle([84, y, 84 + width, y + 12], radius=6,
                               fill=(113, 75, 103, 255))


def chart(draw, accent):
    """Progress is bars that grow, standing on an axis.

    The first attempt drew a line across the top of them, and it cut through
    the tallest bar - which at 64 pixels looks like a mistake rather than a
    chart. An axis underneath reads as one thing.
    """
    for x, height in ((72, 60), (114, 100), (156, 140)):
        draw.rounded_rectangle([x, 196 - height, x + 30, 196], radius=8,
                               fill=accent + (255,))
    draw.rounded_rectangle([64, 202, 194, 210], radius=4, fill=accent + (255,))


def handshake(draw, accent):
    """A subcontract is two parties meeting: two interlocking rings."""
    draw.ellipse([54, 84, 154, 184], outline=accent + (255,), width=20)
    draw.ellipse([102, 84, 202, 184], outline=accent + (255,), width=20)


MARKS = {'clipboard': clipboard, 'chart': chart, 'handshake': handshake}


def write_icon(module, background, accent, mark):
    folder = os.path.join(HERE, 'addons', module, 'static', 'description')
    if not os.path.isdir(os.path.join(HERE, 'addons', module)):
        return "no such module"
    os.makedirs(folder, exist_ok=True)
    image, draw = rounded(background)
    MARKS[mark](draw, accent)
    path = os.path.join(folder, 'icon.png')
    image.save(path, 'PNG')
    return path


if __name__ == '__main__':
    for module, (background, accent, mark) in ICONS.items():
        print("%-26s %s" % (module, write_icon(module, background, accent, mark)))
