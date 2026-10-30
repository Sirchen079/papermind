from app.desktop import loading_page


def test_loading_error_is_readable_and_escaped():
    page = loading_page('连接失败\n<script>alert("x")</script>', error=True)
    assert 'role="alert"' in page
    assert '连接失败\n&lt;script&gt;' in page
    assert '<script>alert(' not in page
    assert 'class="boot failed"' in page


def test_loading_uses_bundled_brand_without_external_requests(tmp_path, monkeypatch):
    from app import desktop_loading

    (tmp_path / 'desktop').mkdir()
    (tmp_path / 'desktop' / 'papermind.svg').write_text('<svg id="test-bundled-mark"></svg>', encoding='utf-8')
    monkeypatch.setattr(desktop_loading.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(desktop_loading.sys, '_MEIPASS', str(tmp_path), raising=False)
    page = loading_page()
    assert 'test-bundled-mark' in page
    assert 'role="status"' in page
    assert '<img ' not in page


def test_missing_cosmetic_asset_does_not_prevent_startup(tmp_path, monkeypatch):
    from app import desktop_loading

    monkeypatch.setattr(desktop_loading.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(desktop_loading.sys, '_MEIPASS', str(tmp_path), raising=False)
    assert '正在启动' in loading_page()
