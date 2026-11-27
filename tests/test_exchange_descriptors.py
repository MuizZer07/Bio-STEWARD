"""Every directory descriptor `exchange.write_new` holds is released (0.21.0, found by tools/ci_local.sh).

`write_new` keeps a duplicate of the item's directory for a rollback until the caller records the item's state. The
`.keep` files of `exchange init` and a one-way item record no state, and their holds were never released: four
descriptors per `exchange init`, one per one-way item. A command exits and frees them, but a long-lived process (the
MCP server, the test suite) ran out of descriptors under a 1024 limit."""

from steward import exchange


def _init(cli, tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    assert cli("init", "--repo", root)[0] == 0
    with (root / "steward.toml").open("a") as f:
        f.write('\n[exchange]\ncode = "ABC"\n')
    return root


def test_exchange_init_holds_no_directory_descriptor(cli, tmp_path):
    root = _init(cli, tmp_path)
    before = dict(exchange.CREATED)
    assert cli("exchange", "init", "--repo", root)[0] == 0
    assert exchange.CREATED == before


def test_a_one_way_item_holds_no_directory_descriptor(cli, tmp_path):
    root = _init(cli, tmp_path)
    assert cli("exchange", "init", "--repo", root)[0] == 0
    before = dict(exchange.CREATED)
    code, _, err = cli("exchange", "new", "feedback", "--repo", root, "--oneway", "--to", "XYZ",
                       "--title", "A one-way note", "--channel", "an issue URL")
    assert code == 0, err
    assert list((root / "exchange/oneway").glob("*.md"))
    assert exchange.CREATED == before
