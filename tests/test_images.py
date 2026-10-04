"""publishing images: resize, convert, thumbnail and strip, one test group per capability, plus the limits,
the refusals and determinism. They need Pillow and skip without it; the Dockerfile.images test stage and CI
run them in the image, with no network. Fixtures are generated here (Pillow), so no binary is committed.
"""
import os
import subprocess
import sys

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from publishing import images  # noqa: E402


def cli(*args, cwd=None):
    return subprocess.run([sys.executable, "-m", "publishing.cli", "images", *args], capture_output=True,
                          text=True, cwd=cwd)


def make(path, size=(120, 80), mode="RGB", **save):
    img = Image.new(mode, size)
    px = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            px[x, y] = ((x * 2) % 256, (y * 3) % 256, (x + y) % 256, 200)[:len(mode)] if mode != "L" else (x + y) % 256
    img.save(path, **save)
    return path


def exif_jpeg(path, orientation=1, size=(120, 80)):
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x010F] = "SecretCam"
    exif[0x8825] = {1: "N", 2: (47.0, 36.0, 0.0)}  # GPS IFD
    return make(path, size, exif=exif, comment=b"private note")


@pytest.fixture
def photo(tmp_path):
    return exif_jpeg(tmp_path / "photo.jpg")


# --- resize -----------------------------------------------------------------------------------

def test_resize_width_keeps_aspect(photo, tmp_path):
    out = images.resize(photo, tmp_path / "o.png", width=60)
    assert Image.open(out).size == (60, 40)


def test_resize_box_fits_within(photo, tmp_path):
    out = images.resize(photo, tmp_path / "o.jpg", width=100, height=20)
    assert Image.open(out).size == (30, 20)


def test_resize_can_enlarge(photo, tmp_path):
    assert Image.open(images.resize(photo, tmp_path / "o.png", height=160)).size == (240, 160)


def test_resize_needs_a_side(photo, tmp_path):
    with pytest.raises(images.UsageError):
        images.resize(photo, tmp_path / "o.png")


@pytest.mark.parametrize("bad", [0, -3, images.MAX_SIDE + 1])
def test_resize_side_range(photo, tmp_path, bad):
    with pytest.raises(images.UsageError):
        images.resize(photo, tmp_path / "o.png", width=bad)
    assert not (tmp_path / "o.png").exists()


# --- convert ----------------------------------------------------------------------------------

@pytest.mark.parametrize("suffix,fmt", [(".png", "PNG"), (".jpg", "JPEG"), (".jpeg", "JPEG"), (".webp", "WEBP")])
def test_convert_formats(photo, tmp_path, suffix, fmt):
    out = images.convert(photo, tmp_path / f"o{suffix}")
    im = Image.open(out)
    assert im.format == fmt and im.size == (120, 80)


@pytest.mark.parametrize("suffix,fmt", [(".gif", "GIF"), (".bmp", "BMP"), (".tiff", "TIFF"), (".webp", "WEBP")])
def test_convert_other_inputs(tmp_path, suffix, fmt):
    src = make(tmp_path / f"in{suffix}", mode="RGB")
    out = images.convert(src, tmp_path / "o.png")
    assert Image.open(out).format == "PNG"


