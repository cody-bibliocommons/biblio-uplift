"""Test __main__.py entry point."""


def test_main_module_import():
    """Importing __main__ exercises the module-level code."""
    import biblio_uplift.__main__  # noqa: F401

    assert True
