from paper_reader.zotero import ZoteroLibrary


def test_collections_tree(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        by_name = {c.name: c for c in lib.collections()}
    finally:
        lib.close()
    assert set(by_name) == {"课题组", "蜜罐", "研讨厅第一篇"}  # deleted collection excluded
    assert by_name["课题组"].parent_id is None
    assert by_name["蜜罐"].parent_id == by_name["课题组"].collection_id
    assert by_name["课题组"].item_count == 1
    assert by_name["研讨厅第一篇"].item_count == 1