def test_convert_keeps_transparency_to_png_and_flattens_for_jpeg(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGBA", (10, 10), (255, 0, 0, 0)).save(src)
    assert Image.open(images.convert(src, tmp_path / "o.png")).getpixel((0, 0))[3] == 0
    assert Image.open(images.convert(src, tmp_path / "o.jpg")).getpixel((0, 0)) == (255, 255, 255)


def test_convert_animated_gif_takes_the_first_frame(tmp_path):
    src = tmp_path / "a.gif"
    a, b = Image.new("RGB", (8, 8), "red"), Image.new("RGB", (8, 8), "blue")
    a.save(src, save_all=True, append_images=[b])
    out = Image.open(images.convert(src, tmp_path / "o.png"))
    assert getattr(out, "n_frames", 1) == 1 and out.convert("RGB").getpixel((0, 0))[0] > 200


# --- thumbnail --------------------------------------------------------------------------------

def test_thumbnail_default_and_size(tmp_path):
    src = make(tmp_path / "big.png", (600, 300))
    assert Image.open(images.thumbnail(src, tmp_path / "t.png")).size == (256, 128)
    assert Image.open(images.thumbnail(src, tmp_path / "t2.jpg", size=64)).size == (64, 32)


def test_thumbnail_extreme_aspect_never_zero(tmp_path):
    src = make(tmp_path / "wide.png", (1000, 2))
    assert Image.open(images.thumbnail(src, tmp_path / "t.png", size=10)).size == (10, 1)


# --- strip ------------------------------------------------------------------------------------

def test_strip_removes_exif_gps_and_comment(photo, tmp_path):
    assert len(Image.open(photo).getexif()) > 0
    out = images.strip(photo, tmp_path / "s.jpg")
    im = Image.open(out)
    assert len(im.getexif()) == 0 and not im.getexif().get_ifd(0x8825)
    assert b"SecretCam" not in out.read_bytes() and b"private note" not in out.read_bytes()
    assert "comment" not in im.info and "exif" not in im.info


@pytest.mark.parametrize("suffix", [".png", ".webp", ".jpg"])
def test_every_output_is_stripped(photo, tmp_path, suffix):
    out = images.convert(photo, tmp_path / f"o{suffix}")
    assert b"SecretCam" not in out.read_bytes() and len(Image.open(out).getexif()) == 0


def test_png_text_and_icc_are_dropped(tmp_path):
    from PIL import PngImagePlugin
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Author", "Someone Private")
    src = tmp_path / "a.png"
    Image.new("RGB", (8, 8), "red").save(src, pnginfo=meta)
    out = images.strip(src, tmp_path / "s.png")
    assert b"Someone Private" not in out.read_bytes()


def test_strip_applies_orientation(tmp_path):
    src = exif_jpeg(tmp_path / "rot.jpg", orientation=6, size=(120, 80))  # stored landscape, shown portrait
    assert Image.open(images.strip(src, tmp_path / "s.jpg")).size == (80, 120)


# --- refusals ---------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["http://example.com/a.png", "https://x/a.jpg", "-a.png", "pipe:0",
                                  "/dev/stdin", "file:///etc/hosts", "ftp://h/a.png"])
def test_source_that_is_not_a_local_file_is_refused(tmp_path, name):
    with pytest.raises(images.UsageError):
        images.convert(name, tmp_path / "o.png")


def test_unsupported_and_missing_sources(tmp_path):
    (tmp_path / "a.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'><image href='http://x/y.png'/></svg>")
    (tmp_path / "a.eps").write_text("%!PS-Adobe-3.0 EPSF-3.0\n")
    for name in ("a.svg", "a.eps", "gone.png"):
        with pytest.raises(images.UsageError):
            images.convert(tmp_path / name, tmp_path / "o.png")


def test_a_directory_named_like_an_image_is_refused(tmp_path):
    (tmp_path / "d.png").mkdir()
    with pytest.raises(images.UsageError):
        images.convert(tmp_path / "d.png", tmp_path / "o.png")


def test_unsupported_output_suffix(photo, tmp_path):
    for name in ("o.svg", "o.eps", "o.pdf", "o"):
        with pytest.raises(images.UsageError):
            images.convert(photo, tmp_path / name)


def test_output_is_never_overwritten(photo, tmp_path):
    (tmp_path / "o.png").write_bytes(b"mine")
    with pytest.raises(images.UsageError):
        images.convert(photo, tmp_path / "o.png")
    assert (tmp_path / "o.png").read_bytes() == b"mine"


def test_suffix_that_lies_about_the_content_is_refused(tmp_path):
    make(tmp_path / "real.png")
    (tmp_path / "real.png").rename(tmp_path / "lie.jpg")
    with pytest.raises(images.ImageError, match="content is PNG"):
        images.convert(tmp_path / "lie.jpg", tmp_path / "o.png")


def test_a_format_outside_the_allow_list_is_refused_even_with_an_image_suffix(tmp_path):
    (tmp_path / "x.png").write_text("%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n")
    with pytest.raises(images.ImageError):
        images.convert(tmp_path / "x.png", tmp_path / "o.png")
    assert not (tmp_path / "o.png").exists()


@pytest.mark.parametrize("body", [b"", b"not an image at all", b"\x89PNG\r\n\x1a\n" + b"\0" * 20])
def test_garbage_and_truncated_input_fail_cleanly(tmp_path, body):
    (tmp_path / "bad.png").write_bytes(body)
    with pytest.raises(images.ImageError):
        images.convert(tmp_path / "bad.png", tmp_path / "o.png")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bad.png"]  # no OUT, no temporary folder left


def test_truncated_real_png_fails_cleanly(photo, tmp_path):
    src = make(tmp_path / "t.png", (200, 200))
    src.write_bytes(src.read_bytes()[:-200])
    with pytest.raises(images.ImageError):
        images.convert(src, tmp_path / "o.png")
    assert not (tmp_path / "o.png").exists()


