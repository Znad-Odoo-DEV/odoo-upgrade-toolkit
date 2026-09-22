"""One icon per kind of request, drawn rather than downloaded.

    python tools/make_request_type_icons.py

Runs on plain Python with Pillow. No Odoo, no database.

The Studio dashboard has a picture on every card, and it is the thing people
aim at: nobody reads thirteen titles to find the leave request, they look for
the aeroplane. Ours had none, so the cards were a wall of text.

Drawn in code for the same reason as the module icons - they can be redrawn
identically when a colour changes, and a binary nobody can regenerate rots in
the repository.

The rules that make them readable at 64 pixels, which is the size they are
actually looked at:

  two or three shapes, never more
  strokes of six pixels or thicker
  one colour per family - site work slate, money green, people blue,
    paperwork amber - so a glance sorts the board before any word is read
  no text in the drawing, because 8pt type inside a 64px square is a smudge
"""
import os

from PIL import Image, ImageDraw

SIZE = 128
PAD = 14

SLATE = (55, 71, 90)        # site and materials
GREEN = (26, 127, 92)       # money
BLUE = (37, 99, 165)        # people and leave
AMBER = (176, 122, 26)      # paperwork and certificates

HERE = os.path.dirname(os.path.dirname(os.path.abspath(
    __file__ if '__file__' in dir() else '.')))
OUT = os.path.join(HERE, 'addons', 'ssc_requests', 'static', 'src', 'img')


def canvas():
    image = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def box(draw, colour):
    """A carton: material."""
    draw.rectangle([PAD, 44, SIZE - PAD, SIZE - PAD], outline=colour, width=7)
    draw.polygon([(PAD, 44), (30, 22), (SIZE - 30, 22), (SIZE - PAD, 44)],
                 outline=colour, width=7)
    draw.line([(64, 44), (64, SIZE - PAD)], fill=colour, width=7)


def sheet(draw, colour, folded=True):
    """A sheet of paper, the base of every paperwork glyph."""
    draw.rounded_rectangle([26, 16, SIZE - 26, SIZE - 16], radius=6,
                           outline=colour, width=7)
    if folded:
        for y in (44, 62, 80):
            draw.line([(42, y), (SIZE - 42, y)], fill=colour, width=6)


def money(draw, colour):
    """A banknote with a coin: an advance."""
    draw.rounded_rectangle([12, 34, 100, 86], radius=6, outline=colour, width=7)
    draw.ellipse([44, 46, 68, 70], outline=colour, width=6)
    draw.ellipse([76, 62, 118, 104], outline=colour, width=7)
    draw.line([(97, 72), (97, 94)], fill=colour, width=6)


def plane(draw, colour):
    """An aeroplane seen from above: annual leave.

    Redrawn. The first attempt was a side view built from two slanted
    polygons and it read as a torn paper dart - which matters more here than
    anywhere else on the board, because the leave request is the one people
    aim at: 223 of them against 5 inspection requests.

    From above it is four shapes that cannot be mistaken: a fuselage, two
    swept wings, a tailplane.
    """
    # fuselage
    draw.polygon([(64, 10), (72, 34), (72, 96), (56, 96), (56, 34)],
                 fill=colour)
    # wings, swept back
    draw.polygon([(56, 44), (10, 78), (10, 90), (56, 74)], fill=colour)
    draw.polygon([(72, 44), (118, 78), (118, 90), (72, 74)], fill=colour)
    # tailplane
    draw.polygon([(56, 92), (36, 108), (36, 116), (92, 116), (92, 108),
                  (72, 92)], fill=colour)


def alarm(draw, colour):
    """An exclamation in a triangle: emergency leave.

    A bell was drawn first and read as a table lamp. This one needs no
    learning at all - it is the warning sign on every road and every machine,
    and at 64 pixels that matters more than being original.
    """
    draw.polygon([(64, 12), (120, 112), (8, 112)], outline=colour, width=8)
    draw.line([(64, 46), (64, 82)], fill=colour, width=9)
    draw.ellipse([58, 92, 70, 104], fill=colour)


def door(draw, colour):
    """A door with an arrow leaving it: resignation."""
    draw.rounded_rectangle([20, 16, 68, SIZE - 16], radius=4,
                           outline=colour, width=7)
    draw.line([(76, 64), (114, 64)], fill=colour, width=7)
    draw.polygon([(104, 50), (118, 64), (104, 78)], fill=colour)


