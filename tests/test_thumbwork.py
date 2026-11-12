"""Making thumbnails: exact sizes, the disk cache, and never raising on a bad file."""

import io

from PIL import Image

from magpie.ui import thumbwork


def _png(w, h, colour=(200, 30, 30), mode="RGB"):
    out = io.BytesIO()
    Image.new(mode, (w, h), colour).save(out, "PNG")
    return out.getvalue()


def test_stamp_is_exactly_the_box_whatever_the_picture():
    for size in ((2560, 1440), (100, 900), (150, 104), (7, 5)):
        raw = thumbwork.stamp(_png(*size), 150, 104)
        assert (raw.width, raw.height) == (150, 104), size
        assert len(raw.data) == raw.stride * raw.height


def test_stamp_crops_from_the_centre():
    im = Image.new("RGB", (400, 100), (255, 0, 0))
    im.paste((0, 0, 255), (150, 0, 250, 100))               # the middle 100 px are blue
    out = io.BytesIO(); im.save(out, "PNG")
    raw = thumbwork.stamp(out.getvalue(), 100, 100)
    px = raw.data[(50 * 100 + 50) * 3: (50 * 100 + 50) * 3 + 3]
    assert px[2] > 200 and px[0] < 60


def test_preview_fits_inside_and_never_enlarges():
    big = thumbwork.preview(_png(4000, 2000), 1400)
    assert (big.width, big.height) == (1400, 700)
    small = thumbwork.preview(_png(300, 200), 1400)
    assert (small.width, small.height) == (300, 200)


def test_transparency_is_kept():
    raw = thumbwork.stamp(_png(50, 50, (255, 0, 0, 0), "RGBA"), 20, 20)
    assert raw.mode == "RGBA"
    assert raw.data[3] == 0


def test_a_broken_file_is_a_miss_not_an_error():
    assert thumbwork.stamp(b"not a picture", 10, 10) is None
    assert thumbwork.preview(b"", 100) is None


def test_disk_cache_round_trip(tmp_path):
    raw = thumbwork.stamp(_png(640, 360), 150, 104)
    assert thumbwork.load_cached(tmp_path, "ab" * 32, 150, 104) is None
    thumbwork.store_cached(tmp_path, "ab" * 32, raw)
    back = thumbwork.load_cached(tmp_path, "ab" * 32, 150, 104)
    assert (back.width, back.height, back.mode) == (150, 104, "RGB")
    # lossy, but a flat red stays red
    assert abs(back.data[0] - 200) < 8 and back.data[1] < 60


def test_a_corrupt_cache_file_is_a_miss(tmp_path):
    path = thumbwork.cached_path(tmp_path, "cd" * 32, 10, 10, "jpg")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xd8 broken")
    assert thumbwork.load_cached(tmp_path, "cd" * 32, 10, 10) is None


def test_no_half_written_file_is_left_behind(tmp_path):
    thumbwork.store_cached(tmp_path, "ef" * 32, thumbwork.stamp(_png(80, 60), 40, 30))
    names = [p.name for p in tmp_path.rglob("*") if p.is_file()]
    assert names == [f"{'ef' * 32}-40x30.jpg"]