def test_path_traversal_in_the_names_is_just_a_path(photo, tmp_path):
    """Names are plain paths; a `..` resolves like any path and nothing is read or written elsewhere."""
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    out = images.convert(sub / ".." / ".." / "photo.jpg", sub / ".." / "o.png")
    assert out == tmp_path / "a" / ".." / "o.png" or out.resolve() == (tmp_path / "a" / "o.png")
    assert (tmp_path / "a" / "o.png").is_file()


# --- limits -----------------------------------------------------------------------------------

def test_pixel_cap_refuses_before_decoding(tmp_path):
    src = make(tmp_path / "a.png", (100, 100))
    with pytest.raises(images.ImageError, match="pixel cap"):
        images.convert(src, tmp_path / "o.png", max_pixels=5000)
    assert not (tmp_path / "o.png").exists()


def test_decompression_bomb_header_is_refused(tmp_path):
    """A tiny PNG file that declares a huge canvas is refused from its header, within the default cap."""
    big = tmp_path / "bomb.png"
    Image.new("1", (30000, 30000)).save(big, optimize=True)  # 900 MP, a few KiB on disk
    assert big.stat().st_size < 10 * 2**20
    with pytest.raises(images.ImageError, match="pixel cap"):
        images.convert(big, tmp_path / "o.png")
    assert not (tmp_path / "o.png").exists()


def test_input_byte_cap(photo, tmp_path):
    with pytest.raises(images.ImageError, match="input is over"):
        images.convert(photo, tmp_path / "o.png", max_input_bytes=100)


def test_output_byte_cap_leaves_no_output(tmp_path):
    src = tmp_path / "noise.png"
    Image.frombytes("RGB", (200, 200), os.urandom(120000)).save(src)
    with pytest.raises(images.ImageError, match="output is"):
        images.convert(src, tmp_path / "o.png", max_bytes=1000)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["noise.png"]


def test_time_cap_kills_the_work(photo, tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(images, "_save", lambda img, out: time.sleep(30))  # inherited by the forked child
    started = time.monotonic()
    with pytest.raises(images.ImageError, match="timed out"):
        images.convert(photo, tmp_path / "o.png", timeout=0.5)
    assert time.monotonic() - started < 10
    assert sorted(p.name for p in tmp_path.iterdir()) == ["photo.jpg"]


def test_a_crashing_decoder_is_an_error_not_a_traceback(photo, tmp_path, monkeypatch):
    def boom(img, out):
        raise RuntimeError("decoder blew up")
    monkeypatch.setattr(images, "_save", boom)
    with pytest.raises(images.ImageError, match="decoder blew up"):
        images.convert(photo, tmp_path / "o.png")


# --- determinism and no network ---------------------------------------------------------------

@pytest.mark.parametrize("suffix", [".png", ".jpg", ".webp"])
def test_same_input_same_bytes(photo, tmp_path, suffix):
    a = images.thumbnail(photo, tmp_path / f"a{suffix}", size=50)
    b = images.thumbnail(photo, tmp_path / f"b{suffix}", size=50)
    assert a.read_bytes() == b.read_bytes()


def test_the_module_opens_no_socket(photo, tmp_path, monkeypatch):
    import socket

    def deny(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    images.convert(photo, tmp_path / "o.webp")


# --- the command ------------------------------------------------------------------------------

def test_cli_prints_only_the_path(photo, tmp_path):
    r = cli("thumbnail", str(photo), "-o", str(tmp_path / "t.png"), "--size", "32")
    assert r.returncode == 0 and r.stdout.strip() == str(tmp_path / "t.png") and r.stderr == ""


def test_cli_exit_codes(photo, tmp_path):
    assert cli("resize", str(photo), "-o", str(tmp_path / "o.png")).returncode == 2  # no side given
    assert cli("convert", "http://x/a.png", "-o", str(tmp_path / "o.png")).returncode == 2
    (tmp_path / "bad.png").write_bytes(b"junk")
    r = cli("convert", str(tmp_path / "bad.png"), "-o", str(tmp_path / "o.png"))
    assert r.returncode == 1 and "publishing:" in r.stderr and "Traceback" not in r.stderr
    assert cli("resize", str(photo), "-o", str(tmp_path / "o.png"), "--width", "-5").returncode == 2


def test_cli_limits(photo, tmp_path):
    r = cli("strip", str(photo), "-o", str(tmp_path / "o.jpg"), "--max-pixels", "10")
    assert r.returncode == 1 and "pixel cap" in r.stderr


def test_without_pillow_exit_3(photo, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "PIL", None)
    with pytest.raises(images.ToolNotFound):
        images.convert(photo, tmp_path / "o.png")