def glass(draw, colour):
    """A magnifying glass over a sheet: inspection."""
    draw.rounded_rectangle([18, 14, 84, 96], radius=5, outline=colour, width=7)
    draw.ellipse([54, 50, 106, 102], outline=colour, width=7)
    draw.line([(100, 96), (118, 114)], fill=colour, width=8)


def tick(draw, colour):
    """A sheet with a tick: clearance."""
    draw.rounded_rectangle([22, 14, 92, 100], radius=5, outline=colour, width=7)
    draw.line([(46, 62), (62, 78)], fill=colour, width=8)
    draw.line([(62, 78), (100, 34)], fill=colour, width=8)


def upload(draw, colour):
    """A sheet with an arrow up: a submittal."""
    draw.rounded_rectangle([22, 40, 106, SIZE - 14], radius=5,
                           outline=colour, width=7)
    draw.line([(64, 96), (64, 20)], fill=colour, width=7)
    draw.polygon([(48, 34), (64, 14), (80, 34)], fill=colour)


def rosette(draw, colour):
    """A seal with ribbons: prequalification."""
    draw.ellipse([32, 12, 96, 76], outline=colour, width=7)
    draw.line([(46, 72), (40, 116)], fill=colour, width=7)
    draw.line([(82, 72), (88, 116)], fill=colour, width=7)
    draw.line([(40, 116), (64, 100)], fill=colour, width=7)
    draw.line([(88, 116), (64, 100)], fill=colour, width=7)


def blueprint(draw, colour):
    """A drawing sheet with a plan on it: shop drawings."""
    draw.rounded_rectangle([14, 24, SIZE - 14, 104], radius=5,
                           outline=colour, width=7)
    draw.rectangle([34, 44, 68, 84], outline=colour, width=6)
    draw.line([(68, 64), (94, 64)], fill=colour, width=6)
    draw.line([(94, 50), (94, 84)], fill=colour, width=6)


def certificate(draw, colour):
    """A sheet with a seal: a certificate."""
    draw.rounded_rectangle([18, 18, 100, 90], radius=5, outline=colour, width=7)
    draw.line([(34, 42), (84, 42)], fill=colour, width=6)
    draw.line([(34, 58), (68, 58)], fill=colour, width=6)
    draw.ellipse([72, 72, 116, 116], outline=colour, width=7)
    draw.line([(94, 84), (94, 104)], fill=colour, width=6)


def star_certificate(draw, colour):
    """A sheet with a star: experience."""
    draw.rounded_rectangle([18, 18, 100, 100], radius=5, outline=colour, width=7)
    draw.line([(34, 44), (84, 44)], fill=colour, width=6)
    points = [(64, 56), (72, 76), (94, 76), (76, 88), (83, 108),
              (64, 96), (45, 108), (52, 88), (34, 76), (56, 76)]
    draw.polygon(points, fill=colour)


def invoice(draw, colour):
    """A sheet with a total ruled under it: a payment certificate."""
    draw.rounded_rectangle([22, 12, 106, 110], radius=5, outline=colour, width=7)
    for y in (40, 58):
        draw.line([(40, y), (88, y)], fill=colour, width=6)
    draw.line([(40, 78), (88, 78)], fill=colour, width=6)
    draw.line([(40, 88), (88, 88)], fill=colour, width=3)


ICONS = {
    'mr': (box, SLATE),
    'spc': (invoice, GREEN),
    'ir': (glass, SLATE),
    'icr': (tick, SLATE),
    'msr': (upload, SLATE),
    'pqs': (rosette, AMBER),
    'sds': (blueprint, SLATE),
    'alr': (plane, BLUE),
    'elr': (alarm, BLUE),
    'asr': (money, GREEN),
    'res': (door, BLUE),
    'sc': (certificate, AMBER),
    'ec': (star_certificate, AMBER),
}


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for code, (glyph, colour) in ICONS.items():
        image, draw = canvas()
        glyph(draw, colour + (255,))
        image.save(os.path.join(OUT, '%s.png' % code), 'PNG')
    print("%s icon(s) written to %s" % (len(ICONS), OUT))
