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


def _item_by_title(lib, title):
    for it in lib.items():
        if it.title == title:
            return it
    raise AssertionError(f"item not found: {title}")


def test_item_metadata(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = _item_by_title(lib, "Honeypot Evolution")
    finally:
        lib.close()
    assert it.item_type == "journalArticle"
    assert it.creators == ["Alice Smith", "Bob Jones"]
    assert it.year == 2024
    assert it.publication == "Security"
    assert it.doi == "10.1000/example"
    assert set(it.collections) == {"课题组", "蜜罐"}
    assert it.key == "ITEM1"


def test_item_editors_excluded_and_single_field(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = _item_by_title(lib, "Agentic AI Threats")
        it3 = _item_by_title(lib, "Retrieval for Science")
    finally:
        lib.close()
    assert it.creators == ["Carol Brown"]  # editor George excluded
    assert it3.creators == ["Dave"]  # fieldMode=1: lastName holds full name


def test_item_year_parsing(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = _item_by_title(lib, "Retrieval for Science")
    finally:
        lib.close()
    assert it.year == 2022


def test_deleted_and_note_items_excluded(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        titles = [it.title for it in lib.items()]
    finally:
        lib.close()
    assert "Ghost Paper" in titles
    assert "DELETED" not in titles
    assert "NOTE5" not in titles


def test_items_by_collection(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        in_seminar = [it.title for it in lib.items(collection_id=3)]
        empty = lib.items(collection_id=99)
    finally:
        lib.close()
    assert in_seminar == ["Agentic AI Threats"]
    assert empty == []


def test_resolve_pdf_stored(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = next(i for i in lib.items() if i.title == "Honeypot Evolution")
    finally:
        lib.close()
    assert it.has_pdf is True
    assert it.pdf_path == zotero_db / "storage" / "ATT11" / "Honeypot Evolution.pdf"


def test_resolve_pdf_linked_file(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = next(i for i in lib.items() if i.title == "Retrieval for Science")
    finally:
        lib.close()
    assert it.has_pdf is True
    assert it.pdf_path is not None and it.pdf_path.is_absolute()
    assert it.pdf_path.name == "linked.pdf"


def test_resolve_pdf_missing_file(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = next(i for i in lib.items() if i.title == "Ghost Paper")
    finally:
        lib.close()
    assert it.has_pdf is False
    assert it.pdf_path is None


def test_item_without_pdf(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = next(i for i in lib.items() if i.title == "Agentic AI Threats")
    finally:
        lib.close()
    assert it.has_pdf is False
    assert it.pdf_path is None
    assert lib.resolve_pdf(it) is None


def test_search_title_case_insensitive(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        hits = [it.title for it in lib.search("HONEYPOT")]
    finally:
        lib.close()
    assert hits == ["Honeypot Evolution"]


def test_search_creator(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        hits = [it.title for it in lib.search("bob")]
    finally:
        lib.close()
    assert hits == ["Honeypot Evolution"]


def test_search_sorted_and_limited(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        hits = [it.title for it in lib.search("i", limit=1)]
    finally:
        lib.close()
    assert hits == ["Agentic AI Threats"]  # first of [Agentic..., Retrieval...] sorted


def test_search_no_match(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        hits = lib.search("zzz")
    finally:
        lib.close()
    assert hits == []


def test_get_item(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = lib.get_item(1)
        missing = lib.get_item(999)
    finally:
        lib.close()
    assert it is not None and it.title == "Honeypot Evolution"
    assert missing is None
