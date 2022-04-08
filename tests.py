from main import sed

def test_single_single():
    assert sed("foo/bar/", "foo") == "bar"

def test_single_multi():
    assert sed("foo/bar", "foo foo foo") == "bar foo foo"

def test_multi_single():
    assert sed("foo/bar/g", "foo bar") == "bar bar"

def test_multi_multi():
    assert sed("foo/bar/g", "foo foo foo") == "bar bar bar"

def test_non_slash_delim_single_single():
    assert sed("foo-bar", "foo", "-") == "bar"

def test_non_slash_delim_single_multi():
    assert sed("foo-bar", "foo foo foo", "-") == "bar foo foo"

def test_non_slash_delim_multi_single():
    assert sed("foo-bar-g", "foo bar", "-") == "bar bar"

def test_non_slash_delim_multi_multi():
    assert sed("foo-bar-g", "foo foo foo", "-") == "bar bar bar"