"""The video format, end to end through the pinned toolchain (`publishing setup --video` once, and ffmpeg)."""
import shutil
import subprocess

import pytest

from publishing import video
from publishing.build import BuildError, build, check, discover, render, resolve
from publishing.cli import main
from publishing.config import load


def new(repo, name="clip-v1"):
    folder = repo / "docs" / "notes" / name
    assert main(["new", str(folder), "--format", "video"]) == 0
    return folder


def composition(body: str, *, duration=1, style="") -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{style}</style></head><body>'
            f'<div id="root" data-composition-id="root" data-no-timeline data-width="1920" data-height="1080" '
            f'data-fps="10" data-start="0" data-duration="{duration}">'
            f'<section id="s" class="slide clip" data-start="0" data-duration="{duration}" data-track-index="0">'
            f"{body}</section></div></body></html>")


def test_scaffold_builds_reproduces_its_bytes_and_checks_current(repo, renderer, tmp_path):
    folder = new(repo)
    cfg = load(folder)
    s = resolve(folder, cfg)
    assert s.kind == "video" and s.pdf.name == "clip-v1.mp4"
    assert build(s, cfg, renderer) == "built"
    info = video.probe(s.pdf)
    assert (info["width"], info["height"], info["fps"], info["frames"]) == (1920, 1080, "30/1", 270)
    assert info["source"] == video.digest(folder)
    again = tmp_path / "again.mp4"
    assert render(s, cfg, again, renderer) == []
    assert again.read_bytes() == s.pdf.read_bytes()  # the same toolchain renders the same bytes
    assert build(s, cfg, renderer) == "current"
    assert check(s, cfg, renderer) is None


def test_check_finds_a_changed_source_missing_and_orphan(repo, renderer):
    folder = repo / "docs" / "notes" / "tiny-v1"
    folder.mkdir()
    (folder / "video.html").write_text(composition("<h1>One</h1>"))
    cfg = load(folder)
    s = resolve(folder, cfg)
    assert check(s, cfg, renderer).endswith("missing (build it: publishing build tiny-v1)")
    build(s, cfg, renderer)
    (folder / "video.html").write_text(composition("<h1>Two</h1>"))
    assert "stale (its source changed" in check(s, cfg, renderer)
    shutil.copy(s.pdf, repo / "docs" / "notes" / "lost-v1.mp4")
    sources, orphans = discover(repo / "docs", cfg)
    assert [x.kind for x in sources] == ["video"] and [o.name for o in orphans] == ["lost-v1.mp4"]


@pytest.mark.parametrize("body,style,problem", [
    ("<h1>Hello</h1>", "h1 { font-family: sans-serif; }", "not vendored"),
    ('<img src="https://example.com/logo.png">', "", "loads from the network"),
    ('<svg viewBox="0 0 10 10"><rect class="fade" width="5" height="5"/></svg>', "", "CSS animation on an SVG element"),
    ("<h1>The token ghp_" + "a" * 36 + "</h1>", "", "secret"),
    ("<h1>Seen at /home/someone/x</h1>", "", "host detail"),
])
def test_the_house_gates_stop_a_video(repo, renderer, body, style, problem):
    folder = repo / "docs" / "notes" / "bad-v1"
    folder.mkdir()
    (folder / "video.html").write_text(composition(body, style=style))
    cfg = load(folder)
    with pytest.raises(BuildError, match=problem):
        build(resolve(folder, cfg), cfg, renderer)
    assert not (repo / "docs" / "notes" / "bad-v1.mp4").exists()


def test_hyperframes_check_gates_layout_and_contrast(repo, renderer):
    folder = repo / "docs" / "notes" / "faint-v1"
    folder.mkdir()
    (folder / "video.html").write_text(composition('<h1 style="color: #eeeeea">Too faint to read</h1>'))
    cfg = load(folder)
    with pytest.raises(BuildError, match="contrast_aa_failure"):
        build(resolve(folder, cfg), cfg, renderer)


def test_a_video_folder_reserves_index_html(repo, renderer):
    folder = new(repo, "own-v1")
    (folder / "index.html").write_text("<p>mine</p>")
    cfg = load(folder)
    with pytest.raises(BuildError, match="reserved"):
        build(resolve(folder, cfg), cfg, renderer)


def test_a_video_is_not_converted_to_another_format(repo):
    folder = new(repo, "fmt-v1")
    with pytest.raises(BuildError, match="does not convert"):
        resolve(folder, load(folder), "memo")


# ---------------------------------------------------------------- compare, on clips ffmpeg makes

def clip(path, *, src="testsrc2", crf=16, frames=20, stamp="a" * 64):
    tags = ["-metadata", f"comment=publishing test source sha256:{stamp}"] if stamp else []
    subprocess.run([video.ff("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=size=320x180:rate=10",
                    "-frames:v", str(frames), "-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p", *tags,
                    str(path)], check=True)
    return path


def test_compare_accepts_identical_and_reencoded_frames(tmp_path):
    a = clip(tmp_path / "a.mp4")
    assert video.compare(a, clip(tmp_path / "same.mp4"), 45) is None
    assert video.compare(a, clip(tmp_path / "reencoded.mp4", crf=12), 45) is None  # another encoder's take


def test_compare_refuses_other_frames_geometry_or_source(tmp_path):
    a = clip(tmp_path / "a.mp4")
    assert "dB PSNR, tolerance 45 dB" in video.compare(a, clip(tmp_path / "other.mp4", src="testsrc"), 45)
    assert "frames 20 committed, 10" in video.compare(a, clip(tmp_path / "short.mp4", frames=10), 45)
    assert "its source changed" in video.compare(a, clip(tmp_path / "src.mp4", stamp="b" * 64), 45)
    assert "not stamped" in video.compare(clip(tmp_path / "bare.mp4", stamp=None), a, 45)


# ---------------------------------------------------------------- the CLI contract

def test_exit_codes_distinguish_usage_and_toolchain(repo, tmp_path, monkeypatch, capsys):
    folder = new(repo, "codes-v1")
    with pytest.raises(SystemExit) as e:
        main(["build", str(repo / "docs" / "missing-v1.mp4")])
    assert e.value.code == 2  # not a source: usage
    monkeypatch.setenv("PUBLISHING_CACHE", str(tmp_path / "empty-cache"))
    with pytest.raises(SystemExit) as e:
        main(["build", str(folder)])
    assert e.value.code == 3 and "publishing setup --video" in capsys.readouterr().err  # toolchain


def test_user_content_mode_refuses_a_video(repo):
    from publishing.usercontent import UserContentRenderer

    folder = new(repo, "untrusted-v1")
    cfg = load(folder)
    with UserContentRenderer() as r, pytest.raises(BuildError, match="outside the sandbox"):
        build(resolve(folder, cfg), cfg, r)
    assert not folder.with_suffix(".mp4").exists()
